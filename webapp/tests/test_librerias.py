"""
`webapp.librerias`: las librerías Python que pide un plugin. La convención
(versión fija y hash por línea, sólo wheels) se hace cumplir acá, antes de
que pip vea el archivo; pip se prueba con un `correr` falso, porque instalar
de verdad tocaría el intérprete de estos tests.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import librerias  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
REQS_OK = f"""# librerías de cómputo del plugin
numpy==2.3.1 --hash=sha256:{HASH_A} \\
    --hash=sha256:{HASH_B}
trimesh==4.6.0  --hash=sha256:{HASH_B}
"""


def _plugin(tmp_path, requisitos: str | None = REQS_OK, wheels: bool = False) -> pathlib.Path:
    carpeta = tmp_path / "convertidor"
    carpeta.mkdir(parents=True)
    (carpeta / "__init__.py").write_text("PLUGIN = None\n", encoding="utf-8")
    if requisitos is not None:
        (carpeta / "requirements.txt").write_text(requisitos, encoding="utf-8")
    if wheels:
        (carpeta / "wheels").mkdir()
        (carpeta / "wheels" / "numpy-2.3.1-cp312-cp312-win_amd64.whl").write_bytes(b"PK")
    return carpeta


# ── La convención ───────────────────────────────────────────────────────


def test_requisitos_de_solo_para_carpetas(tmp_path):
    carpeta = _plugin(tmp_path)
    assert librerias.requisitos_de(carpeta) == carpeta / "requirements.txt"
    assert librerias.requisitos_de(_plugin(tmp_path / "otro", requisitos=None)) is None
    suelto = tmp_path / "suelto.py"
    suelto.write_text("PLUGIN = None\n", encoding="utf-8")
    assert librerias.requisitos_de(suelto) is None


def test_lee_versiones_y_hashes_con_continuaciones(tmp_path):
    reqs = librerias.leer_requisitos(_plugin(tmp_path) / "requirements.txt")
    assert [(r["name"], r["version"]) for r in reqs] == [("numpy", "2.3.1"), ("trimesh", "4.6.0")]
    assert reqs[0]["hashes"] == [HASH_A, HASH_B]
    assert reqs[1]["hashes"] == [HASH_B]


@pytest.mark.parametrize("linea, motivo", [
    ("numpy>=2", "sin versión fija"),
    (f"numpy --hash=sha256:{HASH_A}", "sin versión fija"),
    ("numpy==2.3.1", "sin `--hash"),
    ("numpy==2.3.1 --hash=md5:abc", "forma"),
    ("-e git+https://x/y.git#egg=z", "opciones de pip"),
    ("--index-url https://otro/simple", "opciones de pip"),
])
def test_rechaza_lo_que_no_cumple(tmp_path, linea, motivo):
    carpeta = _plugin(tmp_path, requisitos=linea + "\n")
    with pytest.raises(librerias.LibreriasError) as exc:
        librerias.leer_requisitos(carpeta / "requirements.txt")
    assert any(motivo in d for d in exc.value.detalle), exc.value.detalle


def test_estado_compara_con_lo_instalado(tmp_path):
    # pytest está en este intérprete; "una-libreria-que-no-existe" no.
    import pytest as pt
    reqs = [
        {"name": "pytest", "version": pt.__version__, "hashes": [HASH_A]},
        {"name": "pytest", "version": "0.0.1", "hashes": [HASH_A]},
        {"name": "una-libreria-que-no-existe", "version": "1.0", "hashes": [HASH_A]},
    ]
    estado = librerias.estado_de(reqs)
    assert estado[0]["ok"] and estado[0]["installed"] == pt.__version__
    assert not estado[1]["ok"] and estado[1]["installed"] == pt.__version__
    assert not estado[2]["ok"] and estado[2]["installed"] is None


# ── El runtime ──────────────────────────────────────────────────────────


def test_runtime_lee_la_marca_del_exe_o_se_arma_en_vivo(tmp_path):
    vivo = librerias.runtime(tmp_path)
    assert vivo["source"] == "en vivo" and vivo["tag"] is None
    assert vivo["python"] == sys.version.split()[0]
    assert "pytest" in vivo["packages"]

    (tmp_path / "runtime-release.json").write_text(
        '{"tag": "v0.4.2", "python": "3.12.14", "packages": {"fastapi": "0.136.0"}}', encoding="utf-8",
    )
    marcado = librerias.runtime(tmp_path)
    assert marcado["source"] == "instalador" and marcado["tag"] == "v0.4.2" and marcado["python"] == "3.12.14"


# ── pip ─────────────────────────────────────────────────────────────────


def test_el_comando_de_pip_es_solo_wheels_con_hash(tmp_path):
    cmd = librerias.comando_pip(tmp_path / "r.txt", wheels=[tmp_path / "w"], sin_red=True, python="py")
    assert cmd[:4] == ["py", "-m", "pip", "install"]
    assert "--only-binary" in cmd and ":all:" in cmd and "--require-hashes" in cmd
    assert "--no-input" in cmd and "--disable-pip-version-check" in cmd
    assert cmd[cmd.index("--find-links") + 1] == str(tmp_path / "w")
    assert cmd[-1] == "--no-index"
    assert "--no-index" not in librerias.comando_pip(tmp_path / "r.txt", wheels=[], sin_red=False)


def test_carpetas_de_wheels_solo_las_que_tienen_algo(tmp_path):
    plugin = _plugin(tmp_path, wheels=True)
    root = tmp_path / "instalacion"
    (root / "wheels").mkdir(parents=True)  # existe pero vacía: no cuenta
    assert librerias.carpetas_de_wheels(plugin, root) == [plugin / "wheels"]


class _Completado:
    def __init__(self, codigo=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = codigo, stdout, stderr


def test_instalar_llama_a_pip_y_devuelve_el_estado(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, wheels=True)
    llamadas = []

    def correr(cmd, **kw):
        llamadas.append(cmd)
        return _Completado(0, "Successfully installed numpy-2.3.1 trimesh-4.6.0")

    # El estado final se relee en un subproceso real; acá se lo reemplaza.
    monkeypatch.setattr(librerias, "_estado_en_subproceso", lambda reqs, py: [{"name": r["name"], "ok": True} for r in reqs])
    r = librerias.instalar_requisitos(plugin / "requirements.txt", ruta_plugin=plugin, root=tmp_path, correr=correr)
    assert len(llamadas) == 1 and "--require-hashes" in llamadas[0]
    assert str(plugin / "wheels") in llamadas[0]
    assert [e["name"] for e in r["installed"]] == ["numpy", "trimesh"]


def test_si_ya_estan_no_corre_pip(tmp_path, monkeypatch):
    import pytest as pt
    plugin = _plugin(tmp_path, requisitos=f"pytest=={pt.__version__} --hash=sha256:{HASH_A}\n")
    correr = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no tenía que llamar a pip"))  # noqa: E731
    r = librerias.instalar_requisitos(plugin / "requirements.txt", correr=correr)
    assert r["command"] is None and r["installed"][0]["ok"]


def test_un_hash_que_no_coincide_se_explica(tmp_path):
    plugin = _plugin(tmp_path)

    def correr(cmd, **kw):
        return _Completado(1, "", "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.\n    numpy==2.3.1 ...")

    with pytest.raises(librerias.LibreriasError) as exc:
        librerias.instalar_requisitos(plugin / "requirements.txt", ruta_plugin=plugin, correr=correr)
    assert "no coincide" in exc.value.detalle[0]
    assert any("DO NOT MATCH" in d for d in exc.value.detalle)


def test_sin_red_y_sin_wheels_lo_dice_antes_de_pip(tmp_path):
    plugin = _plugin(tmp_path)
    correr = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no tenía que llamar a pip"))  # noqa: E731
    with pytest.raises(librerias.LibreriasError) as exc:
        librerias.instalar_requisitos(plugin / "requirements.txt", ruta_plugin=plugin, root=tmp_path, sin_red=True, correr=correr)
    assert "wheels" in str(exc.value)


def test_pip_que_no_termina(tmp_path):
    plugin = _plugin(tmp_path)

    def correr(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))

    with pytest.raises(librerias.LibreriasError) as exc:
        librerias.instalar_requisitos(plugin / "requirements.txt", ruta_plugin=plugin, correr=correr)
    assert "no terminó" in str(exc.value)


def test_pip_sin_version_dice_que_python_es_y_apunta_al_programa():
    """
    Desde el servidor del repo (3.11) el error de pip hacía pensar que el plugin
    estaba roto, cuando el catálogo lo curó contra el runtime del programa
    (3.12). El mensaje tiene que nombrar la versión y decir a dónde ir.
    """
    lineas = ["ERROR: No matching distribution found for numpy==2.5.3"]
    [mensaje] = librerias._explicar(lineas)
    import sys
    assert sys.version.split()[0] in mensaje
    assert "programa instalado" in mensaje

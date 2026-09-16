"""
Tests de `webapp/plugin_install.py`.

Instalan plugins de verdad en una carpeta temporal, validándolos con el núcleo
real en un subproceso: es lo que hace la API, y un fake acá probaría otra cosa.
Son los tests más lentos de la webapp (un intérprete por validación).
"""

from __future__ import annotations

import pathlib
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import plugin_install as pi  # noqa: E402

PLUGIN_OK = '''
from backend.core import ports as port_names
from backend.core.contract import (
    FunctionTool, Param, Plugin, PluginManifest, ToolContext, ToolManifest, ToolResult,
)

MANIFEST = PluginManifest(name="{name}", label="{name}", version="0.1.0", ports=(port_names.CLOCK,))
SALUDAR = ToolManifest(id="{name}.saludar", label="saludar", category="TEST",
                       params=(Param("a", required=True),))

def _saludar(ctx: ToolContext) -> ToolResult:
    return ToolResult.ok(saludo=f"hola {{ctx.params['a']}}")

PLUGIN = Plugin(manifest=MANIFEST, tools=[FunctionTool(manifest=SALUDAR, fn=_saludar)])
'''

PLUGIN_PORT_INEXISTENTE = PLUGIN_OK.replace("ports=(port_names.CLOCK,)", 'ports=("teletransporte",)')
PLUGIN_ROTO = "raise RuntimeError('me rompo al importar')\n"


def _escribir(carpeta: pathlib.Path, nombre: str, codigo: str) -> pathlib.Path:
    ruta = carpeta / f"{nombre}.py"
    ruta.write_text(codigo.replace("{name}", nombre), encoding="utf-8")
    return ruta


@pytest.fixture
def plugins_dir(tmp_path):
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def origenes(tmp_path):
    d = tmp_path / "origenes"
    d.mkdir()
    return d


def test_instala_un_py_y_lo_lista(plugins_dir, origenes):
    origen = _escribir(origenes, "saludos", PLUGIN_OK)
    resultado = pi.instalar(plugins_dir, origen)
    assert resultado["name"] == "saludos"
    assert (plugins_dir / "saludos.py").is_file()
    assert resultado["plugin"]["tools"] == ["saludos.saludar"]
    assert [p["name"] for p in pi.instalados(plugins_dir)] == ["saludos"]
    # Es una copia: borrar el origen no toca lo instalado.
    origen.unlink()
    assert (plugins_dir / "saludos.py").is_file()


def test_instala_una_carpeta_con_init(plugins_dir, origenes):
    paquete = origenes / "empaquetado"
    paquete.mkdir()
    (paquete / "__init__.py").write_text("from .plugin import PLUGIN\n", encoding="utf-8")
    _escribir(paquete, "plugin", PLUGIN_OK.replace("{name}", "empaquetado"))
    (paquete / "__pycache__").mkdir()
    (paquete / "__pycache__" / "x.pyc").write_bytes(b"")
    resultado = pi.instalar(plugins_dir, paquete)
    assert resultado["name"] == "empaquetado"
    assert (plugins_dir / "empaquetado" / "__init__.py").is_file()
    assert not (plugins_dir / "empaquetado" / "__pycache__").exists()


def test_instala_desde_zip_con_un_py(plugins_dir, origenes):
    py = _escribir(origenes, "zipeado", PLUGIN_OK)
    z = origenes / "cualquier-nombre.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(py, "zipeado.py")
    resultado = pi.instalar(plugins_dir, z)
    assert resultado["name"] == "zipeado"
    assert (plugins_dir / "zipeado.py").is_file()


def test_zip_con_ruta_maliciosa_se_rechaza(plugins_dir, origenes):
    z = origenes / "malo.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../fuera.py", "PLUGIN = None")
    with pytest.raises(pi.InstallError, match="ruta inválida"):
        pi.instalar(plugins_dir, z)
    assert not (origenes / "fuera.py").exists()


def test_un_plugin_que_no_carga_no_se_instala(plugins_dir, origenes):
    origen = _escribir(origenes, "conport", PLUGIN_PORT_INEXISTENTE)
    with pytest.raises(pi.InstallError) as exc:
        pi.instalar(plugins_dir, origen)
    assert exc.value.errores
    assert "teletransporte" in " ".join(exc.value.errores)
    assert list(plugins_dir.iterdir()) == []


def test_un_plugin_que_revienta_al_importar_no_tumba_nada(plugins_dir, origenes):
    origen = _escribir(origenes, "roto", PLUGIN_ROTO)
    with pytest.raises(pi.InstallError) as exc:
        pi.instalar(plugins_dir, origen)
    assert "me rompo" in " ".join(exc.value.errores)
    assert list(plugins_dir.iterdir()) == []


def test_no_pisa_sin_reemplazar_y_reemplaza_si_se_pide(plugins_dir, origenes):
    origen = _escribir(origenes, "saludos", PLUGIN_OK)
    pi.instalar(plugins_dir, origen)
    with pytest.raises(pi.InstallError, match="Ya hay un plugin"):
        pi.instalar(plugins_dir, origen)
    (origenes / "v2").mkdir()
    nuevo = _escribir(origenes / "v2", "saludos", PLUGIN_OK.replace('version="0.1.0"', 'version="0.2.0"'))
    resultado = pi.instalar(plugins_dir, nuevo, reemplazar=True)
    assert resultado["plugin"]["version"] == "0.2.0"
    assert (plugins_dir / "saludos.py").read_text(encoding="utf-8").count("0.2.0") == 1
    # Sin respaldo colgado.
    assert sorted(p.name for p in plugins_dir.iterdir()) == ["saludos.py"]


def test_reemplazar_con_uno_roto_deja_el_anterior(plugins_dir, origenes):
    pi.instalar(plugins_dir, _escribir(origenes, "saludos", PLUGIN_OK))
    roto = origenes / "otro"
    roto.mkdir()
    _escribir(roto, "saludos", PLUGIN_ROTO)
    with pytest.raises(pi.InstallError):
        pi.instalar(plugins_dir, roto / "saludos.py", reemplazar=True)
    assert "0.1.0" in (plugins_dir / "saludos.py").read_text(encoding="utf-8")


def test_nombre_explicito_renombra_el_modulo(plugins_dir, origenes):
    origen = _escribir(origenes, "saludos", PLUGIN_OK)
    resultado = pi.instalar(plugins_dir, origen, nombre="saludos_v2")
    assert resultado["name"] == "saludos_v2"
    assert (plugins_dir / "saludos_v2.py").is_file()


def test_nombre_invalido(plugins_dir, origenes):
    origen = _escribir(origenes, "saludos", PLUGIN_OK)
    with pytest.raises(pi.InstallError, match="inválido"):
        pi.instalar(plugins_dir, origen, nombre="9-mal")


def test_sin_plugins_dir_lo_dice(origenes):
    with pytest.raises(pi.InstallError, match="plugins_dir"):
        pi.instalar(None, _escribir(origenes, "saludos", PLUGIN_OK))


def test_desinstalar_solo_lo_que_vive_en_la_carpeta(plugins_dir, origenes):
    pi.instalar(plugins_dir, _escribir(origenes, "saludos", PLUGIN_OK))
    ruta = pi.desinstalar(plugins_dir, "saludos")
    assert ruta == plugins_dir / "saludos.py"
    assert not ruta.exists()
    with pytest.raises(pi.InstallError, match="No hay ningún plugin"):
        pi.desinstalar(plugins_dir, "saludos")
    with pytest.raises(pi.InstallError):
        pi.desinstalar(plugins_dir, "../fuera")


# ── Librerías del plugin (requirements.txt) ─────────────────────────────

PLUGIN_PAQUETE = PLUGIN_OK  # el mismo código, como __init__.py de una carpeta


def _carpeta_con_requisitos(origenes, nombre, requisitos):
    carpeta = origenes / nombre
    carpeta.mkdir()
    (carpeta / "__init__.py").write_text(PLUGIN_PAQUETE.replace("{name}", nombre), encoding="utf-8")
    (carpeta / "requirements.txt").write_text(requisitos, encoding="utf-8")
    return carpeta


def test_un_requirements_sin_hash_frena_antes_de_copiar(plugins_dir, origenes):
    carpeta = _carpeta_con_requisitos(origenes, "conreq", "numpy==2.3.1\n")
    with pytest.raises(pi.InstallError) as exc:
        pi.instalar(plugins_dir, carpeta)
    assert "librerías" in str(exc.value).lower()
    assert any("--hash" in e for e in exc.value.errores)
    assert not (plugins_dir / "conreq").exists()


def test_instala_las_librerias_antes_de_validar_y_no_copia_wheels(plugins_dir, origenes, monkeypatch):
    carpeta = _carpeta_con_requisitos(origenes, "conreq", "numpy==2.3.1 --hash=sha256:" + "a" * 64 + "\n")
    (carpeta / "wheels").mkdir()
    (carpeta / "wheels" / "numpy-2.3.1-cp312-cp312-win_amd64.whl").write_bytes(b"PK")
    llamadas = []

    def falso_instalar(archivo, **kw):
        llamadas.append((archivo, kw))
        return {"installed": [{"name": "numpy", "required": "2.3.1", "installed": "2.3.1", "ok": True}], "command": ["pip"], "output": ""}

    monkeypatch.setattr(pi.librerias, "instalar_requisitos", falso_instalar)
    r = pi.instalar(plugins_dir, carpeta, root=plugins_dir.parent, sin_red=True)
    assert len(llamadas) == 1
    assert llamadas[0][1]["sin_red"] is True and llamadas[0][1]["root"] == plugins_dir.parent
    assert r["libraries"][0]["name"] == "numpy"
    assert (plugins_dir / "conreq" / "requirements.txt").is_file()
    assert not (plugins_dir / "conreq" / "wheels").exists()
    assert pi.instalados(plugins_dir)[0]["requirements"].endswith("requirements.txt")


def test_si_pip_falla_no_se_copia_nada(plugins_dir, origenes, monkeypatch):
    carpeta = _carpeta_con_requisitos(origenes, "conreq", "numpy==2.3.1 --hash=sha256:" + "a" * 64 + "\n")

    def falla(archivo, **kw):
        raise pi.librerias.LibreriasError("pip no pudo instalar las librerías del plugin", ["No matching distribution"])

    monkeypatch.setattr(pi.librerias, "instalar_requisitos", falla)
    with pytest.raises(pi.InstallError) as exc:
        pi.instalar(plugins_dir, carpeta)
    assert "No matching distribution" in exc.value.errores
    assert not (plugins_dir / "conreq").exists()

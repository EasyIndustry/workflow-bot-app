"""
Tests de `webapp/updates.py`: actualizar el núcleo y la web app desde un release.

Sin red: la API de GitHub se inyecta como JSON, y el "release" es un tarball
armado con el propio `backend/` (o `webapp/`) del repo. La validación sí corre
el núcleo de verdad en un subproceso — es lo que hace la API, y es lo que
importa probar.
"""

from __future__ import annotations

import io
import json
import pathlib
import shutil
import sys
import tarfile
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import updates  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


def _programa_falso(tmp_path) -> pathlib.Path:
    """Una carpeta de programa con una copia del backend/ real, marcada como v-anterior."""
    programa = tmp_path / "programa"
    programa.mkdir()
    shutil.copytree(REPO / "backend", programa / "backend",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data", "tests"))
    return programa


def _tarball_como_github(tmp_path, backend: pathlib.Path, nombre="EasyIndustry-workflow-bot-core-abc123") -> pathlib.Path:
    """El tarball del tag tal como lo da GitHub: una carpeta `owner-repo-sha/` con backend/ adentro."""
    archivo = tmp_path / "core-vX.tar.gz"
    with tarfile.open(archivo, "w:gz") as t:
        t.add(backend, arcname=f"{nombre}/backend",
              filter=lambda m: None if "__pycache__" in m.name else m)
        info = tarfile.TarInfo(f"{nombre}/pyproject.toml")
        datos = b'[project]\nname = "bot-core"\n'
        info.size = len(datos)
        t.addfile(info, io.BytesIO(datos))
    return archivo


# ── releases ────────────────────────────────────────────────────────────

RELEASES = [
    {"tag_name": "v0.3.0", "name": "v0.3.0", "prerelease": False, "draft": False,
     "published_at": "2026-09-10T00:00:00Z", "body": "final", "html_url": "u", "tarball_url": "t", "assets": []},
    {"tag_name": "v0.3.1-beta.1", "prerelease": True, "draft": False,
     "published_at": "2026-09-11T00:00:00Z", "body": "prueba", "html_url": "u", "tarball_url": "t",
     "assets": [{"name": "bot_core.whl", "size": 10, "browser_download_url": "w"}]},
    {"tag_name": "v9-draft", "prerelease": False, "draft": True, "assets": []},
]


def test_disponibles_filtra_borradores_y_pruebas():
    abrir = lambda url, destino=None, token=None: json.dumps(RELEASES).encode()  # noqa: E731
    todos = updates.disponibles(incluir_prueba=True, abrir=abrir)
    assert [r["tag"] for r in todos] == ["v0.3.0", "v0.3.1-beta.1"]
    assert todos[1]["prerelease"] and todos[1]["assets"][0]["name"] == "bot_core.whl"
    estables = updates.disponibles(incluir_prueba=False, abrir=abrir)
    assert [r["tag"] for r in estables] == ["v0.3.0"]


def test_sin_internet_lo_dice_y_sugiere_subir_el_archivo():
    def abrir(url, destino=None, token=None):
        raise urllib.error.URLError("no route to host")
    with pytest.raises(updates.UpdateError, match="sube el archivo"):
        updates.disponibles(abrir=abrir)


def test_tag_invalido_no_llega_a_la_red(tmp_path):
    with pytest.raises(updates.UpdateError, match="Tag inválido"):
        updates.descargar("../x", tmp_path, abrir=lambda *a: None)


# ── preparar ────────────────────────────────────────────────────────────


def test_preparar_encuentra_el_backend_en_el_tarball_de_github(tmp_path):
    programa = _programa_falso(tmp_path)
    archivo = _tarball_como_github(tmp_path, programa / "backend")
    tmp = tmp_path / "t"
    tmp.mkdir()
    backend = updates.preparar(archivo, tmp)
    assert backend.name == "backend"
    assert (backend / "core" / "instance.py").is_file()


def test_preparar_rechaza_rutas_fuera_y_archivos_sin_backend(tmp_path):
    malo = tmp_path / "malo.tar.gz"
    with tarfile.open(malo, "w:gz") as t:
        info = tarfile.TarInfo("../fuera.py")
        info.size = 0
        t.addfile(info, io.BytesIO(b""))
    tmp = tmp_path / "t1"
    tmp.mkdir()
    with pytest.raises(updates.UpdateError, match="ruta inválida"):
        updates.preparar(malo, tmp)

    vacio = tmp_path / "vacio.tar.gz"
    with tarfile.open(vacio, "w:gz") as t:
        info = tarfile.TarInfo("algo/README.md")
        info.size = 0
        t.addfile(info, io.BytesIO(b""))
    tmp = tmp_path / "t2"
    tmp.mkdir()
    with pytest.raises(updates.UpdateError, match="no trae un backend"):
        updates.preparar(vacio, tmp)


# ── validar ─────────────────────────────────────────────────────────────


def test_validar_arranca_el_nucleo_nuevo_en_otro_proceso(tmp_path):
    programa = _programa_falso(tmp_path)
    veredicto = updates.validar(programa / "backend")
    assert veredicto["ok"], veredicto["errors"]
    assert any(p["name"] == "core" for p in veredicto["catalog"]["plugins"])


def test_validar_detecta_un_nucleo_roto(tmp_path):
    programa = _programa_falso(tmp_path)
    (programa / "backend" / "core" / "__init__.py").write_text("raise RuntimeError('nucleo roto')\n", encoding="utf-8")
    veredicto = updates.validar(programa / "backend")
    assert not veredicto["ok"]
    assert any("nucleo roto" in e for e in veredicto["errors"])


def test_requisitos_nuevos_avisa_lo_que_el_actual_no_pide(tmp_path):
    programa = _programa_falso(tmp_path)
    nuevo = tmp_path / "nuevo"
    shutil.copytree(programa / "backend", nuevo)
    with (nuevo / "requirements.txt").open("a", encoding="utf-8") as f:
        f.write("\nplaywright==1.50.0  # navegador\n")
    assert updates.requisitos_nuevos(programa / "backend", nuevo) == ["playwright==1.50.0"]
    assert updates.requisitos_nuevos(programa / "backend", programa / "backend") == []


# ── aplicar y revertir ──────────────────────────────────────────────────


def test_aplicar_deja_el_anterior_al_lado_y_anota_el_tag(tmp_path):
    programa = _programa_falso(tmp_path)
    nuevo = tmp_path / "nuevo"
    shutil.copytree(programa / "backend", nuevo)
    (nuevo / "NUEVO.txt").write_text("soy el nuevo", encoding="utf-8")

    marca = updates.aplicar(programa, nuevo, tag="v0.3.0", fuente="github")
    assert marca["tag"] == "v0.3.0" and marca["previous_tag"] is None
    assert (programa / "backend" / "NUEVO.txt").is_file()
    assert (programa / updates.ANTERIOR / "core").is_dir()
    assert not (programa / updates.ANTERIOR / "NUEVO.txt").exists()

    estado = updates.instalada(programa)
    assert estado["tag"] == "v0.3.0" and estado["has_previous"]

    # Revertir intercambia; el que estaba queda como anterior, con su marca.
    estado = updates.revertir(programa)
    assert estado["tag"] is None
    assert (programa / updates.ANTERIOR / "NUEVO.txt").is_file()
    assert estado["previous"]["tag"] == "v0.3.0"

    updates.descartar_anterior(programa)
    assert not (programa / updates.ANTERIOR).exists()
    with pytest.raises(updates.UpdateError, match="No hay un núcleo anterior"):
        updates.revertir(programa)


def test_aplicar_dos_veces_pisa_el_anterior_mas_viejo(tmp_path):
    programa = _programa_falso(tmp_path)
    nuevo = tmp_path / "nuevo"
    shutil.copytree(programa / "backend", nuevo)
    updates.aplicar(programa, nuevo, tag="v1", fuente="archivo")
    updates.aplicar(programa, nuevo, tag="v2", fuente="archivo")
    assert updates.instalada(programa)["tag"] == "v2"
    assert updates.instalada(programa)["previous"]["tag"] == "v1"


def test_aplicar_deja_la_version_que_el_tarball_de_fuente_no_trae(tmp_path):
    """
    El núcleo lee `backend/VERSION` cuando no hay `.dist-info` (core#5), pero el
    tarball de fuente del tag no lo incluye — lo genera el release en el wheel.
    Aplicar conoce el tag, así que lo escribe; y respeta uno que ya venga.
    """
    programa = _programa_falso(tmp_path)
    nuevo = tmp_path / "nuevo"
    shutil.copytree(programa / "backend", nuevo)
    (nuevo / "VERSION").unlink(missing_ok=True)

    updates.aplicar(programa, nuevo, tag="v0.3.0-beta.4", fuente="github:v0.3.0-beta.4")
    assert (programa / "backend" / "VERSION").read_text(encoding="utf-8").strip() == "0.3.0-beta.4"

    (nuevo / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    updates.aplicar(programa, nuevo, tag="v0.4.0", fuente="archivo")
    assert (programa / "backend" / "VERSION").read_text(encoding="utf-8").strip() == "9.9.9"


# ── la web app como componente ──────────────────────────────────────────


def _webapp_falsa(tmp_path) -> pathlib.Path:
    """Una carpeta de programa con una copia de la webapp/ real, sin tests ni caches."""
    programa = tmp_path / "programa"
    programa.mkdir(exist_ok=True)
    shutil.copytree(REPO / "webapp", programa / "webapp",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "vendor"))
    return programa


def test_preparar_encuentra_la_webapp_en_el_tarball_del_repo(tmp_path):
    programa = _webapp_falsa(tmp_path)
    archivo = tmp_path / "bot-vX.tar.gz"
    with tarfile.open(archivo, "w:gz") as t:
        t.add(programa / "webapp", arcname="Org-Bot-abc123/webapp")
        t.add(REPO / "core-release.json", arcname="Org-Bot-abc123/core-release.json")
    tmp = tmp_path / "t"
    tmp.mkdir()
    carpeta = updates.preparar(archivo, tmp, updates.WEBAPP)
    assert carpeta.name == "webapp" and (carpeta / "server.py").is_file()
    # El mismo archivo no sirve como núcleo: no trae backend/.
    tmp2 = tmp_path / "t2"
    tmp2.mkdir()
    with pytest.raises(updates.UpdateError, match="no trae un backend"):
        updates.preparar(archivo, tmp2, updates.CORE)


def test_validar_la_webapp_compila_y_exige_lo_que_usa_el_lanzador(tmp_path):
    programa = _webapp_falsa(tmp_path)
    assert updates.validar(programa / "webapp", updates.WEBAPP)["ok"]

    (programa / "webapp" / "bandeja.py").write_text("def roto(:\n", encoding="utf-8")
    veredicto = updates.validar(programa / "webapp", updates.WEBAPP)
    assert not veredicto["ok"] and any("no compila" in e for e in veredicto["errors"])

    (programa / "webapp" / "server.py").unlink()
    veredicto = updates.validar(programa / "webapp", updates.WEBAPP)
    assert any("server.py" in e for e in veredicto["errors"])


def test_aplicar_y_revertir_la_webapp_no_tocan_el_nucleo(tmp_path):
    programa = _programa_falso(tmp_path)
    _webapp_falsa(tmp_path)
    nuevo = tmp_path / "nuevo"
    shutil.copytree(programa / "webapp", nuevo)
    (nuevo / "NUEVO.txt").write_text("web app nueva", encoding="utf-8")

    marca = updates.aplicar(programa, nuevo, tag="0.4.1", fuente="github", comp=updates.WEBAPP)
    assert marca["tag"] == "0.4.1"
    assert (programa / "webapp" / "NUEVO.txt").is_file()
    assert (programa / "webapp.anterior" / "server.py").is_file()
    assert (programa / "webapp-release.json").is_file()
    # No aparece un VERSION (eso es del núcleo) y backend/ sigue intacto, sin anterior.
    assert not (programa / "webapp" / "VERSION").exists()
    assert not (programa / "backend.anterior").exists()
    assert updates.instalada(programa, updates.CORE)["tag"] is None
    assert updates.instalada(programa, updates.WEBAPP)["tag"] == "0.4.1"

    estado = updates.revertir(programa, updates.WEBAPP)
    assert estado["component"] == "webapp" and estado["previous"]["tag"] == "0.4.1"
    assert not (programa / "webapp" / "NUEVO.txt").exists()


def test_descargar_usa_el_repo_y_el_token_que_le_dan(tmp_path):
    pedidos = []

    def abrir(url, destino=None, token=None):
        pedidos.append((url, token))
        destino.write_bytes(b"")
        return destino

    updates.descargar("v1", tmp_path, abrir, repo="Org/Bot", token="tkn", comp=updates.WEBAPP)
    assert pedidos == [("https://api.github.com/repos/Org/Bot/tarball/v1", "tkn")]
    assert (tmp_path / "webapp-v1.tar.gz").is_file()


def test_un_403_sin_token_sugiere_la_variable():
    def abrir(url, destino=None, token=None):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

    with pytest.raises(updates.UpdateError, match="GITHUB_TOKEN"):
        updates.disponibles(abrir=abrir, repo="Org/Privado")


# ── configuración por instalación ───────────────────────────────────────


class _StoreFalso:
    def __init__(self):
        self.datos = {}

    def read(self, clave):
        from backend.core.resources import ResourceError

        if clave not in self.datos:
            raise ResourceError(clave)
        return self.datos[clave]

    def write(self, clave, item):
        self.datos[clave] = item


class _InstanciaFalsa:
    def __init__(self, variables=None):
        self.store = _StoreFalso()
        self.variables = variables or {}

    def resource_store(self, plugin, resource):
        assert plugin == "webapp" and resource is updates.RESOURCE
        return self.store

    def env_vars(self):
        return self.variables


def test_los_repos_se_guardan_por_instalacion_y_vacio_vuelve_al_default():
    inst = _InstanciaFalsa()
    assert updates.configuracion(inst) == {"core": updates.CORE.repo_por_defecto, "webapp": updates.WEBAPP.repo_por_defecto}

    repos = updates.guardar_configuracion(inst, {"core": "Org/core-fork", "webapp": ""})
    assert repos == {"core": "Org/core-fork", "webapp": updates.WEBAPP.repo_por_defecto}
    with pytest.raises(updates.UpdateError, match="Repo inválido"):
        updates.guardar_configuracion(inst, {"webapp": "sin-barra"})
    with pytest.raises(updates.UpdateError, match="Componente desconocido"):
        updates.guardar_configuracion(inst, {"otro": "a/b"})


def test_el_token_sale_de_cualquiera_de_las_dos_variables():
    assert updates.token_de(_InstanciaFalsa()) is None
    assert updates.token_de(_InstanciaFalsa({"PLUGINS_GITHUB_TOKEN": "p"})) == "p"
    assert updates.token_de(_InstanciaFalsa({"GITHUB_TOKEN": "g", "PLUGINS_GITHUB_TOKEN": "p"})) == "g"

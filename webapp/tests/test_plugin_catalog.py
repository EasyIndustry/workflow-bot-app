"""
Tests de `webapp/plugin_catalog.py`: el catálogo de plugins en GitHub.

Sin red: GitHub se inyecta como un `abrir(url, destino, token)` guionado, y
la "rama" es un tarball armado con la forma exacta que da GitHub (una carpeta
`owner-repo-sha/` en la raíz). Lo que se prueba es el contrato con la
pantalla —qué se lista, qué se puede instalar, cómo se dice que falta el
token— y que la carpeta que sale está lista para `plugin_install`.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import tarfile
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import plugin_catalog as cat  # noqa: E402

REPO = "EasyIndustry/workflow-bot-plugins"
ENTRADA_ARCHIVOS = {
    "name": "archivos", "description": "Mover, copiar, eliminar, renombrar y buscar archivos.",
    "source": "workflow-bot-plugin-archivos", "path": "archivos", "ports": ["fs"],
    "maintainer": "EasyIndustry", "repo_url": f"https://github.com/{REPO}",
    "compatible_core": ">=0.3.0", "license": "MIT",
}
ENTRADA_INDICE = {**ENTRADA_ARCHIVOS, "name": "conexiones", "source": "workflow-bot-plugin-conexiones"}
del ENTRADA_INDICE["path"]


def _github(tarball: pathlib.Path | None = None, ramas=("cured", "draft"), entradas=(ENTRADA_ARCHIVOS, ENTRADA_INDICE)):
    """Un GitHub guionado: contents/, raw de cada json, branches y el tarball."""
    llamadas = []

    def abrir(url, destino=None, token=None):
        llamadas.append((url, token))
        if url.endswith("/branches?per_page=50"):
            return json.dumps([{"name": r} for r in ramas]).encode()
        if "/contents/plugins?ref=" in url:
            return json.dumps([
                {"name": f"{e['name']}.json", "download_url": f"https://raw/{e['name']}.json"} for e in entradas
            ] + [{"name": "README.md", "download_url": "https://raw/README.md"}]).encode()
        if url.startswith("https://raw/"):
            nombre = url.rsplit("/", 1)[-1][:-5]
            return json.dumps(next(e for e in entradas if e["name"] == nombre)).encode()
        if "/tarball/" in url:
            assert destino is not None and tarball is not None
            destino.write_bytes(tarball.read_bytes())
            return destino
        raise AssertionError(f"url no guionada: {url}")

    abrir.llamadas = llamadas
    return abrir


def _tarball(tmp_path, *, sha="abc1234") -> pathlib.Path:
    """La rama como la da GitHub: `owner-repo-sha/` con `archivos/__init__.py` y `archivos/plugin.py` adentro."""
    raiz = f"EasyIndustry-workflow-bot-plugins-{sha}"
    archivo = tmp_path / "rama.tar.gz"

    def agregar(t, ruta, contenido):
        info = tarfile.TarInfo(f"{raiz}/{ruta}")
        datos = contenido.encode()
        info.size = len(datos)
        t.addfile(info, io.BytesIO(datos))

    with tarfile.open(archivo, "w:gz") as t:
        agregar(t, "plugins/archivos.json", json.dumps(ENTRADA_ARCHIVOS))
        agregar(t, "archivos/__init__.py", "from .plugin import PLUGIN\n")
        agregar(t, "archivos/plugin.py", "PLUGIN = None\n")
        agregar(t, "roto/plugin.py", "PLUGIN = None\n")  # carpeta sin __init__.py
    return archivo


# ── Listar ──────────────────────────────────────────────────────────────


def test_entradas_lee_los_json_de_plugins_y_dice_cuales_tienen_codigo():
    abrir = _github()
    lista = cat.entradas(REPO, "cured", abrir, token="tok")

    assert [e["name"] for e in lista] == ["archivos", "conexiones"]
    archivos, conexiones = lista
    assert archivos["installable"] is True and archivos["path"] == "archivos" and archivos["module"] == "archivos"
    assert conexiones["installable"] is False  # entrada del índice público: sin path, sin nada que instalar
    # El token viaja en todos los pedidos, y el README de plugins/ se ignora.
    assert all(t == "tok" for _u, t in abrir.llamadas)
    assert not any(u.endswith("README.md") for u, _t in abrir.llamadas)


def test_ramas_pone_cured_primero():
    assert cat.ramas(REPO, _github(ramas=("draft", "cured", "otra"))) == ["cured", "draft", "otra"]


def test_un_403_sin_token_explica_que_variable_cargar():
    def abrir(url, destino=None, token=None):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

    with pytest.raises(cat.CatalogError) as exc:
        cat.entradas(REPO, "cured", abrir)
    assert cat.VARIABLE_TOKEN in str(exc.value)


def test_nombre_con_guion_se_instala_como_modulo_con_guion_bajo():
    entrada = {**ENTRADA_ARCHIVOS, "name": "web-tools", "path": "web_tools"}
    [e] = cat.entradas(REPO, "cured", _github(entradas=(entrada,)))
    assert (e["name"], e["module"]) == ("web-tools", "web_tools")


# ── Descargar la carpeta a instalar ─────────────────────────────────────


def test_descargar_carpeta_devuelve_el_paquete_de_la_rama_y_el_commit(tmp_path):
    tarball = _tarball(tmp_path, sha="f00dbabe")
    tmp = tmp_path / "trabajo"
    tmp.mkdir()
    [entrada, _] = cat.entradas(REPO, "cured", _github(tarball))

    carpeta, commit = cat.descargar_carpeta(entrada, repo=REPO, branch="cured", tmp=tmp, abrir=_github(tarball))

    assert carpeta.name == "archivos" and (carpeta / "__init__.py").is_file()
    assert commit == "f00dbabe"


def test_una_entrada_sin_path_o_una_carpeta_sin_init_no_se_instalan(tmp_path):
    tarball = _tarball(tmp_path)
    tmp = tmp_path / "t"
    tmp.mkdir()
    sin_path = {**ENTRADA_INDICE, "module": "conexiones"}
    with pytest.raises(cat.CatalogError, match="path"):
        cat.descargar_carpeta(sin_path, repo=REPO, branch="cured", tmp=tmp, abrir=_github(tarball))

    rota = {**ENTRADA_ARCHIVOS, "module": "roto", "path": "roto"}
    with pytest.raises(cat.CatalogError, match="__init__"):
        cat.descargar_carpeta(rota, repo=REPO, branch="cured", tmp=tmp, abrir=_github(tarball))


def test_la_ruta_declarada_no_puede_salirse_del_tarball(tmp_path):
    tarball = _tarball(tmp_path)
    tmp = tmp_path / "t"
    tmp.mkdir()
    maliciosa = {**ENTRADA_ARCHIVOS, "module": "x", "path": "../.."}
    with pytest.raises(cat.CatalogError):
        cat.descargar_carpeta(maliciosa, repo=REPO, branch="cured", tmp=tmp, abrir=_github(tarball))


# ── Procedencia y configuración ─────────────────────────────────────────


def test_procedencia_se_anota_en_la_carpeta_instalada_y_se_vuelve_a_leer(tmp_path):
    plugins_dir = tmp_path / "plugins"
    (plugins_dir / "archivos").mkdir(parents=True)
    entrada = {"name": "archivos", "module": "archivos"}
    datos = cat.datos_de_procedencia(entrada, repo=REPO, branch="draft", commit="abc", version="0.2.0")

    cat.anotar_procedencia(plugins_dir / "archivos", datos)
    leido = cat.procedencia_de(plugins_dir, "archivos")

    assert (leido["branch"], leido["commit"], leido["version"], leido["source"]) == ("draft", "abc", "0.2.0", "catalogo")
    # El archivo empieza con punto: el núcleo no lo confunde con un plugin.
    assert (plugins_dir / "archivos" / cat.PROCEDENCIA).is_file()
    assert cat.procedencia_de(plugins_dir, "otro") is None
    assert cat.procedencia_de(None, "archivos") is None


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
    def __init__(self):
        self.store = _StoreFalso()

    def resource_store(self, plugin, resource):
        assert plugin == "webapp" and resource is cat.RESOURCE
        return self.store

    def env_vars(self):
        return {}


def test_configuracion_tiene_defaults_y_valida_lo_que_se_guarda():
    inst = _InstanciaFalsa()
    assert cat.configuracion(inst) == {"repo": cat.REPO_POR_DEFECTO, "branch": "cured"}

    assert cat.guardar_configuracion(inst, repo="Org/plugins", branch="draft") == {"repo": "Org/plugins", "branch": "draft"}
    with pytest.raises(cat.CatalogError):
        cat.guardar_configuracion(inst, repo="sin-barra", branch="cured")
    with pytest.raises(cat.CatalogError):
        cat.guardar_configuracion(inst, repo="Org/plugins", branch="")


# ── ¿La que tengo es la última? ────────────────────────────────────────


def _abrir_falso(respuestas):
    """Un `abrir` que devuelve lo que se le diga según la URL."""
    def abrir(url, destino=None, token=None):
        for trozo, cuerpo in respuestas.items():
            if trozo in url:
                return json.dumps(cuerpo).encode("utf-8")
        raise AssertionError(f"URL sin respuesta en el test: {url}")
    return abrir


# La forma real de `GET /compare/{base}...{head}`: no hay un "head", hay
# `base_commit` y `commits` del más viejo al más nuevo. Escribirla de memoria
# fue el error de la primera versión, y el test la daba por buena.
COMPARACION = {
    "status": "ahead",
    "ahead_by": 3,
    "base_commit": {"sha": "4b9f7ab0000", "commit": {"author": {"date": "2026-09-16T10:00:00Z"}}},
    "commits": [
        {"sha": "aaa1111", "commit": {"author": {"date": "2026-09-17T09:00:00Z"}}},
        {"sha": "e7ef3231234", "commit": {"author": {"date": "2026-09-17T22:00:00Z"}}},
    ],
    "files": [{"filename": "convertidor/plugin.py"}, {"filename": "README.md"}],
}

IDENTICOS = {"status": "identical", "ahead_by": 0, "commits": [],
             "base_commit": {"sha": "4b9f7ab0000", "commit": {"author": {"date": "2026-09-16T10:00:00Z"}}},
             "files": []}


def test_cambios_desde_dice_que_se_tocó_y_dónde_quedó_la_rama():
    r = cat.cambios_desde("o/r", "4b9f7ab", "draft", _abrir_falso({"/compare/": COMPARACION}))

    assert r["head"] == "e7ef323"
    assert r["adelante"] == 3
    assert r["rutas"] == ["convertidor/plugin.py", "README.md"]


def test_sin_nada_en_el_medio_la_cabeza_es_la_base():
    """`status: identical`: la rama está donde se instaló, no hay versión nueva."""
    r = cat.cambios_desde("o/r", "4b9f7ab", "draft", _abrir_falso({"/compare/": IDENTICOS}))

    assert (r["head"], r["adelante"], r["rutas"]) == ("4b9f7ab", 0, [])
    assert cat._toca(r["rutas"], "convertidor") is False


def test_si_github_no_contesta_no_se_dice_nada():
    """Es información de más en una pantalla que ya funciona: no puede romperla."""
    def abrir(url, destino=None, token=None):
        raise OSError("sin red")

    assert cat.cambios_desde("o/r", "4b9f7ab", "draft", abrir) is None
    assert cat.cambios_desde("o/r", "", "draft", abrir) is None


def test_toca_mira_la_carpeta_del_plugin_y_no_el_prefijo():
    rutas = ["convertidor/plugin.py", "README.md", "convertidor-viejo/x.py"]

    assert cat._toca(rutas, "convertidor") is True
    assert cat._toca(rutas, "archivos") is False
    # "convertidor-viejo" empieza igual que "convertidor" y no es lo mismo.
    assert cat._toca(["convertidor-viejo/x.py"], "convertidor") is False


def _listar_con(monkeypatch, tmp_path, procedencia, entradas):
    monkeypatch.setattr(cat, "cambios_desde", lambda *a, **k: {
        "head": "e7ef323", "fecha": "2026-09-17T22:00:00Z", "adelante": 3,
        "rutas": [f["filename"] for f in COMPARACION["files"]],
    })
    monkeypatch.setattr(cat, "entradas", lambda *a, **k: entradas)
    monkeypatch.setattr(cat, "ramas", lambda *a, **k: ["draft"])
    monkeypatch.setattr(cat, "procedencia_de", lambda _d, modulo: dict(procedencia) or None)
    monkeypatch.setattr(cat, "configuracion", lambda _i: {"repo": "o/r", "branch": "draft"})
    monkeypatch.setattr(cat, "token_de", lambda _i: None)
    import webapp.plugin_install as pi
    monkeypatch.setattr(pi, "instalados", lambda _d: [{"name": e["module"]} for e in entradas])

    class Inst:
        boot = type("B", (), {"plugins_dir": tmp_path})()
    return {e["name"]: e for e in cat.listar(Inst())["entries"]}


def test_solo_marca_el_plugin_que_cambio(tmp_path, monkeypatch):
    """
    El falso positivo que tenía la primera versión: la procedencia guarda el
    commit de la **rama** al instalar, no el de la carpeta del plugin, así que
    comparar uno contra otro marcaba como desactualizado hasta lo recién
    instalado. Comparando lo que cambió entre los dos commits, sólo se marca
    el que de verdad se tocó.
    """
    entradas = [
        {"name": "convertidor", "module": "convertidor", "path": "convertidor", "installable": True},
        {"name": "archivos", "module": "archivos", "path": "archivos", "installable": True},
    ]
    r = _listar_con(monkeypatch, tmp_path, {"commit": "4b9f7ab", "branch": "draft"}, entradas)

    assert r["convertidor"]["hay_nueva"] is True
    assert r["archivos"]["hay_nueva"] is False
    assert r["convertidor"]["upstream"]["head"] == "e7ef323"


@pytest.mark.parametrize("procedencia", [
    {"commit": "4b9f7ab", "branch": "cured"},   # otra rama: no comparable
    {},                                          # instalado a mano
])
def test_sin_con_que_comparar_no_se_inventa(tmp_path, monkeypatch, procedencia):
    entradas = [{"name": "convertidor", "module": "convertidor", "path": "convertidor", "installable": True}]
    r = _listar_con(monkeypatch, tmp_path, procedencia, entradas)

    assert r["convertidor"]["hay_nueva"] is False
    assert r["convertidor"]["upstream"] is None

"""
Plugins en línea: un catálogo curado en un repo de GitHub, del que la app
lista e instala.

El programa se instala **sin plugins** (`installer/` deja `plugins_dir` vacía)
y lo que una instalación necesita se trae de acá, uno por uno, desde la
pestaña Plug ins. El repo tiene la forma del índice público
`EasyIndustry/workflow-bot-plugins`: un `plugins/<name>.json` por plugin,
validado contra `schema/plugin.schema.json`. Además de apuntar a un paquete, una entrada puede **alojar el código**: cada entrada declara
`path`, la carpeta del repo (un paquete con `__init__.py`) que es lo que se
instala. Un índice que apunta a paquetes de pip no sirve en una máquina de
planta sin PyPI; un tarball de GitHub, sí.

Ramas: `cured` es lo curado y `draft` lo que todavía no terminó. La rama se
elige por instalación y queda guardada; instalar desde `draft` se avisa como
tal en la pantalla. Se lista con la API de contenidos (dos requests chicos)
y se instala bajando el tarball de la rama una sola vez. Un repo privado
necesita un token: se guarda en Config → Variables como `PLUGINS_GITHUB_TOKEN`
(secreto), nunca en un setting en claro.

Instalar pasa por `webapp/plugin_install.py`, el mismo camino que un archivo
subido: validación en otro proceso, copia, recarga de la instancia. Lo que
se agrega es la **procedencia**: un `.procedencia.json` adentro de la carpeta
instalada (el mismo nombre que usa `installer/source/plugins.py`; el núcleo
saltea lo que empieza con punto) con repo, rama y commit — para poder decir
"esto vino de draft" y ofrecer volver a instalar cuando el repo cambió.
"""

from __future__ import annotations

import json
import re
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend.core.contract import Field, ParamType, Resource
from backend.core.resources import ResourceError

REPO_POR_DEFECTO = "EasyIndustry/workflow-bot-plugins"
RAMA_POR_DEFECTO = "cured"
VARIABLE_TOKEN = "PLUGINS_GITHUB_TOKEN"
PROCEDENCIA = ".procedencia.json"
TIMEOUT_RED = 15
_MAX_BYTES = 80 * 1024 * 1024
_REPO_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAMA_VALIDA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")

RESOURCE = Resource(
    name="catalogo_plugins",
    label="Catálogo de plugins",
    item_label="Ajuste",
    key_field="clave",
    doc="De qué repo y rama se listan e instalan los plugins en línea.",
    fields=(Field("value", ParamType.STR, label="Valor"),),
)


class CatalogError(Exception):
    def __init__(self, mensaje: str, detalle: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.detalle = detalle or []


# ── Configuración (repo y rama), por instalación ─────────────────────────


def _store(instance):
    return instance.resource_store("webapp", RESOURCE)


def configuracion(instance) -> dict:
    valores = {}
    for clave in ("repo", "branch"):
        try:
            valores[clave] = (_store(instance).read(clave).get("value") or "").strip()
        except ResourceError:
            valores[clave] = ""
    return {
        "repo": valores["repo"] or REPO_POR_DEFECTO,
        "branch": valores["branch"] or RAMA_POR_DEFECTO,
    }


def guardar_configuracion(instance, *, repo: str, branch: str) -> dict:
    repo, branch = (repo or "").strip(), (branch or "").strip()
    if not _REPO_VALIDO.match(repo):
        raise CatalogError(f"Repo inválido: {repo!r}. Se espera owner/nombre.")
    if not _RAMA_VALIDA.match(branch):
        raise CatalogError(f"Rama inválida: {branch!r}.")
    store = _store(instance)
    store.write("repo", {"value": repo})
    store.write("branch", {"value": branch})
    return configuracion(instance)


def token_de(instance) -> str | None:
    """El token de GitHub, si se cargó como variable. Un repo público no lo necesita."""
    try:
        return (instance.env_vars().get(VARIABLE_TOKEN) or "").strip() or None
    except Exception:  # noqa: BLE001 — sin token se sigue como repo público
        return None


# ── GitHub ──────────────────────────────────────────────────────────────


def _abrir_url(url: str, destino: Path | None = None, token: str | None = None) -> bytes | Path:
    cabeceras = {"Accept": "application/vnd.github+json", "User-Agent": "bot-webapp-plugins"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(url, headers=cabeceras)
    with urllib.request.urlopen(peticion, timeout=TIMEOUT_RED) as r:  # noqa: S310 — https a GitHub
        if destino is None:
            return r.read()
        total = 0
        with destino.open("wb") as f:
            while True:
                trozo = r.read(1024 * 256)
                if not trozo:
                    break
                total += len(trozo)
                if total > _MAX_BYTES:
                    raise CatalogError("El tarball del catálogo pesa más de 80 MB: no es un repo de plugins.")
                f.write(trozo)
        return destino


def _pedir_json(abrir, url: str, token: str | None, que: str):
    try:
        crudo = abrir(url, None, token)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise CatalogError(
                f"GitHub respondió {exc.code} al {que}. Si el repo es privado, hace falta la variable "
                f"{VARIABLE_TOKEN} (Config → Variables, secreta) con un token que lo pueda leer.",
            ) from None
        raise CatalogError(f"GitHub respondió {exc.code} al {que}.") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CatalogError("No se pudo llegar a GitHub para leer el catálogo de plugins.", [str(exc)]) from None
    try:
        return json.loads(crudo)
    except ValueError:
        raise CatalogError(f"GitHub devolvió algo que no es JSON al {que}.") from None


def ramas(repo: str, abrir=None, token: str | None = None) -> list[str]:
    abrir = abrir or _abrir_url
    datos = _pedir_json(abrir, f"https://api.github.com/repos/{repo}/branches?per_page=50", token, "listar las ramas")
    if not isinstance(datos, list):
        return []
    nombres = [b.get("name") for b in datos if isinstance(b, dict) and b.get("name")]
    # Lo curado primero, después lo demás por nombre: es el orden en que se eligen.
    return sorted(nombres, key=lambda n: (n != RAMA_POR_DEFECTO, n))


def entradas(repo: str, branch: str, abrir=None, token: str | None = None) -> list[dict]:
    """Los `plugins/<name>.json` de la rama, leídos y saneados."""
    abrir = abrir or _abrir_url
    listado = _pedir_json(
        abrir, f"https://api.github.com/repos/{repo}/contents/plugins?ref={branch}", token,
        f'leer plugins/ de la rama "{branch}"',
    )
    if not isinstance(listado, list):
        raise CatalogError(f'La rama "{branch}" no tiene una carpeta plugins/.')

    salida = []
    for archivo in listado:
        if not isinstance(archivo, dict) or not str(archivo.get("name", "")).endswith(".json"):
            continue
        url = archivo.get("download_url")
        if not url:
            continue
        datos = _pedir_json(abrir, url, token, f"leer {archivo['name']}")
        if not isinstance(datos, dict):
            continue
        nombre = str(datos.get("name") or Path(archivo["name"]).stem)
        salida.append({
            "name": nombre,
            "module": nombre.replace("-", "_"),
            "description": str(datos.get("description") or ""),
            "ports": [str(p) for p in (datos.get("ports") or [])],
            "path": str(datos.get("path") or "").strip("/"),
            "source": str(datos.get("source") or ""),
            "repo_url": str(datos.get("repo_url") or ""),
            "compatible_core": str(datos.get("compatible_core") or ""),
            "maintainer": str(datos.get("maintainer") or ""),
            "license": str(datos.get("license") or ""),
            # Sin `path` es una entrada del índice público (un paquete de pip):
            # se muestra, pero no hay nada que esta app pueda instalar.
            "installable": bool(datos.get("path")),
        })
    return sorted(salida, key=lambda e: e["name"])


# ── Lo instalado, con su procedencia ────────────────────────────────────


def procedencia_de(plugins_dir: Path | None, modulo: str) -> dict | None:
    if plugins_dir is None:
        return None
    archivo = Path(plugins_dir) / modulo / PROCEDENCIA
    if not archivo.is_file():
        return None
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def anotar_procedencia(carpeta: Path, datos: dict) -> None:
    """Sólo para un plugin instalado como carpeta: un `.py` suelto no tiene dónde anotarlo."""
    if carpeta.is_dir():
        (carpeta / PROCEDENCIA).write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def listar(instance, abrir=None) -> dict:
    """Lo que dibuja la pantalla: config, ramas, entradas y qué está instalado de cada una."""
    from webapp import plugin_install

    cfg = configuracion(instance)
    token = token_de(instance)
    plugins_dir = instance.boot.plugins_dir
    instalados = {p["name"]: p for p in plugin_install.instalados(plugins_dir)}
    salida = {**cfg, "branches": [cfg["branch"]], "entries": [], "error": None, "token": bool(token)}
    try:
        salida["branches"] = ramas(cfg["repo"], abrir, token) or [cfg["branch"]]
        salida["entries"] = entradas(cfg["repo"], cfg["branch"], abrir, token)
    except CatalogError as exc:
        salida["error"] = str(exc)
        salida["error_detail"] = exc.detalle
    for entrada in salida["entries"]:
        instalado = instalados.get(entrada["module"])
        entrada["installed"] = instalado is not None
        entrada["provenance"] = procedencia_de(plugins_dir, entrada["module"]) if instalado else None
    return salida


# ── Instalar ────────────────────────────────────────────────────────────


def descargar_carpeta(entrada: dict, *, repo: str, branch: str, tmp: Path, abrir=None, token: str | None = None) -> tuple[Path, str]:
    """
    Baja el tarball de la rama y devuelve la carpeta del plugin lista para
    `plugin_install.instalar`, más el commit del que salió (el sufijo del
    directorio raíz del tarball, que GitHub arma como `owner-repo-sha`).
    """
    abrir = abrir or _abrir_url
    if not entrada.get("path"):
        raise CatalogError(f'"{entrada.get("name")}" no declara `path`: es una entrada de índice, no hay código que instalar.')
    if not _RAMA_VALIDA.match(branch) or not _REPO_VALIDO.match(repo):
        raise CatalogError("Repo o rama inválidos.")

    archivo = tmp / "catalogo.tar.gz"
    try:
        abrir(f"https://api.github.com/repos/{repo}/tarball/{branch}", archivo, token)
    except urllib.error.HTTPError as exc:
        raise CatalogError(f'GitHub respondió {exc.code} al bajar la rama "{branch}" de {repo}.') from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CatalogError("No se pudo bajar el catálogo: sin conexión a GitHub.", [str(exc)]) from None

    extraido = tmp / "repo"
    extraido.mkdir()
    try:
        with tarfile.open(archivo) as t:
            for m in t.getmembers():
                partes = Path(m.name).parts
                if m.name.startswith(("/", "\\")) or ".." in partes or m.issym() or m.islnk():
                    raise CatalogError(f"El tarball trae una ruta inválida: {m.name}")
            if hasattr(tarfile, "data_filter"):
                t.extractall(extraido, filter="data")
            else:
                t.extractall(extraido)  # noqa: S202 — rutas ya revisadas
    except tarfile.TarError as exc:
        raise CatalogError(f"El tarball del catálogo no se pudo abrir: {exc}") from None

    raices = [p for p in extraido.iterdir() if p.is_dir()]
    if len(raices) != 1:
        raise CatalogError("El tarball no tiene la forma de GitHub (una carpeta owner-repo-sha en la raíz).")
    raiz = raices[0]
    commit = raiz.name.rsplit("-", 1)[-1]

    carpeta = (raiz / entrada["path"]).resolve()
    if raiz.resolve() not in carpeta.parents or not carpeta.is_dir():
        raise CatalogError(f'La rama "{branch}" no tiene la carpeta {entrada["path"]} que declara {entrada["name"]}.')
    if not (carpeta / "__init__.py").is_file():
        raise CatalogError(f"{entrada['path']} no es un paquete: le falta el __init__.py que exporte PLUGIN.")
    return carpeta, commit


def datos_de_procedencia(entrada: dict, *, repo: str, branch: str, commit: str, version: str) -> dict:
    return {
        "name": entrada["module"],
        "catalog_name": entrada["name"],
        "version": version,
        "source": "catalogo",
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "installed_at": time.time(),
    }


__all__ = [
    "PROCEDENCIA", "RAMA_POR_DEFECTO", "REPO_POR_DEFECTO", "RESOURCE", "VARIABLE_TOKEN",
    "CatalogError", "anotar_procedencia", "configuracion", "datos_de_procedencia",
    "descargar_carpeta", "entradas", "guardar_configuracion", "listar", "procedencia_de", "ramas", "token_de",
]

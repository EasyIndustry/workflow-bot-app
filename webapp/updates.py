"""
Actualizar el núcleo (`backend/`) y la web app (`webapp/`) desde releases de
GitHub, sin git, desde la propia app.

Dos componentes, un mismo movimiento
------------------------------------

`backend/` se trae de un release de `workflow-bot-core` y se reemplaza entero;
`webapp/` se trae de un release del repo de este programa y se reemplaza
entero. Los dos son "una carpeta del programa que se cambia por la del tag,
con la anterior al lado": por eso acá hay un solo juego de funciones y un
`Componente` que dice carpeta, marca, repo por defecto y cómo validar.

1. **La fuente es un release de GitHub**, por tag. Se baja el tarball del tag;
   si el release trae un asset con el nombre del componente (`webapp-*.zip`),
   se prefiere ése, que pesa menos. Como las máquinas de producción suelen no
   tener internet, la misma rutina acepta el archivo bajado en otra máquina y
   subido desde el navegador. Un repo privado necesita un token: variable
   `GITHUB_TOKEN` en Config → Variables (o `PLUGINS_GITHUB_TOKEN`, la del
   catálogo de plugins, que suele ser el mismo).

2. **El repo de cada componente se elige por instalación** y queda en la base
   (resource `webapp/actualizaciones`), como el repo del catálogo de plugins.
   Los de acá son sólo el valor por defecto.

3. **Se valida antes de tocar nada.** El núcleo nuevo se arranca en otro
   proceso (`python -m backend.core plugins --json` en un temporal): si no
   importa o no arma el catálogo, no se aplica. La web app nueva se compila
   entera (`compileall`) y se le exige lo que el lanzador necesita; no se
   arranca, porque arrancarla es abrir la instalación real. En los dos casos se
   compara el `requirements.txt`: una dependencia nueva no se instala sola —una
   máquina sin PyPI no podría— pero se avisa antes.

4. **El anterior queda al lado.** Aplicar es mover `<carpeta>/` a
   `<carpeta>.anterior/` y copiar la nueva. Si después del reinicio la app no
   levanta, `python -m webapp --revertir-nucleo` / `--revertir-webapp` los
   intercambia de vuelta. Si la web app nueva ni siquiera importa, renombrar
   las dos carpetas a mano hace lo mismo.

5. **El tag queda anotado** en `core-release.json` / `webapp-release.json`, al
   lado de la carpeta, no adentro: el hook de pre-commit exige que `backend/`
   sea idéntico al tag del core. El instalador deja `webapp-release.json` con
   la versión del `.exe`, así la pantalla sabe qué web app corre.

6. **Hace falta reiniciar.** Python ya importó el código viejo; no se recarga
   en caliente. El servidor lo pide (`POST /updates/restart`) y el lanzador
   `python -m webapp` se vuelve a ejecutar a sí mismo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.core.contract import Field, ParamType, Resource
from backend.core.resources import ResourceError

TIMEOUT_RED = 15
TIMEOUT_VALIDACION = 90
_MAX_BYTES = 60 * 1024 * 1024
VARIABLES_TOKEN = ("GITHUB_TOKEN", "PLUGINS_GITHUB_TOKEN")
_REPO_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")


class UpdateError(Exception):
    def __init__(self, mensaje: str, detalle: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.detalle = detalle or []


# ── Componentes ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Componente:
    id: str
    label: str
    carpeta: str  # la carpeta del programa que se reemplaza
    marca: str  # el .json al lado, con el tag aplicado
    repo_por_defecto: str
    senal: str  # qué tiene que haber adentro para reconocer la carpeta en un tarball
    requisitos: str  # el requirements.txt que se compara, relativo a la carpeta
    validar: Callable[[Path], dict]

    @property
    def anterior(self) -> str:
        return f"{self.carpeta}.anterior"

    @property
    def marca_anterior(self) -> str:
        return self.marca.replace(".json", ".anterior.json")


def _validar_nucleo(backend_nuevo: Path) -> dict:
    """
    Arranca el núcleo nuevo en otro proceso, contra una raíz vacía: importa,
    migra una base en memoria y arma el catálogo. Devuelve `{"ok", "errors",
    "catalog"}`. El proceso corre con `cwd` en la carpeta que contiene ese
    `backend/`, y sin el `PYTHONPATH` de acá, para no importar el actual.
    """
    contenedor = backend_nuevo.parent
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("BOOTSTRAP_", "PYTHONPATH", "BOT_"))}
    with tempfile.TemporaryDirectory(prefix="bot-nucleo-") as raiz_tmp:
        comando = [sys.executable, "-m", "backend.core", "--root", raiz_tmp, "plugins", "--json"]
        try:
            hecho = subprocess.run(
                comando, cwd=str(contenedor), capture_output=True, text=True,
                timeout=TIMEOUT_VALIDACION, shell=False, env=entorno,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "errors": [f"el núcleo nuevo no arrancó en {TIMEOUT_VALIDACION} s"], "catalog": None}
    try:
        catalogo = json.loads(hecho.stdout)
    except ValueError:
        cola = (hecho.stderr or hecho.stdout or "").strip().splitlines()[-12:]
        return {"ok": False, "errors": ["el núcleo nuevo no armó el catálogo"] + cola, "catalog": None}
    return {"ok": True, "errors": [], "catalog": catalogo}


# Lo que el lanzador y el servidor necesitan encontrar en una webapp/ nueva.
_IMPRESCINDIBLES_WEBAPP = ("__main__.py", "server.py", "routes/core_api.py", "static/index.html")


def _validar_webapp(webapp_nueva: Path) -> dict:
    """
    Compila la web app nueva entera en otro proceso y exige los archivos que
    el lanzador usa. No la arranca: `routes.core_api` construye la instancia
    al importarse, y eso es abrir la base de la instalación real desde código
    que todavía no se aceptó. Un error de sintaxis o un archivo faltante se
    atajan acá; un error de lógica lo ataja el reinicio, con el anterior al lado.
    """
    faltan = [f for f in _IMPRESCINDIBLES_WEBAPP if not (webapp_nueva / f).is_file()]
    if faltan:
        return {"ok": False, "errors": [f"la web app nueva no trae {f}" for f in faltan], "catalog": None}
    comando = [sys.executable, "-m", "compileall", "-q", "-f", str(webapp_nueva)]
    try:
        hecho = subprocess.run(comando, capture_output=True, text=True, timeout=TIMEOUT_VALIDACION, shell=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "errors": [f"compilar la web app nueva no terminó en {TIMEOUT_VALIDACION} s"], "catalog": None}
    if hecho.returncode != 0:
        cola = (hecho.stderr or hecho.stdout or "").strip().splitlines()[-12:]
        return {"ok": False, "errors": ["la web app nueva no compila"] + cola, "catalog": None}
    return {"ok": True, "errors": [], "catalog": None}


CORE = Componente(
    id="core", label="núcleo", carpeta="backend", marca="core-release.json",
    repo_por_defecto="EasyIndustry/workflow-bot-core", senal="core",
    requisitos="requirements.txt", validar=_validar_nucleo,
)
WEBAPP = Componente(
    id="webapp", label="web app", carpeta="webapp", marca="webapp-release.json",
    repo_por_defecto="EasyIndustry/workflow-bot-app", senal="server.py",
    requisitos="requirements.txt", validar=_validar_webapp,
)
COMPONENTES: dict[str, Componente] = {c.id: c for c in (CORE, WEBAPP)}

# Compatibilidad con quien conocía el módulo de un solo componente.
REPO = CORE.repo_por_defecto
ANTERIOR = CORE.anterior
MARCA = CORE.marca
MARCA_ANTERIOR = CORE.marca_anterior


def componente(id_: str | None) -> Componente:
    comp = COMPONENTES.get(id_ or CORE.id)
    if comp is None:
        raise UpdateError(f"Componente desconocido: {id_!r}. Hay {', '.join(COMPONENTES)}.")
    return comp


# ── Configuración (repos), por instalación ──────────────────────────────

RESOURCE = Resource(
    name="actualizaciones",
    label="Actualizaciones",
    item_label="Ajuste",
    key_field="clave",
    doc="De qué repo de GitHub se traen los releases del núcleo y de la web app.",
    fields=(Field("value", ParamType.STR, label="Valor"),),
)


def _store(instance):
    return instance.resource_store("webapp", RESOURCE)


def configuracion(instance) -> dict[str, str]:
    """El repo de cada componente: el guardado en la base, o el por defecto."""
    salida = {}
    for comp in COMPONENTES.values():
        try:
            valor = (_store(instance).read(f"repo_{comp.id}").get("value") or "").strip()
        except ResourceError:
            valor = ""
        salida[comp.id] = valor or comp.repo_por_defecto
    return salida


def guardar_configuracion(instance, repos: dict[str, str]) -> dict[str, str]:
    """Guarda los repos que vengan; vacío vuelve al por defecto."""
    store = _store(instance)
    for id_, repo in repos.items():
        comp = componente(id_)
        repo = (repo or "").strip()
        if repo and not _REPO_VALIDO.match(repo):
            raise UpdateError(f"Repo inválido para {comp.label}: {repo!r}. Se espera owner/nombre.")
        store.write(f"repo_{comp.id}", {"value": repo})
    return configuracion(instance)


def token_de(instance) -> str | None:
    """El token de GitHub si se cargó como variable. Un repo público no lo necesita."""
    try:
        variables = instance.env_vars()
    except Exception:  # noqa: BLE001 — sin token se sigue como repo público
        return None
    for nombre in VARIABLES_TOKEN:
        valor = (variables.get(nombre) or "").strip()
        if valor:
            return valor
    return None


# ── Qué hay ─────────────────────────────────────────────────────────────


def instalada(programa: Path, comp: Componente = CORE, repo: str | None = None) -> dict:
    """Lo que corre de este componente: el tag anotado, si lo hay, y si existe un anterior."""
    datos = _leer_marca(programa / comp.marca) or {}
    return {
        "component": comp.id,
        "label": comp.label,
        "folder": comp.carpeta,
        "tag": datos.get("tag"),
        "applied_at": datos.get("applied_at"),
        "source": datos.get("source"),
        "has_previous": (programa / comp.anterior).is_dir(),
        "previous": _leer_marca(programa / comp.marca_anterior),
        "repo": repo or comp.repo_por_defecto,
    }


def _leer_marca(ruta: Path) -> dict | None:
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# ── Releases publicados ─────────────────────────────────────────────────


def disponibles(incluir_prueba: bool = True, abrir=None, *, repo: str | None = None, token: str | None = None) -> list[dict]:
    """
    Los releases de `repo`, del más nuevo al más viejo. `abrir` se inyecta en
    los tests; por defecto es urllib contra la API de GitHub.
    """
    abrir = abrir or _abrir_url
    repo = repo or REPO
    try:
        crudo = abrir(f"https://api.github.com/repos/{repo}/releases?per_page=30", None, token)
    except urllib.error.HTTPError as exc:
        raise UpdateError(_explicar_http(exc.code, f"listar los releases de {repo}", token)) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdateError(
            "No se pudo llegar a GitHub. Sin internet, se sube el archivo del release "
            "bajado en otra máquina.", [str(exc)],
        ) from None
    try:
        datos = json.loads(crudo)
    except ValueError:
        raise UpdateError("GitHub devolvió algo que no es JSON.") from None
    if not isinstance(datos, list):
        raise UpdateError("GitHub devolvió una respuesta inesperada.", [str(datos)[:300]])

    salida = []
    for r in datos:
        if r.get("draft"):
            continue
        if r.get("prerelease") and not incluir_prueba:
            continue
        salida.append({
            "tag": r.get("tag_name"),
            "name": r.get("name") or r.get("tag_name"),
            "prerelease": bool(r.get("prerelease")),
            "published_at": r.get("published_at"),
            "body": (r.get("body") or "")[:2000],
            "url": r.get("html_url"),
            "tarball_url": r.get("tarball_url"),
            "assets": [
                {"name": a.get("name"), "size": a.get("size"), "url": a.get("browser_download_url")}
                for a in r.get("assets", [])
            ],
        })
    return salida


def _explicar_http(codigo: int, que: str, token: str | None) -> str:
    if codigo in (401, 403, 404):
        pista = (
            "el token no lo puede leer" if token
            else f"si el repo es privado hace falta {VARIABLES_TOKEN[0]} en Config → Variables (secreta)"
        )
        return f"GitHub respondió {codigo} al {que}: {pista}."
    return f"GitHub respondió {codigo} al {que}."


def _abrir_url(url: str, destino: Path | None = None, token: str | None = None) -> bytes | Path:
    cabeceras = {"Accept": "application/vnd.github+json", "User-Agent": "bot-webapp-updater"}
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
                    raise UpdateError("El archivo del release pesa más de 60 MB: no es lo que se espera.")
                f.write(trozo)
        return destino


def descargar(tag: str, carpeta: Path, abrir=None, *, repo: str | None = None, token: str | None = None,
              comp: Componente = CORE) -> Path:
    """Baja el tarball del tag a `carpeta`. Devuelve la ruta."""
    abrir = abrir or _abrir_url
    repo = repo or comp.repo_por_defecto
    _validar_tag(tag)
    destino = carpeta / f"{comp.id}-{tag}.tar.gz"
    url = f"https://api.github.com/repos/{repo}/tarball/{tag}"
    try:
        abrir(url, destino, token)
    except urllib.error.HTTPError as exc:
        raise UpdateError(_explicar_http(exc.code, f'bajar el tag "{tag}" de {repo}', token)) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdateError("No se pudo bajar el release: sin conexión a GitHub.", [str(exc)]) from None
    return destino


_TAG_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")


def _validar_tag(tag: str) -> None:
    if not _TAG_VALIDO.match(tag or ""):
        raise UpdateError(f"Tag inválido: {tag!r}")


# ── Preparar y validar ──────────────────────────────────────────────────


def preparar(archivo: Path, tmp: Path, comp: Componente = CORE) -> Path:
    """
    Desempaqueta el release y devuelve la ruta de la carpeta del componente
    que trae. Acepta el tarball de GitHub (una carpeta `owner-repo-sha/` con
    la carpeta adentro), un `.zip` equivalente, o un archivo con la carpeta
    en la raíz.
    """
    extraido = tmp / "release"
    extraido.mkdir()
    nombre = archivo.name.lower()
    try:
        if nombre.endswith((".tar.gz", ".tgz", ".tar")):
            with tarfile.open(archivo) as t:
                for m in t.getmembers():
                    _ruta_segura(m.name)
                    if m.issym() or m.islnk():
                        raise UpdateError(f"El archivo trae un enlace ({m.name}): no se acepta.")
                # `filter="data"` (3.12+) además rechaza permisos raros y
                # enlaces; en 3.10/3.11 no existe y la revisión de arriba alcanza.
                if hasattr(tarfile, "data_filter"):
                    t.extractall(extraido, filter="data")
                else:
                    t.extractall(extraido)  # noqa: S202 — rutas ya revisadas
        elif nombre.endswith(".zip"):
            with zipfile.ZipFile(archivo) as z:
                for info in z.infolist():
                    _ruta_segura(info.filename)
                z.extractall(extraido)
        else:
            raise UpdateError(f"{archivo.name}: se espera el .tar.gz o el .zip del release.")
    except (tarfile.TarError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"{archivo.name} no se pudo abrir: {exc}") from None

    return _encontrar_carpeta(extraido, comp)


def _ruta_segura(nombre: str) -> None:
    partes = Path(nombre).parts
    if nombre.startswith(("/", "\\")) or ".." in partes or (len(partes) > 0 and ":" in partes[0]):
        raise UpdateError(f"El archivo trae una ruta inválida: {nombre}")


def _es_la_carpeta(ruta: Path, comp: Componente) -> bool:
    return ruta.is_dir() and (ruta / comp.senal).exists()


def _encontrar_carpeta(extraido: Path, comp: Componente) -> Path:
    if _es_la_carpeta(extraido / comp.carpeta, comp):
        return extraido / comp.carpeta
    for hijo in (p for p in extraido.iterdir() if p.is_dir()):
        if _es_la_carpeta(hijo / comp.carpeta, comp):
            return hijo / comp.carpeta
        if hijo.name == comp.carpeta and _es_la_carpeta(hijo, comp):
            return hijo
    raise UpdateError(
        f"El archivo no trae un {comp.carpeta}/ con {comp.senal} adentro. Se espera el tarball "
        f"del tag de {comp.repo_por_defecto} (o su .zip)."
    )


def validar(nuevo: Path, comp: Componente = CORE) -> dict:
    """Lo que el componente exige antes de aplicarse; ver cada `_validar_*`."""
    return comp.validar(nuevo)


def requisitos_nuevos(actual: Path, nuevo: Path, comp: Componente = CORE) -> list[str]:
    """Líneas de `requirements.txt` que el nuevo pide y el actual no. Informativo."""
    return sorted(_requisitos(nuevo / comp.requisitos) - _requisitos(actual / comp.requisitos))


def _requisitos(archivo: Path) -> set[str]:
    if not archivo.is_file():
        return set()
    salida = set()
    for linea in archivo.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea:
            salida.add(linea)
    return salida


# ── Aplicar y revertir ──────────────────────────────────────────────────


def aplicar(programa: Path, nuevo: Path, *, tag: str, fuente: str, comp: Componente = CORE) -> dict:
    """
    Mueve la carpeta actual a `<carpeta>.anterior/` y copia la nueva. Anota
    el tag. No reinicia: eso lo decide quien llama.
    """
    actual = programa / comp.carpeta
    anterior = programa / comp.anterior
    if not actual.is_dir():
        raise UpdateError(f"No hay un {comp.carpeta}/ en {programa}: nada que actualizar.")

    marca_actual = _leer_marca(programa / comp.marca)
    if anterior.exists():
        shutil.rmtree(anterior, ignore_errors=True)
    actual.rename(anterior)
    try:
        shutil.copytree(nuevo, actual, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception:
        # Volver a dejar todo como estaba: sin la carpeta la app no arranca.
        if actual.exists():
            shutil.rmtree(actual, ignore_errors=True)
        anterior.rename(actual)
        raise

    # El núcleo lee su versión de `backend/VERSION` cuando no hay `.dist-info`
    # (core#5), y `release.yml` deja ese archivo en el wheel — no en el
    # tarball de fuente del tag, que es lo que se baja acá. Sin esto, una
    # instalación actualizada seguía diciendo "0.0.0+sin-instalar" en el
    # manifest del core. El tag ya se conoce: se escribe pelado de la "v".
    if comp is CORE and tag and not (actual / "VERSION").exists():
        (actual / "VERSION").write_text(tag.lstrip("vV") + "\n", encoding="utf-8")

    # Los tests no hacen falta en una instalación, pero tampoco molestan: se
    # dejan tal cual vienen. La marca del que estaba pasa a ser la del
    # anterior, y se escribe la nueva.
    marca = {
        "tag": tag,
        "applied_at": time.time(),
        "source": fuente,
        "previous_tag": (marca_actual or {}).get("tag"),
    }
    _escribir_marca(programa / comp.marca_anterior, marca_actual)
    _escribir_marca(programa / comp.marca, marca)
    return marca


def revertir(programa: Path, comp: Componente = CORE) -> dict:
    """Intercambia la carpeta y su `.anterior/`. La que estaba queda como anterior."""
    actual = programa / comp.carpeta
    anterior = programa / comp.anterior
    if not anterior.is_dir():
        raise UpdateError(f"No hay un {comp.label} anterior guardado.")
    temporal = programa / f"{comp.carpeta}.cambiando"
    if temporal.exists():
        shutil.rmtree(temporal, ignore_errors=True)
    actual.rename(temporal)
    anterior.rename(actual)
    temporal.rename(anterior)
    # Las marcas se intercambian con las carpetas.
    m_actual, m_anterior = _leer_marca(programa / comp.marca), _leer_marca(programa / comp.marca_anterior)
    _escribir_marca(programa / comp.marca, m_anterior)
    _escribir_marca(programa / comp.marca_anterior, m_actual)
    return instalada(programa, comp)


def _escribir_marca(ruta: Path, datos: dict | None) -> None:
    """Escribe la marca, o la borra si no hay qué anotar."""
    if datos is None:
        if ruta.exists():
            ruta.unlink()
        return
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def descartar_anterior(programa: Path, comp: Componente = CORE) -> None:
    anterior = programa / comp.anterior
    if anterior.is_dir():
        shutil.rmtree(anterior, ignore_errors=True)
    _escribir_marca(programa / comp.marca_anterior, None)

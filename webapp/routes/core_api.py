"""
API del núcleo.

Es la superficie única: la UI y el MCP consumen estos mismos endpoints. El MCP
va a ser un adaptador delgado sobre esto, **no** una segunda implementación —
que es exactamente el modo de falla de este repo.

Los endpoints son delgados a propósito: validan la entrada, llaman a
`core.Instance` y devuelven lo que ya viene serializable. Toda la lógica está
en el núcleo, donde se testea sin levantar un servidor.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import asyncio
import importlib.util
import json
import re

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

# Dónde está el código (el repo, o la carpeta del programa instalado).
REPO = Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from webapp import ubicacion  # noqa: E402

# Dónde está la instalación: boot.env, data/, workspace/, plugins/. En el repo
# de desarrollo es la misma carpeta que el código; en una máquina de un
# cliente es la que eligió en el wizard. Ver webapp/ubicacion.py.
ROOT = ubicacion.resolver_root(REPO, os.environ.get("BOT_ROOT"))

from backend.core.doctor import run_checks  # noqa: E402
from backend.core.env_store import EnvError  # noqa: E402
from backend.core.flow import serializer  # noqa: E402
from backend.core.flow.parser import parse_flow  # noqa: E402
from backend.core.instance import Instance, WorkflowNotFound  # noqa: E402
from backend.core.resources import ResourceError  # noqa: E402
from backend.core.ports import PLUGIN_PORTS  # noqa: E402
from backend.core.stores import StoreError  # noqa: E402
from backend.core.users import DEFAULTS_POR_KIND, KINDS, UserError  # noqa: E402
from webapp import db_view, plugin_catalog, plugin_install, updates  # noqa: E402
from webapp import (  # noqa: E402
    agent_provider_config,
    agent_providers,
    agent_sessions,
    agent_settings,
    mcp_registration,
)
from webapp.agent_terminal import TerminalSession  # noqa: E402
from webapp.run_gate import RunGate, run_with_gate  # noqa: E402
from webapp.runs_en_vuelo import RunsEnVuelo  # noqa: E402

router = APIRouter()

# Una sola instancia por proceso: el registro se arma una vez, no por request.
#
# `connections` entra por `local_plugins` y no por entry point: es un default de
# **esta** webapp, no algo que un tercero instale u omita — por eso vive bajo
# `webapp/` y se registra acá, no en `backend/core`. Ver `webapp/connections/plugin.py`.
LOCAL_PLUGINS = {"connections": "webapp.connections.plugin:PLUGIN"}
_instance = Instance(ROOT, local_plugins=LOCAL_PLUGINS)

# Un solo gate por proceso, igual que la instancia: todos los runs de esta
# máquina se coordinan entre sí. Ver `webapp/run_gate.py`.
_gate = RunGate()
# Y un solo registro de lo que está corriendo, que es lo que la grilla dibuja
# como progreso mientras `POST /run` no volvió. Ver `webapp/runs_en_vuelo.py`.
_en_vuelo = RunsEnVuelo()


def instance() -> Instance:
    return _instance


def _recargar_instancia(modulos: tuple[str, ...] = ()) -> None:
    """
    Vuelve a construir la instancia: el registry se arma una sola vez, así que
    instalar o sacar un plugin obliga a esto.

    `modulos` son los nombres de plugin que cambiaron en disco: se sacan de
    `sys.modules` (con sus submódulos) para que el import siguiente lea el
    archivo nuevo y no el que ya estaba cargado. Sin esto, reemplazar un
    plugin "funcionaba" pero seguía corriendo la versión anterior.

    Quien llama lo hace con el gate en exclusivo: nada corre mientras se cambia
    la instancia de abajo. La anterior se cierra; los runs que ya terminaron
    están en la base, no en memoria.
    """
    global _instance
    for nombre in modulos:
        for cargado in [m for m in sys.modules if m == nombre or m.startswith(nombre + ".")]:
            del sys.modules[cargado]
    importlib.invalidate_caches()
    anterior = _instance
    _instance = Instance(ROOT, local_plugins=LOCAL_PLUGINS)
    try:
        anterior.db.close()
    except Exception:  # noqa: BLE001 — cerrar lo viejo no puede tumbar lo nuevo
        pass


# ── Catálogo y salud ────────────────────────────────────────────────────


@router.get("/overview")
def get_overview():
    """
    Qué tiene esta instalación, en una mirada. Es lo que dibuja la pantalla de
    Inicio y lo que decide si una instalación está "recién hecha": sin plugins
    instalados, sin fuentes y sin flujos.
    """
    catalogo = _instance.registry.catalog()
    plugins = [p for p in catalogo["plugins"] if p["source"] != "builtin"]
    carpeta = _instance.boot.plugins_dir
    instalados = plugin_install.instalados(carpeta)
    try:
        fuentes = len(_instance.resource_items("connections", "sources"))
    except Exception:  # noqa: BLE001 — sin el plugin connections no hay fuentes, no es un error
        fuentes = 0
    flujos = _instance.list_workflows()
    actores = _instance.users.list(include_disabled=False)
    return {
        "root": str(ROOT),
        "plugins_dir": str(carpeta) if carpeta else None,
        "plugins": len(plugins),
        "plugins_installed": len(instalados),
        "plugin_errors": len(catalogo.get("errors", [])),
        "sources": fuentes,
        "workflows": len(flujos),
        "actors": len(actores),
        "default_actor": _instance.boot.default_actor,
        "key_exists": _llave_existe(),
        "fresh": not instalados and fuentes == 0 and not flujos,
    }


@router.get("/tools")
def get_tools():
    """
    Catálogo de tools y plugins con sus settings y resources.

    La UI se dibuja con esto. Antes el catálogo estaba escrito dos veces —en
    `catalog.js` a mano y en las rutas de Python— así que un tool nuevo obligaba
    a tocar los dos. Ahora un plugin instalado aparece sin tocar una línea de JS.
    """
    return _instance.registry.catalog()


@router.get("/doctor")
async def get_doctor():
    """Diagnóstico de la instalación. Mismo informe que `python -m core.doctor`."""
    reporte = await run_in_threadpool(
        run_checks, root=ROOT, registry=_instance.registry, config=_instance.config.read()
    )
    return reporte.to_dict()


# ── Configuración ───────────────────────────────────────────────────────


class ConfigBody(BaseModel):
    values: dict


@router.get("/config")
def get_config():
    """
    Configuración de esta instancia, con lo que falta según los manifests.

    Vive en el servidor, no en `localStorage`: antes cada navegador tenía la
    suya, no se sincronizaba entre máquinas y se perdía al limpiar el navegador.
    """
    config = _instance.registry.effective_config(_instance.config.read())
    faltantes = _instance.registry.missing_config(config)
    return {
        "values": config,
        "missing": {
            plugin: [m.to_dict() for m in pendientes]
            for plugin, pendientes in faltantes.items()
        },
    }


@router.patch("/config")
def patch_config(body: ConfigBody):
    """Mergea las claves dadas; el resto queda como está."""
    return {"values": _instance.config.update(body.values)}


# ── Variables y secretos ────────────────────────────────────────────────


class EnvBody(BaseModel):
    value: str
    secret: bool = False


@router.get("/env")
def get_env():
    """
    Lo que los flujos interpolan como `{env.CLAVE}`, con su conteo de usos.

    **El valor de un secreto no sale por acá.** La respuesta trae el nombre, si
    tiene valor y cuándo cambió; la clave `value` sólo existe para las
    variables. Es la regla del almacén write-only, y está en el núcleo —
    `EnvVar.to_dict()`— y no en este endpoint, para que el MCP no pueda tener
    otra política que la UI.

    Los nombres que un flujo o una conexión referencian y nadie cargó también
    aparecen, marcados `undeclared`: son justo los que van a romper una
    ejecución, así que esconderlos sería lo contrario de lo útil.
    """
    return {
        "items": _instance.env_listing(),
        # La UI necesita saberlo para explicar qué pasa si se pierde el archivo.
        "key_exists": _llave_existe(),
    }


def _llave_existe() -> bool:
    """
    Si ya hay llave de cifrado. Vive en el adapter de crypto, no en el EnvStore:
    el núcleo la movió ahí (la llave es del cifrador, el almacén sólo lo usa).
    El `getattr` cubre un adapter sin llave en disco —el de los tests, o uno en
    memoria—, para el que la pregunta no tiene sentido y la respuesta es "no".
    """
    return bool(getattr(_instance.crypto, "key_exists", False))


@router.put("/env/{name}")
def put_env(name: str, body: EnvBody):
    """
    Da de alta o reemplaza. Un secreto entra cifrado y no se puede volver a leer.

    No hay PATCH: un secreto no se edita, se reemplaza. Editar exigiría leerlo
    primero para mostrarlo, que es exactamente lo que este almacén no hace.
    """
    try:
        guardado = _instance.env.save(name, body.value, secret=body.secret)
    except EnvError as exc:
        raise HTTPException(400, str(exc)) from None
    return guardado.to_dict(_instance.env_usage().get(guardado.name, 0))


@router.delete("/env/{name}")
def delete_env(name: str):
    if not _instance.env.delete(name):
        raise HTTPException(404, f'No hay ninguna variable "{name}" cargada')
    return {"deleted": name}


@router.get("/storage")
def get_storage():
    """
    Dónde vive la base, cuánto ocupa, y si está la llave de los secretos.

    El núcleo informa esquema, conteos y qué adapter de cifrado hay; la ruta,
    el tamaño y la llave son de la instalación y se completan acá, que es
    donde se sabe cómo arrancó esta instancia (`boot`). Mismo diccionario para
    que la pantalla no tenga que pedir dos cosas.
    """
    info = dict(_instance.storage_info())
    ruta = Path(_instance.boot.storage_path)
    llave = getattr(_instance.crypto, "key_path", None)
    info.update({
        "path": str(ruta),
        "exists": ruta.exists(),
        "bytes": ruta.stat().st_size if ruta.exists() else 0,
        "key_path": str(llave) if llave else "",
        "key_exists": _llave_existe(),
    })
    return info


@router.get("/storage/tables")
def get_storage_tables():
    """Las tablas del esquema del núcleo, con cuántas filas tiene cada una."""
    return {"tables": db_view.tablas(_instance.db)}


@router.get("/storage/tables/{table}")
def get_storage_rows(
    table: str,
    limit: int = Query(50, ge=1, le=db_view.LIMITE_MAXIMO),
    offset: int = Query(0, ge=0),
):
    """
    Una página de una tabla, de la fila más nueva a la más vieja. Sólo lectura,
    y sin secretos: ver `webapp/db_view.py`.
    """
    try:
        return db_view.filas(_instance.db, _instance.registry, table, limit=limit, offset=offset)
    except db_view.TablaDesconocida as e:
        raise HTTPException(404, str(e))


# ── Plugins: instalar y desinstalar ─────────────────────────────────────
#
# Instalar es dejar el plugin en `plugins_dir` y recargar la instancia; la
# validación previa, en un subproceso, vive en webapp/plugin_install.py. Dos
# entradas, un mismo camino: un archivo subido desde el navegador, o una ruta
# de esta máquina — que es lo que usa un agente que acaba de escribirlo con
# plugin_template + load_plugin por MCP.


@router.get("/plugins/install-info")
def get_install_info():
    """Dónde se instala, qué hay ahí, y qué plugins no cargaron."""
    carpeta = _instance.boot.plugins_dir
    return {
        "plugins_dir": str(carpeta) if carpeta else None,
        "installed": plugin_install.instalados(carpeta),
        "errors": _instance.registry.catalog().get("errors", []),
        # Los ports que un plugin puede pedir, para la plantilla: salen del
        # núcleo y no de una lista escrita en el front, que quedó vieja apenas
        # apareció `browser`.
        "ports": sorted(PLUGIN_PORTS),
    }


class InstallPathBody(BaseModel):
    path: str
    name: str | None = None
    replace: bool = False


@router.post("/plugins/install/path", status_code=201)
async def install_plugin_from_path(body: InstallPathBody):
    """Instala un `.py`, una carpeta con `__init__.py` o un `.zip` que ya está en esta máquina."""
    return await _instalar(Path(body.path), nombre=body.name, reemplazar=body.replace)


@router.post("/plugins/install/upload", status_code=201)
async def install_plugin_from_upload(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    replace: bool = Form(False),
):
    """Instala un `.py` o un `.zip` subido desde el navegador."""
    sufijo = Path(file.filename or "").suffix
    if sufijo not in (".py", ".zip"):
        raise HTTPException(400, "Se sube un .py o un .zip (una carpeta va comprimida).")
    tmp = Path(tempfile.mkdtemp(prefix="bot-subida-"))
    try:
        destino = tmp / Path(file.filename).name
        with destino.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        return await _instalar(destino, nombre=name or None, reemplazar=replace)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _instalar(origen: Path, *, nombre: str | None, reemplazar: bool):
    carpeta = _instance.boot.plugins_dir
    try:
        resultado = await run_in_threadpool(
            plugin_install.instalar, carpeta, origen, nombre=nombre, reemplazar=reemplazar
        )
    except plugin_install.InstallError as exc:
        raise HTTPException(400, {"message": str(exc), "errors": exc.errores}) from None

    # Exclusivo: que ningún run esté a mitad de camino mientras se cambia la
    # instancia de abajo. Y el veredicto final es el de la instancia nueva:
    # un id de tool que choca con otro plugin ya instalado sólo se ve acá.
    async with _gate.exclusive():
        _recargar_instancia((resultado["name"],))
        errores = [e for e in _instance.registry.catalog().get("errors", []) if e["name"] == resultado["name"]]
        if errores:
            plugin_install.desinstalar(carpeta, resultado["name"])
            _recargar_instancia((resultado["name"],))
            raise HTTPException(400, {
                "message": f'"{resultado["name"]}" no carga junto a lo ya instalado; se deshizo la instalación.',
                "errors": [e["error"] for e in errores],
            })
    return {"installed": resultado, "catalog": _instance.registry.catalog()}


# ── Plugins en línea: el catálogo curado en GitHub ──────────────────────
#
# El programa se instala sin plugins; los que hacen falta se traen de acá.
# Ver webapp/plugin_catalog.py. Instalar reusa `_instalar` —validación en otro
# proceso, copia, recarga— y suma la procedencia (repo, rama, commit).


@router.get("/plugins/catalog")
async def get_plugin_catalog():
    """Repo y rama configurados, las ramas que hay, y las entradas con qué está instalado."""
    return await run_in_threadpool(plugin_catalog.listar, _instance)


class CatalogConfigBody(BaseModel):
    repo: str
    branch: str


@router.put("/plugins/catalog/config")
def put_plugin_catalog_config(body: CatalogConfigBody):
    try:
        return plugin_catalog.guardar_configuracion(_instance, repo=body.repo, branch=body.branch)
    except plugin_catalog.CatalogError as exc:
        raise HTTPException(400, str(exc)) from None


class CatalogInstallBody(BaseModel):
    name: str


@router.post("/plugins/catalog/install", status_code=201)
async def install_plugin_from_catalog(body: CatalogInstallBody):
    """Baja la rama configurada, saca la carpeta que declara la entrada y la instala (reemplazando)."""
    cfg = plugin_catalog.configuracion(_instance)
    token = plugin_catalog.token_de(_instance)
    try:
        candidatas = await run_in_threadpool(plugin_catalog.entradas, cfg["repo"], cfg["branch"], None, token)
    except plugin_catalog.CatalogError as exc:
        raise HTTPException(502, {"message": str(exc), "errors": exc.detalle}) from None
    entrada = next((e for e in candidatas if e["name"] == body.name), None)
    if entrada is None:
        raise HTTPException(404, f'No hay un plugin "{body.name}" en la rama "{cfg["branch"]}" de {cfg["repo"]}.')

    tmp = Path(tempfile.mkdtemp(prefix="bot-catalogo-"))
    try:
        try:
            carpeta, commit = await run_in_threadpool(
                plugin_catalog.descargar_carpeta, entrada, repo=cfg["repo"], branch=cfg["branch"], tmp=tmp, token=token,
            )
        except plugin_catalog.CatalogError as exc:
            raise HTTPException(502, {"message": str(exc), "errors": exc.detalle}) from None
        resultado = await _instalar(carpeta, nombre=entrada["module"], reemplazar=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    procedencia = plugin_catalog.datos_de_procedencia(
        entrada, repo=cfg["repo"], branch=cfg["branch"], commit=commit,
        version=(resultado["installed"].get("plugin") or {}).get("version", ""),
    )
    plugin_catalog.anotar_procedencia(Path(resultado["installed"]["path"]), procedencia)
    return {**resultado, "provenance": procedencia}


@router.delete("/plugins/{name}")
async def uninstall_plugin(name: str):
    """Saca un plugin de `plugins_dir`. Sus settings e items quedan en la base, por si vuelve."""
    carpeta = _instance.boot.plugins_dir
    try:
        ruta = plugin_install.desinstalar(carpeta, name)
    except plugin_install.InstallError as exc:
        raise HTTPException(404, str(exc)) from None
    async with _gate.exclusive():
        _recargar_instancia((name,))
    return {"uninstalled": name, "path": str(ruta)}


class TemplateBody(BaseModel):
    name: str
    ports: list[str] = []


@router.post("/plugins/template")
def plugin_template(body: TemplateBody):
    """
    El esqueleto de un plugin, generado desde el contrato. Es la misma
    operación que el MCP expone como `plugin_template`: un agente arranca por
    acá, escribe el archivo, y lo instala por ruta.
    """
    from backend.mcp.operations import plugin_template as generar

    return generar(body.name, body.ports)


# ── Actualizaciones del núcleo y de la web app ──────────────────────────
#
# backend/ se trae de los releases del core y webapp/ de los del repo de este
# programa; cada uno se reemplaza entero, ver webapp/updates.py. Acá sólo se
# orquesta: bajar o recibir el archivo, validar lo nuevo en otro proceso,
# aplicarlo con el anterior al lado, y reiniciar cuando quien mira lo pida.
# El repo de cada componente se guarda por instalación (`PUT /updates/config`).


def _componente(id_: str) -> updates.Componente:
    try:
        return updates.componente(id_)
    except updates.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/updates")
def get_updates():
    """Qué corre de cada componente (tag anotado, si lo hay), los repos, y si se puede reiniciar desde acá."""
    catalogo = _instance.registry.catalog()
    nucleo = next((p for p in catalogo["plugins"] if p["name"] == "core"), None)
    repos = updates.configuracion(_instance)
    componentes = {
        comp.id: {
            **updates.instalada(REPO, comp, repos[comp.id]),
            "version": (nucleo["version"] if nucleo else None) if comp is updates.CORE else None,
            "default_repo": comp.repo_por_defecto,
        }
        for comp in updates.COMPONENTES.values()
    }
    return {
        "components": componentes,
        "repos": repos,
        "program_dir": str(REPO),
        "can_restart": bool(getattr(router, "_reiniciar", None)),
        "token_variables": list(updates.VARIABLES_TOKEN),
        "has_token": updates.token_de(_instance) is not None,
    }


class UpdatesConfigBody(BaseModel):
    core: str = ""
    webapp: str = ""


@router.put("/updates/config")
def put_updates_config(body: UpdatesConfigBody):
    """El repo de cada componente. Vacío vuelve al por defecto."""
    try:
        return {"repos": updates.guardar_configuracion(_instance, {"core": body.core, "webapp": body.webapp})}
    except updates.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/updates/releases")
def get_releases(prerelease: bool = Query(True), component: str = Query("core")):
    comp = _componente(component)
    repo = updates.configuracion(_instance)[comp.id]
    try:
        return {"releases": updates.disponibles(incluir_prueba=prerelease, repo=repo, token=updates.token_de(_instance)), "repo": repo}
    except updates.UpdateError as exc:
        raise HTTPException(502, {"message": str(exc), "errors": exc.detalle}) from None


class UpdateTagBody(BaseModel):
    tag: str
    component: str = "core"


@router.post("/updates/install/tag")
async def install_update_from_tag(body: UpdateTagBody):
    """Baja el tarball del tag y lo aplica. Devuelve la marca; hace falta reiniciar."""
    comp = _componente(body.component)
    repo = updates.configuracion(_instance)[comp.id]
    tmp = Path(tempfile.mkdtemp(prefix="bot-update-"))
    try:
        archivo = await run_in_threadpool(
            updates.descargar, body.tag, tmp, repo=repo, token=updates.token_de(_instance), comp=comp,
        )
        return await _aplicar_update(archivo, tmp, tag=body.tag, fuente=f"github:{repo}@{body.tag}", comp=comp)
    except updates.UpdateError as exc:
        raise HTTPException(400, {"message": str(exc), "errors": exc.detalle}) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/updates/install/upload")
async def install_update_from_upload(file: UploadFile = File(...), tag: str = Form(""), component: str = Form("core")):
    """El mismo release, subido desde el navegador: para máquinas sin internet."""
    comp = _componente(component)
    nombre = Path(file.filename or "release.tar.gz").name
    tmp = Path(tempfile.mkdtemp(prefix="bot-update-"))
    try:
        archivo = tmp / nombre
        with archivo.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        etiqueta = tag.strip() or _tag_del_nombre(nombre)
        return await _aplicar_update(archivo, tmp, tag=etiqueta, fuente=f"archivo:{nombre}", comp=comp)
    except updates.UpdateError as exc:
        raise HTTPException(400, {"message": str(exc), "errors": exc.detalle}) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tag_del_nombre(nombre: str) -> str:
    """`workflow-bot-core-v0.2.1-beta1.tar.gz` → `v0.2.1-beta1`; si no se ve, el nombre pelado."""
    import re

    m = re.search(r"(v?\d+\.\d+[\w.\-]*)", nombre)
    return m.group(1).rstrip(".") if m else nombre


async def _aplicar_update(archivo: Path, tmp: Path, *, tag: str, fuente: str, comp: updates.Componente):
    nuevo = await run_in_threadpool(updates.preparar, archivo, tmp, comp)
    veredicto = await run_in_threadpool(updates.validar, nuevo, comp)
    if not veredicto["ok"]:
        raise HTTPException(400, {"message": f"El {comp.label} nuevo no pasa la validación; no se aplicó.", "errors": veredicto["errors"]})
    requisitos = updates.requisitos_nuevos(REPO / comp.carpeta, nuevo, comp)
    # Exclusivo: que ningún run esté a mitad de camino mientras se cambia el
    # código de abajo. Lo que ya importó Python sigue siendo el viejo hasta
    # reiniciar; lo que se evita es que un run arranque justo en el medio.
    async with _gate.exclusive():
        marca = await run_in_threadpool(updates.aplicar, REPO, nuevo, tag=tag, fuente=fuente, comp=comp)
    catalogo = veredicto.get("catalog") or {}
    return {
        "component": comp.id,
        "label": comp.label,
        "applied": marca,
        "new_requirements": requisitos,
        "restart_required": True,
        "can_restart": bool(getattr(router, "_reiniciar", None)),
        "core_version": next((p["version"] for p in catalogo.get("plugins", []) if p["name"] == "core"), None),
    }


@router.post("/updates/revert")
async def revert_update(component: str = Query("core")):
    """Vuelve al anterior de ese componente. También hace falta reiniciar."""
    comp = _componente(component)
    try:
        async with _gate.exclusive():
            estado = await run_in_threadpool(updates.revertir, REPO, comp)
    except updates.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None
    return {**estado, "restart_required": True, "can_restart": bool(getattr(router, "_reiniciar", None))}


@router.delete("/updates/previous")
def discard_previous(component: str = Query("core")):
    comp = _componente(component)
    updates.descartar_anterior(REPO, comp)
    return updates.instalada(REPO, comp)


@router.post("/updates/restart")
async def restart_server():
    """
    Reinicia el servidor. Sólo cuando lo arrancó `python -m webapp`, que es
    quien sabe volver a levantarlo; bajo uvicorn --reload o un supervisor
    ajeno se devuelve 409 y se reinicia a mano.
    """
    reiniciar = getattr(router, "_reiniciar", None)
    if reiniciar is None:
        raise HTTPException(409, "Este servidor no se puede reiniciar desde acá: reiniciá el proceso a mano.")
    async with _gate.exclusive():
        reiniciar()
    return {"restarting": True}


# ── Actores ─────────────────────────────────────────────────────────────
#
# La tabla `users` del núcleo guarda actores: personas, agentes, agendas y el
# propio sistema. Es identidad y política —qué puede ejecutar cada uno—, no
# autenticación: acá nadie prueba ser quien dice. Ver backend/core/users.py.
# No hay DELETE a propósito: los runs apuntan al actor por nombre, y la baja
# es lógica.


class UserCreateBody(BaseModel):
    name: str
    kind: str = "human"
    label: str = ""
    # None = el default del kind. Ver DEFAULTS_POR_KIND.
    can_run_dangerous: bool | None = None
    allowed_ports: list[str] | None = None


class UserPatchBody(BaseModel):
    can_run_dangerous: bool | None = None
    allowed_ports: list[str] | None = None
    # True abre todos los ports (allowed_ports = None en la fila).
    clear_ports: bool = False
    enabled: bool | None = None


def _users_payload():
    return {
        "items": [u.to_dict() for u in _instance.users.list()],
        "default_actor": _instance.boot.default_actor,
        "kinds": list(KINDS),
        "defaults": DEFAULTS_POR_KIND,
        "ports": sorted(PLUGIN_PORTS),
    }


@router.get("/users")
def get_users():
    """Todos los actores, habilitados o no, más el vocabulario para dar de alta."""
    return _users_payload()


@router.post("/users", status_code=201)
def create_user(body: UserCreateBody):
    try:
        creado = _instance.users.create(
            body.name, kind=body.kind, label=body.label,
            can_run_dangerous=body.can_run_dangerous, allowed_ports=body.allowed_ports,
        )
    except UserError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"user": creado.to_dict()}


@router.patch("/users/{name}")
def patch_user(name: str, body: UserPatchBody):
    """Cambia permisos y/o habilita o deshabilita. Nunca borra."""
    try:
        if body.enabled is False and name == _instance.boot.default_actor:
            raise HTTPException(
                400, f'"{name}" es el actor por defecto del arranque (boot.env): '
                     "deshabilitarlo dejaría sin actor a toda ejecución que no nombre uno.",
            )
        if body.can_run_dangerous is not None or body.allowed_ports is not None or body.clear_ports:
            _instance.users.update_policy(
                name, can_run_dangerous=body.can_run_dangerous,
                allowed_ports=body.allowed_ports, clear_ports=body.clear_ports,
            )
        if body.enabled is True:
            _instance.users.enable(name)
        elif body.enabled is False:
            _instance.users.disable(name)
        actual = _instance.users.get(name)
    except UserError as exc:
        raise HTTPException(404 if "no existe" in str(exc) else 400, str(exc)) from None
    if actual is None:
        raise HTTPException(404, f'no existe el actor "{name}"')
    return {"user": actual.to_dict()}



def _conexion_mcp() -> dict:
    """
    El argv que levanta `backend/mcp` desde esta misma instalación.

    Compartido entre `GET /agent` (lo que se pega a mano) y
    `mcp_registration.registrar` (lo que se escribe solo tras un
    install/login) — un solo lugar que arma el comando, para que las dos
    formas de registrar la conexión nunca diverjan.

    El `cwd` es REPO —donde está el código, `%LOCALAPPDATA%\\Programs\\Bot`
    en una instalación— y no ROOT, la carpeta de datos que eligió el wizard:
    `python -m backend.mcp` necesita importar `backend`, y en la máquina de un
    cliente esas dos carpetas son distintas. Con ROOT el servidor moría con
    "No module named 'backend'" y el cliente MCP sólo veía "Connection
    closed"; en el repo de desarrollo son la misma carpeta y no se notaba.
    La instalación a operar viaja aparte, como `root` de cada tool.

    El mismo dato va también como `env.PYTHONPATH`: Claude Code ignora la
    clave `cwd` de `.mcp.json` (arranca el servidor en la carpeta del
    proyecto y lo único que respeta es `env`), así que con `cwd` solo
    reportaba CONNECTION_CLOSED en una instalación. `env` lo entienden todos
    los clientes; `cwd` se deja para los que sí lo leen y para pegarlo a mano.

    `python.exe` y no `pythonw.exe`: el servidor habla por stdin/stdout, y
    el intérprete sin consola es el que corre "Abrir Bot", no el que quiere
    un cliente MCP. Al lado del uno siempre está el otro.
    """
    ejecutable = Path(sys.executable)
    if ejecutable.name.lower() == "pythonw.exe":
        consola = ejecutable.with_name("python.exe")
        if consola.is_file():
            ejecutable = consola
    return {
        "command": str(ejecutable),
        # webapp.mcp_servidor y no backend.mcp directo: es el mismo servidor
        # con `root` = esta instalación y `connections` cargado — ver ese módulo.
        "args": ["-m", "webapp.mcp_servidor"],
        "cwd": str(REPO),
        "env": {"PYTHONPATH": str(REPO), "BOT_ROOT": str(ROOT)},
    }


@router.get("/agent")
def get_agent_config():
    """
    Lo que hace falta para conectar un agente MCP a esta instalación.

    `backend/mcp` es un servidor por **stdio**: lo levanta el cliente del
    agente (Claude Desktop, Claude Code, Cursor, Codex, cualquiera que hable
    MCP), no esta webapp — por eso no hay un "conectado" que mostrar acá,
    sólo la receta para que ese cliente lo levante él mismo, apuntando a esta
    instalación y no a un checkout de desarrollo. Para Claude Code, Codex y
    Antigravity, además, no hace falta ni copiar esto: `mcp_registration` ya
    lo escribe solo apenas se instala/loguea ese proveedor desde la terminal
    de la pestaña Agente.

    `root` viaja aparte del bloque de conexión a propósito: cada tool del MCP
    lo recibe como argumento propio (`run_flow(root=...)`, `load_plugin(root=...)`),
    no como algo fijado al arrancar el servidor — así que es un dato para
    pasarle al agente, no algo que entre en su config de conexión.
    """
    mcp_instalado = importlib.util.find_spec("mcp") is not None
    return {
        "connection": _conexion_mcp(),
        "root": str(_instance.boot.root),
        "mcp_instalado": mcp_instalado,
    }


@router.get("/agent/providers")
def get_agent_providers():
    """Proveedores de CLI conocidos, y si ya están instalados en esta máquina."""
    return {"providers": agent_providers.estado(), "winget": agent_providers.ruta_de_winget() is not None}


@router.get("/agent/providers/{proveedor_id}/config")
def get_agent_provider_config(proveedor_id: str):
    """Notas/ajustes guardados para este proveedor — vacío si nunca se tocó."""
    return agent_provider_config.obtener(_instance, proveedor_id)


class ProviderConfigBody(BaseModel):
    notas: str = ""


@router.put("/agent/providers/{proveedor_id}/config")
def put_agent_provider_config(proveedor_id: str, body: ProviderConfigBody):
    return agent_provider_config.guardar(_instance, proveedor_id, body.notas)


# ── Herramientas siempre permitidas (una lista, toda la instalación) ─────


class AllowedToolsBody(BaseModel):
    value: str


@router.get("/agent/allowed-tools")
def get_agent_allowed_tools():
    """La lista de `--allowedTools` que se auto-aprueba en toda sesión nueva."""
    return {"allowed_tools": agent_settings.allowed_tools(_instance)}


@router.put("/agent/allowed-tools")
def put_agent_allowed_tools(body: AllowedToolsBody):
    """Reemplaza la lista entera — la pantalla de Configuración manda el texto completo, no un diff."""
    if not _ALLOWED_TOOLS_RE.match(body.value):
        raise HTTPException(
            422,
            "Caracteres no permitidos — sólo nombres de tool, coma/espacio y un "
            'patrón entre paréntesis, ej. "Bash(git *)".',
        )
    return {"allowed_tools": agent_settings.fijar_allowed_tools(_instance, body.value)}


# Un nombre de tool suelto, sin el patrón entre paréntesis que sí acepta el
# textbox de Configuración — es lo único que un botón "Permitir siempre" arma
# solo, a partir de `tool_name` de un evento `permission_denied`.
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,100}$")


@router.post("/agent/allowed-tools/{tool}")
def post_agent_allowed_tool(tool: str):
    """
    Suma una tool a la lista si no estaba. Para un patrón más fino
    (`Bash(git *)`) hay que escribirlo a mano en Configuración.
    """
    if not _TOOL_NAME_RE.match(tool):
        raise HTTPException(422, f"Nombre de tool inválido: {tool!r}")
    return {"allowed_tools": agent_settings.agregar_tool_permitida(_instance, tool)}


# Lo que `--allowedTools` documenta como sintaxis válida: nombres de tool,
# opcionalmente con un patrón entre paréntesis (`Bash(git *)`), separados por
# coma o espacio. Nada de `;`, `&`, `|` ni comillas: esto termina en el argv
# de un subprocess que en Windows corre con `shell=True` (ver `agent_terminal.py`).
_ALLOWED_TOOLS_RE = re.compile(r"^[A-Za-z0-9_,\s*().:/-]{0,300}$")


@router.websocket("/agent/terminal")
async def agent_terminal_ws(
    websocket: WebSocket, provider: str, mode: str = "login", actor: str = "agente-mcp", paquete: str = "",
):
    """
    La terminal embebida del wizard: instala un proveedor o lo loguea.

    El argv que corre sale siempre de `agent_providers` — el cliente sólo
    elige *cuál* proveedor y *cuál* de los dos modos, nunca un comando propio.

    Si es un login y `actor` ya se había logueado antes desde otra máquina, se
    manda un aviso por texto antes de arrancar el proceso — no se bloquea: ver
    issue #11 para la preocupación de fondo y por qué, hoy, esto sólo avisa.
    """
    await websocket.accept()

    prov = agent_providers.proveedor(provider)
    if prov is None or mode not in ("login", "install"):
        await websocket.send_text(json.dumps({
            "error": f"proveedor o modo inválido: provider={provider!r} mode={mode!r}",
        }))
        await websocket.close(code=1008)
        return
    if mode == "login" and not agent_sessions.coincide_con_esta_maquina(_instance, actor):
        anterior = agent_sessions.sesion_de(_instance, actor)
        await websocket.send_text(json.dumps({
            "aviso": (
                f"'{actor}' ya se había logueado en {prov.label} desde "
                f"'{anterior['hostname']}'. Esta máquina es distinta "
                f"('{agent_sessions.hostname_actual()}') — puede hacer falta "
                "volver a autenticar."
            ),
        }))

    # El login con el binario resuelto: recién instalado por el vendor, el PATH
    # de este proceso todavía no lo tiene (ver agent_providers.ruta_del_binario).
    if prov.id == "manual" and mode == "install":
        # "Manual / otro" instala cualquier CLI por su id de winget. El id lo
        # valida agent_providers; acá sólo se decide qué decirle al navegador.
        try:
            argv = list(agent_providers.comando_winget_paquete(paquete))
        except ValueError as exc:
            await websocket.send_text(json.dumps({"error": str(exc)}))
            await websocket.close(code=1008)
            return
    else:
        argv = list(prov.instalar if mode == "install" else agent_providers.comando_login(prov))
    if not argv:
        await websocket.send_text(json.dumps({"error": f"{prov.label} no tiene un comando de {mode}."}))
        await websocket.close(code=1008)
        return
    sesion = TerminalSession(argv, cwd=str(ROOT))
    sesion.iniciar()

    async def bombear_salida() -> None:
        """Termina cuando el proceso da EOF — el otro lado de la sesión murió."""
        loop = asyncio.get_event_loop()
        while True:
            datos = await loop.run_in_executor(None, sesion.leer)
            if not datos:
                return
            await websocket.send_bytes(datos)

    async def recibir_del_cliente() -> None:
        """Termina cuando el navegador cierra la pestaña o la conexión."""
        try:
            while True:
                mensaje = await websocket.receive()
                if mensaje["type"] == "websocket.disconnect":
                    return
                if mensaje.get("bytes") is not None:
                    sesion.escribir(mensaje["bytes"])
                elif mensaje.get("text") is not None:
                    try:
                        control = json.loads(mensaje["text"])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(control.get("resize"), dict):
                        sesion.resize(
                            int(control["resize"].get("rows", 24)),
                            int(control["resize"].get("cols", 80)),
                        )
        except WebSocketDisconnect:
            return

    # Lo que termine primero —el proceso (EOF) o el cliente (desconexión)—
    # cierra la sesión entera. Sin esto, el lado que sigue vivo deja la
    # conexión colgada esperando algo que ya no va a llegar.
    tarea_salida = asyncio.create_task(bombear_salida())
    tarea_entrada = asyncio.create_task(recibir_del_cliente())
    try:
        await asyncio.wait(
            {tarea_salida, tarea_entrada}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        tarea_salida.cancel()
        tarea_entrada.cancel()
        exito_proceso = sesion.exit_code == 0
        sesion.terminar()

        if exito_proceso and mode == "login":
            agent_sessions.registrar_login(_instance, actor, prov.id)

        # El auto-registro corre tanto para "install" como para "login": lo
        # único que hace falta para escribir la conexión es que el proceso
        # haya salido bien, no que haya sido específicamente un login (`agy
        # mcp add`, por ejemplo, no necesita estar logueado para funcionar).
        # Se manda el aviso ANTES de cerrar el socket — después, el cliente ya
        # no está para leerlo.
        if exito_proceso and prov.auto_registro:
            aviso_registro = mcp_registration.registrar(prov.id, ROOT, _conexion_mcp())
            if aviso_registro:
                try:
                    await websocket.send_text(json.dumps({"aviso": aviso_registro}))
                except RuntimeError:
                    pass  # el cliente ya había cerrado su lado

        try:
            await websocket.close(code=1000)
        except RuntimeError:
            pass  # el cliente ya había cerrado su lado


# ── Resources de los plugins (ABM genérico) ─────────────────────────────


def _resource(plugin_name: str, resource_name: str):
    plugin = next((p for p in _instance.registry.plugins if p.name == plugin_name), None)
    if plugin is None or plugin.manifest is None:
        raise HTTPException(404, f"No hay un plugin '{plugin_name}' con manifest")
    resource = plugin.manifest.resource(resource_name)
    if resource is None:
        raise HTTPException(404, f"El plugin '{plugin_name}' no declara '{resource_name}'")
    return resource


def _store(plugin_name: str, resource_name: str):
    """
    Store de una colección. Ya no puede fallar por configuración.

    Antes esto devolvía 400 si el `dir_setting` del resource no estaba puesto:
    no se podía crear una conexión hasta elegir en qué carpeta guardarla. Con la
    tabla, una instalación nueva guarda desde el primer minuto.
    """
    return _instance.resource_store(plugin_name, _resource(plugin_name, resource_name))


@router.get("/resources/{plugin}/{resource}")
def list_resource(plugin: str, resource: str):
    """Items de una colección que administra un plugin (conexiones, comandos…)."""
    definicion = _resource(plugin, resource)
    return {"resource": definicion.to_dict(), "items": _store(plugin, resource).list_items()}


@router.get("/resources/{plugin}/{resource}/{key}")
def get_resource_item(plugin: str, resource: str, key: str):
    try:
        return _store(plugin, resource).read(key)
    except ResourceError as exc:
        raise HTTPException(404, str(exc)) from None


class ResourceItem(BaseModel):
    item: dict


@router.put("/resources/{plugin}/{resource}/{key}")
def put_resource_item(plugin: str, resource: str, key: str, body: ResourceItem):
    """Crea o actualiza un item, validado contra el esquema del resource."""
    try:
        return _store(plugin, resource).write(key, body.item)
    except ResourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/resources/{plugin}/{resource}/{key}")
def delete_resource_item(plugin: str, resource: str, key: str):
    try:
        _store(plugin, resource).delete(key)
        return {"ok": True}
    except ResourceError as exc:
        raise HTTPException(404, str(exc)) from None


# ── Workflows ───────────────────────────────────────────────────────────


@router.get("/workflows")
def list_workflows():
    return _instance.list_workflows()


@router.get("/workflows/{name}")
def get_workflow(name: str):
    """El flujo con su contenido, para el editor."""
    wf = _instance.workflows.get(name)
    if wf is None:
        raise HTTPException(404, f'No existe el flujo "{name}"')
    return wf.to_dict()


class WorkflowBody(BaseModel):
    content: str
    folder: str = ""
    state: str = "enabled"
    description: str = ""


@router.put("/workflows/{name}")
def put_workflow(name: str, body: WorkflowBody):
    """
    Crea o actualiza un flujo.

    Devuelve además sus diagnósticos: guardar un flujo roto está permitido —se
    guarda a medias mientras se escribe—, pero el editor tiene que poder decirlo
    en el momento y no cuando alguien lo ejecute.
    """
    try:
        wf = _instance.workflows.save(
            name,
            content=body.content,
            folder=body.folder,
            state=body.state,
            description=body.description,
        )
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None

    graph, extra = _instance.diagnose(name)
    diagnosticos = list(graph.diagnostics) + extra
    return {
        "workflow": wf.to_dict(),
        "runnable": graph.runnable and not any(d.severity.value == "error" for d in extra),
        "diagnostics": [d.to_dict() for d in diagnosticos],
    }


class GraphBody(BaseModel):
    """El grafo con la forma que devuelve `GET /workflows/{name}/graph`."""

    nodes: dict = {}
    edges: list = []
    start_node: str | None = None
    meta: dict = {}


class ContentBody(BaseModel):
    content: str


@router.post("/flow/parse")
def parse_flow_text(body: ContentBody):
    """
    Texto Mermaid → grafo, sin guardar nada.

    Es lo que el editor de texto llama al soltar el foco: dibuja el diagrama y
    lista los diagnósticos de un flujo que todavía no existe en la base. Sin
    esto habría que guardar para poder ver, y guardar a medias mientras se
    escribe deja el flujo roto para cualquiera que lo ejecute en el medio.
    """
    grafo = parse_flow(body.content, with_meta=True)
    return {"graph": grafo.to_dict(), "problems": serializer.verificar(grafo)}


@router.post("/flow/serialize")
def serialize_flow(body: GraphBody):
    """
    Grafo → texto Mermaid. Es lo que usa el editor de tarjetas para guardar.

    Existe para que **la gramática viva en un solo lugar**. El ayudante de la app
    vieja generaba el texto en JavaScript, unía los parámetros con coma —que al
    parsear también los separa— y guardaba flujos partidos en silencio. Acá el
    mismo módulo que parsea es el que escribe.

    `problems` lista lo que no sobreviviría a volver a leerse. Se devuelve junto
    con el texto en vez de fallar: el editor lo muestra mientras se escribe, y
    quien guarda decide.
    """
    grafo = serializer.from_dict(body.model_dump())
    return {
        # Sin cabecera `%%`: la carpeta, el estado y la descripción viajan en el
        # PUT y viven en columnas. Ver el docstring de `to_mermaid`.
        "content": serializer.to_mermaid(grafo),
        "meta": grafo.meta.to_dict(),
        "problems": serializer.verificar(grafo),
    }


@router.delete("/workflows/{name}")
def delete_workflow(name: str):
    try:
        if not _instance.workflows.delete(name):
            raise HTTPException(404, f'No existe el flujo "{name}"')
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}


@router.get("/workflows/{name}/graph")
def get_workflow_graph(name: str):
    """
    El grafo tal como lo entiende el motor, con sus diagnósticos.

    Es lo que necesita el editor para señalar errores por línea, y lo que le
    permite a un agente corregir un flujo sin ejecutarlo.
    """
    try:
        graph, extra = _instance.diagnose(name)
    except WorkflowNotFound as exc:
        raise HTTPException(404, str(exc)) from None

    datos = graph.to_dict()
    # Los diagnósticos del parser más los que dependen de qué hay instalado: un
    # tool que no existe es un error del flujo aunque el texto parsee bien.
    datos["diagnostics"] += [d.to_dict() for d in extra]
    datos["runnable"] = graph.runnable and not any(d.severity.value == "error" for d in extra)
    return datos


# ── Validación y ejecución ──────────────────────────────────────────────


class RunBody(BaseModel):
    flow: str
    case_id: str
    row: dict = {}
    source: str = ""
    # Quién ejecuta. Vacío = el actor por defecto del arranque (boot.env). No es
    # autenticación —nadie prueba ser quien dice—: es qué política aplica el
    # núcleo a la corrida y a quién queda atribuida. Sirve para probar un flujo
    # "como agente" antes de dárselo a uno.
    actor: str | None = None


@router.post("/validate")
async def validate(body: RunBody):
    """
    Revisa un flujo sin ejecutarlo: parseo, tools que existan, params que
    resuelvan, y qué configuración falta.

    Es el dry-run: resuelve todas las variables y no toca nada.
    """
    try:
        graph, extra = _instance.diagnose(body.flow)
    except WorkflowNotFound as exc:
        raise HTTPException(404, str(exc)) from None

    diagnosticos = [d.to_dict() for d in list(graph.diagnostics) + extra]
    ejecutable = graph.runnable and not any(d.severity.value == "error" for d in extra)

    faltantes = {
        plugin: [m.to_dict() for m in pendientes]
        for plugin, pendientes in _instance.missing_config_for(body.flow).items()
    }

    if not ejecutable:
        return {
            "runnable": False,
            "diagnostics": diagnosticos,
            "missing_config": faltantes,
            "run": None,
        }

    try:
        resultado = await run_in_threadpool(
            _instance.run, body.flow, body.case_id, row=body.row, dry_run=True, actor=body.actor
        )
    except UserError as exc:
        raise HTTPException(403, str(exc)) from None
    return {
        "runnable": resultado.status == "ok",
        "diagnostics": diagnosticos,
        "missing_config": faltantes,
        "run": resultado.to_dict(),
    }


@router.post("/run")
async def run_flow(body: RunBody):
    """
    Ejecuta un flujo del lado del servidor.

    Bloquea hasta terminar; el run sobrevive igual al cierre del navegador,
    porque el motor ya no vive en la pestaña. La traza queda guardada aunque el
    cliente se desconecte.

    Pasa por `_gate`: si el flujo declara que necesita correr solo (issue #8,
    todavía no en esta rama), espera a que no quede ningún otro run en vuelo y
    bloquea a los nuevos mientras dura. Hasta que esa declaración exista, todo
    corre concurrente — ver `run_with_gate`.
    """
    # Un flujo con errores de diagnóstico —un tool que no está instalado, un
    # nodo sin salida— no se ejecuta. El núcleo sí lo correría: el nodo falla y
    # sigue por la arista |err|, y el run termina "ok" con el trabajo sin
    # hacer. Eso es un error de configuración, no una falla de runtime, y se
    # frena antes de tocar nada; el dry run ya lo muestra.
    try:
        _, extra = _instance.diagnose(body.flow)
    except WorkflowNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    errores = [d.message for d in extra if d.severity.value == "error"]
    if errores:
        raise HTTPException(409, {
            "message": f'El flujo "{body.flow}" tiene errores y no se ejecuta hasta corregirlos.',
            "errors": errores,
        })

    try:
        resultado = await run_with_gate(
            _instance, _gate, body.flow, body.case_id, en_vuelo=_en_vuelo,
            row=body.row, source=body.source, actor=body.actor,
        )
    except WorkflowNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except UserError as exc:
        # El actor no existe, está deshabilitado o no puede con algún nodo. El
        # mensaje del núcleo ya dice cuál y por qué.
        raise HTTPException(403, str(exc)) from None
    return resultado.to_dict()


# ── Acciones de un plugin (botón + formulario + resultado) ──────────────
#
# Genérico: sirve para la Action de cualquier plugin, no sólo `connections`
# (`preview`, `test`) — es lo mismo que ya prueba `probar conexión` en el
# plugin de referencia. La UI la dibuja sola desde `Action.to_dict()`, que ya
# viaja en `GET /tools`.


class ActionBody(BaseModel):
    params: dict = {}
    # Opcional: la clave de un item guardado de la colección que declara la
    # acción; el núcleo arma los params desde ahí y `params` pisa campo a campo.
    item: str | None = None


@router.post("/actions/{plugin}/{action}")
async def run_plugin_action(plugin: str, action: str, body: ActionBody):
    """
    Ejecuta la Action de un plugin. No es parte de ningún run: la dispara una
    persona desde la pantalla del plugin, y aun así vuelve como `ToolResult`.
    """
    # Por nombre: el núcleo v0.3 hizo keyword-only a `params` e `item`, y la
    # llamada posicional rompía con TypeError toda Action — la grilla de
    # Sources no podía ni previsualizar una fuente.
    resultado, registro = await run_in_threadpool(
        lambda: _instance.run_action(plugin, action, params=body.params, item=body.item)
    )
    return {
        "result": resultado.to_dict(),
        "log": [{"message": mensaje, "level": nivel} for mensaje, nivel in registro],
    }


# ── Fuentes de datos ─────────────────────────────────────────────────────
#
# El mecanismo viejo (`SourceKind` por plugin, `_instance.sources`) se sacó
# entero con el núcleo que lo traía: ninguno de estos atributos existe en el
# `Instance` actual. Lo que reemplaza a "fuente de datos" es el resource
# `sources` del plugin `connections` (`webapp/connections/plugin.py`) — grilla
# + ejecución por fila, con paginación externa opcional en su propio schema.
#
# Todavía no hay endpoints para eso a propósito: la grilla y el "ejecutar por
# fila / en tanda" son la parte de UI que falta diseñar, y antes de escribir
# rutas para eso hace falta saber qué pantalla las va a consumir. El ABM del
# resource ya funciona hoy por la vía genérica (`/resources/connections/
# sources/...`), y probar un source antes de guardarlo por
# `POST /actions/connections/preview`.


# ── Historial ───────────────────────────────────────────────────────────


@router.get("/runs")
def list_runs(
    case_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    only_failed: bool = Query(default=False),
    source: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    include_dry: bool = Query(default=True),
):
    """Historial, del más reciente al más viejo. Sin la traza."""
    # Por nombre, no por posición: el núcleo v0.3 metió `actor` en el medio de
    # la firma y la llamada posicional mandaba `include_dry` como actor — la
    # lista volvía vacía con la tabla llena, y sin un solo error.
    filas = _instance.runs.list(
        case_id=case_id, limit=limit, only_failed=only_failed, source=source,
        actor=actor, include_dry=include_dry,
    )
    return [r.to_dict() for r in filas]


@router.get("/runs/en-vuelo")
def list_runs_en_vuelo():
    """
    Los runs que están corriendo ahora, con cuánto llevan y —cuando el núcleo
    lo cuente— en qué paso van. Es lo que la grilla dibuja como barra en la
    columna Log mientras `POST /run` no volvió. Va antes de `/runs/{run_id}`
    a propósito: si no, "en-vuelo" se leería como un id.
    """
    return _en_vuelo.listar()


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    """
    Un run con su traza completa.

    Cada nodo con sus params **ya resueltos**, status, outputs, duración y
    traceback. Es lo que responde "por qué falló": no sirve saber que el nodo
    pedía {filesFolder}, sino a qué ruta se resolvió esa vez.
    """
    datos = _instance.run_detail(run_id)
    if datos is None:
        raise HTTPException(404, f"No existe el run '{run_id}'")
    return datos


# ── Registro de eventos por fila ────────────────────────────────────────


@router.get("/logs/{case_id}")
def get_case_log(case_id: str, limit: int = Query(500, ge=1, le=5000)):
    """
    Todo el registro de una fila de una fuente, run tras run.

    Es lo que abre el botón **Log** de la grilla. Se acumula por fila y no por
    run a propósito: cuando alguien mira una fila que viene fallando, lo que
    necesita es la historia completa de esa fila, no la de la última corrida.

    Viene del más viejo al más nuevo. Con `limit` se recortan las **primeras**
    líneas y no las últimas: cuando algo falla, lo que hay que leer es el final.
    """
    return _instance.case_log(case_id, limit=limit)


@router.delete("/logs/{case_id}")
def clear_case_log(case_id: str):
    """
    Limpia el registro de una fila. Es el botón "Limpiar" del modal.

    Borra el log, **no los runs**: el historial de ejecuciones es append-only y
    sigue ahí con su traza. Lo que se limpia es la narración acumulada, que es
    lo que alguien quiere resetear cuando arranca de nuevo con un caso.
    """
    return {"case_id": case_id, "deleted": _instance.logs.clear_case(case_id)}

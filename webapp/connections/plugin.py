"""
Plugin `connections` — propio de esta webapp, no de terceros.

Resuelve dos necesidades distintas, y por eso son dos `Resource` separados en
vez de uno solo:

- **sources**: de dónde sale la grilla del panel principal. Trae una lista y
  de ahí salen las filas, la clave de cada una (`case_id`) y las columnas.
  Nunca es un nodo de un flujo — lo lee la webapp para dibujar la tabla y para
  disparar `Instance.run(row=fila)` por fila o en tanda.
- **actions**: una llamada HTTP guardada que un nodo de un flujo dispara para
  traer un dato puntual y seguir el flujo con eso — el caso de
  `Legacy/connections/*.json` (consultar un id externo, marcar un estado).
  Es la única de las dos que expone un Tool.

Por qué vive bajo `webapp/` y no como plugin instalado por entry point: es un
default de esta aplicación, no algo que un tercero deba poder instalar u
omitir. Aun así respeta el contrato entero — manifest, ports declarados,
`ToolResult`, nunca importa una librería fuera de lo que el port permite— así
que el catálogo, el registry y la política de actores lo tratan exactamente
igual que a cualquier otro plugin.

Paginación de un source: por defecto se trae la fuente entera y se pagina en
memoria (el mismo mecanismo que ya usa un CSV cargado entero). Sólo si el
source declara `page_param` se le pide página por página a la API externa —
es la salida para cuando traer todo de una vez no da abasto. Las dos cosas
conviven en el mismo schema; se elige una según lo que ese source necesite,
nunca las dos a la vez.

Tipos de source: hoy sólo `http`. Un origen de archivos (CSV, etc.) es un
módulo aparte a propósito — no contamina este.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from backend.core import ports as port_names
from backend.core.contract import (
    Action,
    Field,
    FunctionAction,
    FunctionTool,
    Output,
    Param,
    ParamType,
    Plugin,
    PluginManifest,
    Resource,
    Setting,
    ToolContext,
    ToolManifest,
    ToolResult,
)

# ── Resources ─────────────────────────────────────────────────────────────

_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

SOURCES = Resource(
    name="sources",
    label="Sources",
    item_label="Source",
    key_field="name",
    doc=(
        "Fuente de datos para la grilla del panel principal: trae una lista, y "
        "de ahí salen las filas, la clave de caso y las columnas."
    ),
    fields=(
        Field(
            "kind", ParamType.ENUM, label="Tipo", default="http", choices=("http",),
            doc="Por ahora sólo 'http'. Un origen de archivos es un módulo aparte.",
        ),
        Field("url", ParamType.STR, label="URL", required=True),
        Field("method", ParamType.ENUM, label="Método", default="GET", choices=_HTTP_METHODS),
        Field("headers", ParamType.JSON, label="Headers", default={}),
        Field("payload", ParamType.JSON, label="Payload", default={}),
        Field(
            "results_path", ParamType.STR, label="Camino al array",
            doc="Ej. 'data.items'. Vacío si la raíz de la respuesta ya es la lista.",
        ),
        Field(
            "key_field", ParamType.STR, label="Campo clave", required=True,
            doc="Qué campo de cada fila identifica el caso (case_id) para el bot.",
        ),
        Field("default_flow", ParamType.STR, label="Flujo por defecto"),
        # Paginación externa — opcional. Vacío = se trae todo y se pagina en
        # memoria, igual que un CSV cargado entero.
        Field(
            "page_param", ParamType.STR, label="Parámetro de página",
            doc="Nombre del query param de página en la API. Vacío = sin paginación externa.",
        ),
        Field("page_size_param", ParamType.STR, label="Parámetro de tamaño de página"),
        Field("page_size", ParamType.INT, label="Filas por página", default=100),
        Field(
            "total_path", ParamType.STR, label="Camino al total",
            doc="Ej. 'data.total'. Para saber cuándo dejar de pedir páginas.",
        ),
    ),
)

ACTIONS = Resource(
    name="actions",
    label="Actions",
    item_label="Action",
    key_field="name",
    doc=(
        "Llamada HTTP guardada que un nodo de un flujo dispara para traer un dato "
        "puntual y seguir con eso — no alimenta la grilla."
    ),
    fields=(
        Field("url", ParamType.STR, label="URL", required=True),
        Field("method", ParamType.ENUM, label="Método", default="GET", choices=_HTTP_METHODS),
        Field("headers", ParamType.JSON, label="Headers", default={}),
        Field("payload", ParamType.JSON, label="Payload", default={}),
        Field(
            "results_path", ParamType.STR, label="Camino al resultado",
            doc="Opcional: qué parte de la respuesta guardar en {result}.",
        ),
    ),
)


# ── Helpers de HTTP, propios del plugin ────────────────────────────────────


def _dig(obj, path: str):
    """Recorre un camino con puntos ('data.items') dentro de dicts/listas."""
    if not path:
        return obj
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.lstrip("-").isdigit():
            idx = int(part)
            current = current[idx] if -len(current) <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _con_query(url: str, params: dict) -> str:
    """Agrega/pisa query params sin tocar el resto de la URL."""
    partes = urlparse(url)
    query = dict(parse_qsl(partes.query))
    query.update({k: str(v) for k, v in params.items()})
    return urlunparse(partes._replace(query=urlencode(query)))


def _cuerpo(payload) -> str | None:
    if not payload:
        return None
    return json.dumps(payload)


def _headers_con_json(headers: dict, cuerpo: str | None) -> dict:
    headers = dict(headers or {})
    if cuerpo is not None and not any(h.lower() == "content-type" for h in headers):
        headers["Content-Type"] = "application/json"
    return headers


def _pedir(http, cfg: dict, *, timeout: float):
    """Un request HTTP a partir de un schema de source/action ya resuelto."""
    cuerpo = _cuerpo(cfg.get("payload"))
    return http.request(
        cfg["url"],
        method=cfg.get("method") or "GET",
        headers=_headers_con_json(cfg.get("headers") or {}, cuerpo),
        body=cuerpo,
        timeout=timeout,
    )


def _coincide(fila, termino: str) -> bool:
    termino = termino.lower()
    if not isinstance(fila, dict):
        return termino in str(fila).lower()
    return any(termino in str(v).lower() for v in fila.values())


def _coincide_filtros(fila, filtros: dict) -> bool:
    if not isinstance(fila, dict):
        return False
    return all(str(fila.get(campo)) == str(valor) for campo, valor in filtros.items())


# Por encima de esto una columna no es para filtrar por igualdad — un id o un
# texto libre tiene un valor casi distinto por fila, y el desplegable
# terminaría siendo la lista entera de la fuente en vez de una ayuda.
_MAX_VALORES_FACETA = 50


def _facetas(filas: list) -> dict:
    """Valores únicos por columna, para poblar el desplegable de cada filtro."""
    valores: dict[str, set] = {}
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        for campo, valor in fila.items():
            valores.setdefault(campo, set()).add(str(valor))
    return {
        campo: sorted(vs) for campo, vs in valores.items()
        if 0 < len(vs) <= _MAX_VALORES_FACETA
    }


def _fetch_page(
    http, cfg: dict, *, offset: int, limit: int, timeout: float,
    search: str | None = None, filters: dict | None = None,
) -> dict:
    """
    Trae una página de filas de un source.

    Con `page_param` declarado, le pide sólo esa página a la API externa. Sin
    eso, trae la fuente entera de una vez y corta/pagina en memoria — el mismo
    mecanismo que ya usa un CSV cargado entero (ver `webapp/static/js/views/
    sources.js`, que hace lo mismo del lado de la vista).

    `search` filtra por substring en cualquier valor de la fila; `filters` es
    por columna, igualdad exacta (el desplegable de cada columna). Sin
    paginación externa filtran la fuente entera antes de cortar la página —
    una búsqueda de verdad. Con paginación externa sólo pueden filtrar la
    página que ya se trajo: pedirle "todas las páginas" a una API ajena para
    poder buscar arruina la razón de tener `page_param`. La vista no promete lo
    que esto no puede cumplir (ver `webapp/static/js/views/sources.js`).

    `facets` (valores únicos por columna, para esos mismos desplegables) sale
    de las filas que ya pasaron `search` pero no `filters`: así elegir un valor
    en una columna no le achica las opciones a las demás.
    """
    externa = bool(cfg.get("page_param"))
    peticion = dict(cfg)

    if externa:
        tam = int(cfg.get("page_size") or limit or 100)
        pagina = offset // tam + 1
        params = {cfg["page_param"]: pagina}
        if cfg.get("page_size_param"):
            params[cfg["page_size_param"]] = tam
        peticion["url"] = _con_query(cfg["url"], params)

    respuesta = _pedir(http, peticion, timeout=timeout)
    if not respuesta.ok:
        return {"error": f"la fuente respondió {respuesta.status}", "rows": [], "total": 0, "facets": {}}

    cuerpo = respuesta.json(default=None)
    filas = _dig(cuerpo, cfg.get("results_path") or "")
    if filas is None:
        filas = cuerpo if isinstance(cuerpo, list) else None
    if not isinstance(filas, list):
        return {
            "error": "la respuesta no es una lista de filas (revisá 'camino al array')",
            "rows": [], "total": 0, "facets": {},
        }

    if search:
        filas = [f for f in filas if _coincide(f, search)]
    facetas = _facetas(filas)
    if filters:
        filas = [f for f in filas if _coincide_filtros(f, filters)]

    total = _dig(cuerpo, cfg.get("total_path") or "")
    if not externa:
        # Sin paginación externa: ya está todo acá. Filtra, cuenta y recién
        # ahí pagina en memoria — el filtro tiene que mirar la fuente entera,
        # no la página que ya se había cortado.
        total = len(filas)
        if limit:
            filas = filas[offset: offset + limit]
    elif not isinstance(total, int):
        total = offset + len(filas)

    return {"error": None, "rows": filas, "total": total, "facets": facetas}


_PATRON_VAR = re.compile(r"\{(\w+)\}")


def _resolver(valor, obtener):
    """
    Sustituye `{campo}` en url/headers/payload contra `obtener(nombre)`.

    Recursivo porque el payload guardado es JSON libre — la referencia puede
    estar en la URL, en un header o anidada en el cuerpo. Lo que no resuelve
    queda literal, igual que el resto del motor: mejor un `{id_externo}` visible
    en la traza que un `None` silencioso.

    `obtener` es cualquier callable `(nombre) -> valor | None`, no un
    `ToolContext`: en un run es `ctx.var`, contra el contexto real; probando
    una Action antes de guardarla es un dict a mano que arma quien prueba —
    ahí no hay run, ni caso, ni contexto de donde sacar nada.
    """

    def _uno(m: re.Match) -> str:
        val = obtener(m.group(1))
        return str(val) if val is not None else m.group(0)

    def _mapear(v):
        if isinstance(v, str):
            return _PATRON_VAR.sub(_uno, v)
        if isinstance(v, dict):
            return {k: _mapear(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_mapear(x) for x in v]
        return v

    return _mapear(valor)


# ── Tool: connections.llamar — el único nodo de flujo de este plugin ──────

LLAMAR = ToolManifest(
    id="connections.llamar",
    label="llamar conexión",
    category="CONNECTIONS",
    doc=(
        "Ejecuta una Action guardada en Connections. Sustituye {variables} en "
        "la URL, headers y payload contra cualquier otro param del propio "
        "nodo primero (para pisar un campo con un literal distinto por nodo, "
        "ej. un 'texto' de comentario) y si no contra el contexto del run; "
        "deja la respuesta en {response} y, si la Action declara 'camino al "
        "resultado', también en {result}."
    ),
    params=(Param("connection", required=True, doc="Nombre de la Action guardada."),),
    extra_params=True,
    extra_params_doc="Cualquier otro param pisa al {variable} de mismo nombre en la Action, antes que el contexto del run.",
    outputs=(
        Output("response", ParamType.JSON),
        Output("status", ParamType.INT),
        Output("result", ParamType.JSON),
    ),
)


def _ejecutar_guardada(ctx: ToolContext, nombre: str):
    """
    Lo que comparten `llamar` y `llamar_y_fusionar`: buscar la Action, pegarle
    y devolver (guardada, respuesta, cuerpo_resp, resultado) — o un
    `ToolResult` de error si algo de eso falla, para que el caller lo
    propague tal cual.
    """
    guardada = ctx.resource("actions", nombre)
    if guardada is None:
        disponibles = ", ".join(ctx.resource_keys("actions")) or "ninguna"
        return ToolResult.err(f"no existe la conexión '{nombre}'. Disponibles: {disponibles}")

    # Un extra del propio nodo (`texto=...` en el .mmd) pisa a la variable de
    # mismo nombre del contexto del run: es lo que permite compartir una sola
    # Action guardada entre varios nodos que mandan un texto distinto cada uno.
    resuelta = _resolver(
        {"url": guardada["url"], "headers": guardada.get("headers") or {},
         "payload": guardada.get("payload") or {}},
        lambda nombre: ctx.extras.get(nombre, ctx.var(nombre)),
    )
    cuerpo = _cuerpo(resuelta["payload"])
    respuesta = ctx.port(port_names.HTTP).request(
        resuelta["url"],
        method=guardada.get("method") or "GET",
        headers=_headers_con_json(resuelta["headers"], cuerpo),
        body=cuerpo,
        timeout=float(ctx.config("connectionsTimeout") or 30.0),
    )
    ctx.log(f"{guardada.get('method', 'GET')} {resuelta['url']} → {respuesta.status}")
    cuerpo_resp = respuesta.json(default=respuesta.text)
    resultado = _dig(cuerpo_resp, guardada.get("results_path") or "")
    return guardada, respuesta, cuerpo_resp, resultado


def _llamar(ctx: ToolContext) -> ToolResult:
    nombre = ctx.params["connection"]
    ejecutada = _ejecutar_guardada(ctx, nombre)
    if isinstance(ejecutada, ToolResult):
        return ejecutada
    _guardada, respuesta, cuerpo_resp, resultado = ejecutada

    if not respuesta.ok:
        return ToolResult.err(
            f"la conexión '{nombre}' respondió {respuesta.status}",
            status=respuesta.status, response=cuerpo_resp,
        )
    return ToolResult.ok(response=cuerpo_resp, status=respuesta.status, result=resultado)


# ── Tool: connections.llamar_y_fusionar ────────────────────────────────────
#
# Distinto de `llamar` a propósito, no un flag más: además de {response},
# {status} y {result}, vuelca cada campo de primer nivel de la respuesta
# directo al contexto del run — así un nodo más adelante puede leer {pais} o
# {tratamiento_intranet} sin un segundo tool que los saque de {response}. Es
# lo que un flujo necesita para "traer la fila de nuevo y seguir con sus
# datos al día". El precio es real —puede pisar cualquier variable del
# contexto con el mismo nombre que un campo de la respuesta— así que es un
# tool aparte, con un nombre que lo dice, no un default silencioso.

FUSIONAR = ToolManifest(
    id="connections.llamar_y_fusionar",
    label="llamar y fusionar al contexto",
    category="CONNECTIONS",
    doc=(
        "Como 'llamar conexión', pero además vuelca cada campo de primer nivel "
        "de la respuesta al contexto del run (pisa cualquier variable con el "
        "mismo nombre). Para cuando un nodo más adelante necesita leer un "
        "campo de la fila recién traída directo por su nombre."
    ),
    params=(Param("connection", required=True, doc="Nombre de la Action guardada."),),
    extra_params=True,
    extra_params_doc="Cualquier otro param pisa al {variable} de mismo nombre en la Action, antes que el contexto del run.",
    outputs=(
        Output("response", ParamType.JSON),
        Output("status", ParamType.INT),
        Output("result", ParamType.JSON),
    ),
    extra_outputs=True,
    extra_outputs_doc="Cada campo de primer nivel de la respuesta, si es un objeto JSON.",
)


def _llamar_y_fusionar(ctx: ToolContext) -> ToolResult:
    nombre = ctx.params["connection"]
    ejecutada = _ejecutar_guardada(ctx, nombre)
    if isinstance(ejecutada, ToolResult):
        return ejecutada
    _guardada, respuesta, cuerpo_resp, resultado = ejecutada

    if not respuesta.ok:
        return ToolResult.err(
            f"la conexión '{nombre}' respondió {respuesta.status}",
            status=respuesta.status, response=cuerpo_resp,
        )
    extra = cuerpo_resp if isinstance(cuerpo_resp, dict) else {}
    return ToolResult.ok(response=cuerpo_resp, status=respuesta.status, result=resultado, **extra)


# ── Actions: probar, sin wizard ────────────────────────────────────────────

PREVIEW = Action(
    "preview",
    "Probar",
    doc="Trae filas sin guardar nada — arma y probá un source antes de guardarlo.",
    # Atada a la colección: un agente por MCP la pide con `item=<fuente>` y los
    # params salen del item guardado, en vez de reconstruirlos a mano.
    resource="sources",
    params=(
        Param("url", required=True),
        Param("method", default="GET"),
        Param("headers", ParamType.JSON, default={}),
        Param("payload", ParamType.JSON, default={}),
        Param("results_path"),
        Param("page_param"),
        Param("page_size_param"),
        Param("page_size", ParamType.INT, default=100),
        Param("total_path"),
        Param("limit", ParamType.INT, default=25),
        Param("offset", ParamType.INT, default=0),
        Param("search", doc="Filtra por substring en cualquier valor de la fila."),
        Param(
            "filters", ParamType.JSON, default={},
            doc="Filtra por igualdad exacta, columna por columna: {'campo': 'valor'}.",
        ),
    ),
)


def _preview(ctx: ToolContext) -> ToolResult:
    resultado = _fetch_page(
        ctx.port(port_names.HTTP), ctx.params,
        offset=ctx.params.get("offset") or 0,
        limit=ctx.params.get("limit") or 25,
        timeout=float(ctx.config("connectionsTimeout") or 30.0),
        search=ctx.params.get("search") or None,
        filters=ctx.params.get("filters") or None,
    )
    if resultado["error"]:
        return ToolResult.err(resultado["error"])
    return ToolResult.ok(rows=resultado["rows"], total=resultado["total"], facets=resultado["facets"])


TEST = Action(
    "test",
    "Probar conexión",
    doc="Ejecuta la conexión guardada tal cual y muestra la respuesta.",
    params=(Param("connection", required=True),),
    resource="actions",
)


def _test(ctx: ToolContext) -> ToolResult:
    nombre = ctx.params["connection"]
    guardada = ctx.resource("actions", nombre)
    if guardada is None:
        return ToolResult.err(f"no existe la conexión '{nombre}'")

    respuesta = _pedir(
        ctx.port(port_names.HTTP), guardada,
        timeout=float(ctx.config("connectionsTimeout") or 30.0),
    )
    cuerpo_resp = respuesta.json(default=respuesta.text)
    if not respuesta.ok:
        return ToolResult.err(f"respondió {respuesta.status}", status=respuesta.status, response=cuerpo_resp)
    return ToolResult.ok(f"respondió {respuesta.status}", status=respuesta.status, response=cuerpo_resp)


PROBAR_LLAMADA = Action(
    "probar_llamada",
    "Probar",
    doc=(
        "Ejecuta la llamada tal cual está en el formulario, sin guardar nada. "
        "Si la URL, los headers o el payload traen {variables} —como las "
        "resuelve `connections.llamar` en un run real—, se sustituyen contra "
        "'Variables para probar'; lo que no se declara ahí queda literal."
    ),
    params=(
        Param("url", required=True),
        Param("method", default="GET"),
        Param("headers", ParamType.JSON, default={}),
        Param("payload", ParamType.JSON, default={}),
        Param("results_path"),
        Param(
            "vars", ParamType.JSON, default={},
            doc="Valores para reemplazar los {llaves} de la URL, headers o payload al probar. No se guardan.",
        ),
    ),
)


def _probar_llamada(ctx: ToolContext) -> ToolResult:
    variables = ctx.params.get("vars") or {}
    resuelta = _resolver(
        {"url": ctx.params["url"], "headers": ctx.params.get("headers") or {},
         "payload": ctx.params.get("payload") or {}},
        variables.get,
    )
    cuerpo = _cuerpo(resuelta["payload"])
    respuesta = ctx.port(port_names.HTTP).request(
        resuelta["url"],
        method=ctx.params.get("method") or "GET",
        headers=_headers_con_json(resuelta["headers"], cuerpo),
        body=cuerpo,
        timeout=float(ctx.config("connectionsTimeout") or 30.0),
    )
    cuerpo_resp = respuesta.json(default=respuesta.text)
    resultado = _dig(cuerpo_resp, ctx.params.get("results_path") or "")

    if not respuesta.ok:
        return ToolResult.err(f"respondió {respuesta.status}", status=respuesta.status, response=cuerpo_resp)
    return ToolResult.ok(
        f"respondió {respuesta.status}", status=respuesta.status, response=cuerpo_resp, result=resultado,
    )


# ── Manifest y armado ───────────────────────────────────────────────────

MANIFEST = PluginManifest(
    name="connections",
    label="Connections",
    version="0.1.0",
    doc=(
        "Sources (grilla + ejecución por fila) y Actions (llamada HTTP guardada "
        "para usar dentro de un flujo). Plugin propio de esta webapp."
    ),
    ports=(port_names.HTTP,),
    settings=(
        Setting("connectionsTimeout", ParamType.FLOAT, label="Timeout (s)", default=30.0),
    ),
    resources=(SOURCES, ACTIONS),
    actions=(PREVIEW, TEST, PROBAR_LLAMADA),
)


def build_plugin() -> Plugin:
    return Plugin(
        manifest=MANIFEST,
        tools=[
            FunctionTool(manifest=LLAMAR, fn=_llamar),
            FunctionTool(manifest=FUSIONAR, fn=_llamar_y_fusionar),
        ],
        actions=[
            FunctionAction(action=PREVIEW, fn=_preview),
            FunctionAction(action=TEST, fn=_test),
            FunctionAction(action=PROBAR_LLAMADA, fn=_probar_llamada),
        ],
    )


PLUGIN = build_plugin()

__all__ = ["MANIFEST", "PLUGIN", "build_plugin", "SOURCES", "ACTIONS"]

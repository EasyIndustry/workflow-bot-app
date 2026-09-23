"""
Un plugin de mentira con Actions de fila que devuelven `outputs.indicador` y
`outputs.abrir_url`.

Existe por lo mismo que `plugin_con_secreto.py`: sin un plugin real que declare
esto —hoy ninguno del repo lo hace— no hay contra qué probar que `webapp/
indicadores.py` guarda el indicador y `GET /resources/...` lo suma a cada item
como `_indicador`, ni contra qué probar que `plugins.js` abre una pestaña
cuando una Action devuelve `abrir_url`.

`probar` devuelve `ok` o `err` según el campo `falla` del item, para poder
probar los dos casos guardando dos items distintos en vez de mockear nada.
`abrir` devuelve una URL fija — no hace falta que sirva nada de verdad, sólo
que `plugins.js` la abra.
"""

from __future__ import annotations

from backend.core.contract import (
    Action,
    Field,
    FunctionAction,
    Param,
    ParamType,
    Plugin,
    PluginManifest,
    Resource,
    ToolContext,
    ToolResult,
)

CONEXIONES = Resource(
    name="conexiones",
    label="Conexiones",
    item_label="Conexión",
    key_field="nombre",
    fields=(
        Field("nombre", ParamType.STR, label="Nombre", required=True),
        Field("falla", ParamType.BOOL, label="Falla"),
    ),
)

PROBAR = Action(
    "probar",
    "Probar",
    params=(Param("nombre", required=True),),
    resource="conexiones",
)


def _probar(ctx: ToolContext) -> ToolResult:
    item = ctx.resource("conexiones", ctx.params["nombre"], key_field="nombre")
    if item and item.get("falla"):
        return ToolResult.err("no contestó", indicador={"estado": "err", "texto": "no contestó"})
    return ToolResult.ok("contestó", indicador={"estado": "ok", "texto": "contestó"})


ABRIR = Action(
    "abrir",
    "Abrir en pestaña",
    params=(Param("nombre", required=True),),
    resource="conexiones",
)


def _abrir(ctx: ToolContext) -> ToolResult:
    # En un plugin real es la URL guardada del otro Bot; acá alcanza con que
    # tenga forma de URL http(s) — nada la visita de verdad en el test.
    nombre = ctx.params["nombre"]
    return ToolResult.ok(abrir_url=f"http://127.0.0.1:19999/?bot={nombre}")


MANIFEST = PluginManifest(
    name="conexiones_test",
    label="Conexiones de prueba",
    version="0.0.1",
    doc="Sólo para tests: Actions de fila que devuelven outputs.indicador y outputs.abrir_url.",
    resources=(CONEXIONES,),
    actions=(PROBAR, ABRIR),
)

PLUGIN = Plugin(manifest=MANIFEST, actions=[
    FunctionAction(action=PROBAR, fn=_probar),
    FunctionAction(action=ABRIR, fn=_abrir),
])

__all__ = ["CONEXIONES", "MANIFEST", "PLUGIN"]

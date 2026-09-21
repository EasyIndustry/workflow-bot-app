"""
Un plugin de mentira con una Action suelta que devuelve `outputs.vista`.

Para probar el dibujo de una vista declarada sin depender de que el plugin
`bots` del catálogo esté listo. Imita lo que va a mandar `bots.comparar`: una
tabla con estados, filas que no se pueden elegir, una nota por fila, y una
acción de seguimiento que recibe lo tildado más el contexto fijo.

Sirve además como la especificación ejecutable del contrato: si alguien cambia
el renderer y esto deja de dibujarse, el contrato se rompió.
"""

from __future__ import annotations

from backend.core.contract import (
    Action, FunctionAction, Param, ParamType, Plugin, PluginManifest, ToolResult,
)

COMPARAR = Action(
    name="comparar",
    label="Comparar con el otro Bot",
    doc="Trae qué difiere y deja elegir qué mandar. Ejemplo del contrato de `vista`.",
    params=(
        Param("destino", ParamType.STR, required=True, doc="Contra quién comparar."),
    ),
)

MIGRAR = Action(
    name="migrar",
    label="Migrar lo elegido",
    doc="Escribe en el otro Bot lo que se haya tildado.",
    dangerous=True,
    params=(
        Param("destino", ParamType.STR, required=True),
        Param("claves", ParamType.JSON, required=True),
    ),
)


def _comparar(ctx) -> ToolResult:
    destino = ctx.params["destino"]
    filas = [
        {"clave": "alta de caso", "estado": "distinto", "campos": "content, folder"},
        {"clave": "cierre", "estado": "solo_origen", "campos": ""},
        {"clave": "QA viejo", "estado": "igual", "campos": "", "_elegible": False},
        {"clave": "conexión SAP", "estado": "indeterminado", "campos": "",
         "_nota": "tiene campos secretos: no se puede saber si difiere"},
    ]
    return ToolResult.ok(
        vista={
            "tipo": "tabla",
            "clave": "clave",
            "titulo": f"4 cosas comparadas contra {destino}.",
            "columnas": [
                {"campo": "clave", "label": "Nombre"},
                {"campo": "estado", "label": "Estado", "ancho": "130px"},
                {"campo": "campos", "label": "Qué difiere"},
            ],
            "filas": filas,
            "seleccion": {
                "accion": "migrar",
                "param": "claves",
                "params": {"destino": destino},
                "etiqueta": "Migrar lo elegido",
                "aviso": "Migrar pisa lo que haya del otro lado. Los secretos no se pueden "
                         "comparar: se pisan a ciegas.",
            },
        },
    )


def _migrar(ctx) -> ToolResult:
    claves = ctx.params.get("claves") or []
    destino = ctx.params["destino"]
    return ToolResult.ok(
        message=f"Se migraron {len(claves)} a {destino}.",
        vista={
            "tipo": "tabla",
            "clave": "clave",
            "columnas": [{"campo": "clave", "label": "Nombre"},
                         {"campo": "resultado", "label": "Resultado"}],
            "filas": [{"clave": c, "resultado": "migrado"} for c in claves],
        },
    )


MANIFEST = PluginManifest(
    name="vista_demo",
    label="Vista de prueba",
    version="0.0.1",
    doc="Sólo para probar el dibujo de `outputs.vista`.",
    actions=(COMPARAR, MIGRAR),
)

PLUGIN = Plugin(
    manifest=MANIFEST,
    actions=[FunctionAction(action=COMPARAR, fn=_comparar),
             FunctionAction(action=MIGRAR, fn=_migrar)],
)

__all__ = ["COMPARAR", "MANIFEST", "MIGRAR", "PLUGIN"]

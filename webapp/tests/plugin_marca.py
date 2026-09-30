"""
Un plugin de mentira con un solo tool que deja su param como salida.

Existe para probar la decisión manual (core#37) de punta a punta contra el
núcleo real: hace falta un flujo sin errores de diagnóstico, con nodos antes y
después de la decisión, para ver que se pausa, que los de después no corren y
que al retomar corre sólo la rama elegida con el contexto de antes.
"""

from __future__ import annotations

from backend.core.contract import (
    FunctionTool,
    Output,
    Param,
    ParamType,
    Plugin,
    PluginManifest,
    ToolContext,
    ToolManifest,
    ToolResult,
)


def _marcar(ctx: ToolContext) -> ToolResult:
    return ToolResult.ok(visto=ctx.params["x"])


PLUGIN = Plugin(
    manifest=PluginManifest(name="marca", label="Marca", version="1.0.0"),
    tools=[
        FunctionTool(
            manifest=ToolManifest(
                id="marca.poner", label="Poner marca", category="TEST",
                doc="Deja el valor de x como salida {visto}.",
                params=(Param("x", ParamType.STR, required=True),),
                outputs=(Output("visto", ParamType.STR),),
            ),
            fn=_marcar,
        ),
    ],
)

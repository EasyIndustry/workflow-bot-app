"""
El servidor MCP de una instalación: `python -m webapp.mcp_servidor`.

Es `backend.mcp` con dos datos que el núcleo no puede saber solo y que un
agente no debería tener que adivinar en cada llamada:

- **La instalación.** Las tools del núcleo toman `root` por llamada y, sin
  él, operan sobre `backend/` — el checkout, no la carpeta que eligió el
  wizard. Acá `root` cae por defecto a la instalación que resuelve
  `webapp.ubicacion` (la que "Abrir Bot" está sirviendo: `BOT_ROOT` viaja en
  el `env` de la receta).
- **Los plugins de la app.** `connections` no está en `plugins/`: lo trae la
  webapp como plugin local (`webapp.connections`). El núcleo escanea la
  carpeta y no lo ve, así que `check_flow` sobre cualquier flujo con una
  Action decía "No hay ningún tool connections.llamar", y el agente iba a
  "arreglar" un flujo que estaba bien. Acá se pasa como `--plugin` en cada
  operación que acepte `plugins`, debajo de los que mande el agente.

No reimplementa nada: usa `TOOLS`, `call_tool` y el transporte de
`backend.mcp.server`, y sólo completa los argumentos antes de despachar.
Lo que el núcleo pueda incorporar de esto (plugins y root por defecto, por
env o flag) es el issue #16 de workflow-bot-core; cuando llegue, este módulo
queda en un `main()` que pasa esos dos datos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import mcp.types as types  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from backend.mcp import server as nucleo  # noqa: E402
from webapp import ubicacion  # noqa: E402

# Los plugins que la webapp registra como locales, con la ruta que entiende
# `backend.core --plugin NOMBRE=RUTA`. Tiene que decir lo mismo que
# `webapp/server.py` al armar la Instance.
PLUGINS_DE_LA_APP: dict[str, str] = {"connections": str(REPO / "webapp" / "connections")}


def completar(nombre: str, argumentos: dict | None, *, root: str, plugins: dict[str, str]) -> dict:
    """
    Los argumentos con `root` y `plugins` puestos si la tool los acepta.

    Lo que mandó el agente gana: un `root` explícito se respeta, y un plugin
    suyo con el mismo nombre que uno de la app pisa al de la app — es la forma
    de probar una versión propia de `connections` sin instalarla.
    """
    tool = next((t for t in nucleo.TOOLS if t.name == nombre), None)
    if tool is None:
        return dict(argumentos or {})
    propiedades = (tool.input_schema or {}).get("properties", {})
    completados = dict(argumentos or {})
    if "root" in propiedades and not completados.get("root"):
        completados["root"] = root
    if "plugins" in propiedades:
        completados["plugins"] = {**plugins, **(completados.get("plugins") or {})}
    return completados


def build_server(root: str, plugins: dict[str, str]) -> Server:
    async def on_list_tools(_ctx, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=nucleo.TOOLS)

    async def on_call_tool(_ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        return nucleo.call_tool(params.name, completar(params.name, params.arguments, root=root, plugins=plugins))

    return Server(
        "bot-workflows",
        version="0.1.0",
        title="Motor de workflows",
        instructions=nucleo.INSTRUCCIONES
        + f"\n\nEsta sesión opera la instalación {root}: `root` ya va puesto en cada tool "
        "si no se pasa otro, y los plugins de la app (connections) ya están cargados.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve(root: str, plugins: dict[str, str]) -> None:
    servidor = build_server(root, plugins)
    async with stdio_server() as (lectura, escritura):
        await servidor.run(lectura, escritura, servidor.create_initialization_options())


def main() -> int:
    import anyio

    root = ubicacion.resolver_root(REPO, os.environ.get("BOT_ROOT"))
    anyio.run(serve, str(root), PLUGINS_DE_LA_APP)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
El servidor MCP de una instalación: `python -m webapp.mcp_servidor`.

Es `backend.mcp` con lo que el núcleo no puede saber solo y un agente no
debería tener que adivinar:

- **La instalación** (`default_root`): la que "Abrir Bot" está sirviendo,
  resuelta por `webapp.ubicacion` a partir de `BOT_ROOT`, que viaja en el
  `env` de la receta. Sin esto cada tool operaría sobre `backend/`, el
  checkout.
- **Los plugins de la app** (`default_plugins`): `connections` y
  `conocimiento` no están en `plugins/`, los registra la webapp como
  locales. El núcleo escanea la carpeta y no los ve, así que `check_flow`
  sobre un flujo con una Action decía "No hay ningún tool connections.llamar".
- **Lo que sólo esta app conoce**, por la puerta que el núcleo abrió para eso
  (`instructions_extra`, `extra_tools`, `extra_handlers`; workflow-bot-core
  #16 y #17):
  - `describe_installation` **enriquecido**: el del núcleo más las fuentes
    de `connections` y las notas de `conocimiento` (`contexto_agente`).
  - `preview_source`: las filas de una fuente guardada, tal como las ve la
    grilla. Es una Action de un plugin de la app; el núcleo no la conoce.
  - `write_resource_item` / `delete_resource_item` envueltos para regenerar
    el `AGENTS.md` de la instalación después de escribir: una nota o una
    fuente nueva son parte de su resumen.

No reimplementa nada del núcleo: `nucleo.build_server` completa `root` y
`plugins` en cada llamada y despacha; acá sólo se le pasan los defaults y
los extras. La `Instance` propia se abre en la primera tool extra que la
necesite, no al arrancar: las tools del núcleo van por subproceso y no la
usan.
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

from backend.mcp import operations  # noqa: E402
from backend.mcp import server as nucleo  # noqa: E402
from webapp import contexto_agente, ubicacion  # noqa: E402

# Los plugins que la webapp registra como locales, con la ruta que entiende
# `backend.core --plugin NOMBRE=RUTA`. Tiene que decir lo mismo que
# `routes/core_api.py` (LOCAL_PLUGINS) al armar la Instance.
PLUGINS_DE_LA_APP: dict[str, str] = {
    "connections": str(REPO / "webapp" / "connections"),
    "conocimiento": str(REPO / "webapp" / "conocimiento"),
}
# Los mismos, en la forma `modulo:objeto` que toma `Instance(local_plugins=)`.
LOCAL_PLUGINS: dict[str, str] = {
    "connections": "webapp.connections.plugin:PLUGIN",
    "conocimiento": "webapp.conocimiento.plugin:PLUGIN",
}

INSTRUCCIONES_EXTRA = """\
Esta sesión opera una instalación concreta: `root` ya va puesto en cada tool si
no se pasa otro, y los plugins de la app (connections, conocimiento) ya están
cargados.

Propio de esta instalación:

  - `describe_installation` trae además `fuentes` (las de connections, con su
    campo clave y su flujo por defecto) y `notas` (lo que dejó escrito quien
    opera en conocimiento/notas). Leerlo primero.
  - ¿Qué datos tiene una fuente? -> preview_source (nombre de la fuente).
  - Aprendiste algo de esta instalación que no está escrito -> write_resource_item
    con plugin=conocimiento, resource=notas, key=<tema>, item={tema, texto, origen: "agente"}.

Los datos se consultan por acá, nunca abriendo data/bot.db.\
"""

_PLUGINS_ARG = {
    "type": "object",
    "description": "Plugins locales {nombre: ruta}; los de la app ya van puestos.",
    "additionalProperties": {"type": "string"},
}
_ROOT_ARG = {"type": "string", "description": "Directorio de la instalación; ya va puesto."}

PREVIEW_SOURCE = types.Tool(
    name="preview_source",
    description=(
        "Filas de una fuente guardada (connections/sources), tal como las ve la grilla: columnas, "
        "clave de caso y total. No guarda ni ejecuta nada. Los nombres están en describe_installation.fuentes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nombre de la fuente."},
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 200},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
            "search": {"type": "string", "description": "Substring en cualquier columna."},
            "filters": {
                "type": "object", "description": "Igualdad exacta por columna: {\"campo\": \"valor\"}.",
                "additionalProperties": {"type": "string"},
            },
            "root": _ROOT_ARG,
        },
        "required": ["name"],
    },
)

EXTRA_TOOLS: list[types.Tool] = [PREVIEW_SOURCE]


class Extras:
    """
    Los handlers propios, sobre una `Instance` de la instalación abierta en
    la primera llamada. Cada método tiene la firma que el esquema de su tool
    declara —con `root`/`plugins` cuando el núcleo los completa— porque
    `call_tool` los llama con los argumentos tal cual llegan.
    """

    def __init__(self, root: str, local_plugins: dict[str, str] | None = None) -> None:
        self.root = root
        self.local_plugins = local_plugins or LOCAL_PLUGINS
        self._instance = None

    @property
    def instance(self):
        if self._instance is None:
            from backend.core.instance import Instance
            self._instance = Instance(self.root, local_plugins=self.local_plugins)
        return self._instance

    def handlers(self) -> dict:
        return {
            "describe_installation": self.describe_installation,
            "preview_source": self.preview_source,
            "write_resource_item": self.write_resource_item,
            "delete_resource_item": self.delete_resource_item,
        }

    def describe_installation(self, plugins: dict | None = None, root: str | None = None) -> dict:
        # Contra otra raíz que la propia, el del núcleo tal cual: la Instance
        # de acá es la de esta instalación.
        if root and Path(root) != Path(self.root):
            return operations.describe_installation(plugins=plugins, root=root)
        return contexto_agente.describir(self.instance)

    def preview_source(self, name: str, limit: int = 10, offset: int = 0, search: str | None = None,
                       filters: dict | None = None, root: str | None = None) -> dict:
        # Por `item`, no reconstruyendo url/headers acá: es la misma acción que
        # usa la grilla, con los params saliendo de la fuente guardada.
        resultado, registro = self.instance.run_action(
            "connections", "preview", item=name,
            params={"limit": max(1, min(int(limit), 200)), "offset": max(0, int(offset)),
                    "search": search or None, "filters": filters or {}},
        )
        return {"result": resultado.to_dict(),
                "log": [{"message": mensaje, "level": nivel} for mensaje, nivel in registro]}

    def write_resource_item(self, plugin: str, resource: str, key: str, item: dict,
                            plugins: dict | None = None, root: str | None = None) -> dict:
        escrito = operations.write_resource_item(plugin, resource, key, item, plugins=plugins, root=root)
        self._manual_cambio(root)
        return escrito

    def delete_resource_item(self, plugin: str, resource: str, key: str,
                             plugins: dict | None = None, root: str | None = None) -> dict:
        borrado = operations.delete_resource_item(plugin, resource, key, plugins=plugins, root=root)
        self._manual_cambio(root)
        return borrado

    def _manual_cambio(self, root: str | None) -> None:
        # El AGENTS.md lleva el resumen de la instalación; una nota nueva o una
        # fuente nueva son parte de ese resumen. Sólo para la propia.
        if root and Path(root) != Path(self.root):
            return
        contexto_agente.regenerar(self.instance, Path(self.root))


def build_server(root: str, plugins: dict[str, str], *, local_plugins: dict[str, str] | None = None) -> Server:
    extras = Extras(root, local_plugins)
    return nucleo.build_server(
        default_root=root,
        default_plugins=plugins,
        instructions_extra=INSTRUCCIONES_EXTRA,
        extra_tools=EXTRA_TOOLS,
        extra_handlers=extras.handlers(),
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

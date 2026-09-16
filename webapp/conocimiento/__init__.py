"""
Plugin local `conocimiento`: notas sobre la instalación, para el agente y para quien opera.

`PLUGIN` se exporta acá porque el núcleo carga este paquete de dos formas: la
webapp por `webapp.conocimiento.plugin:PLUGIN`, y las tools del MCP —que van
por subproceso— por la carpeta (`--plugin conocimiento=<ruta>`), donde el
registry busca `PLUGIN` en el módulo raíz. Sin esto, cada llamada por MCP
traía "No se pudo cargar el plugin local conocimiento" en `_stderr`.
"""

from .plugin import MANIFEST, NOTAS, PLUGIN, build_plugin

__all__ = ["MANIFEST", "NOTAS", "PLUGIN", "build_plugin"]

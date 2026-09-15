

# `PLUGIN` a nivel de paquete: es lo que busca `--plugin connections=webapp/connections`
# (la CLI y el MCP importan `connections:PLUGIN`). Sin esto, un agente por MCP
# no podía cargar el plugin de la webapp y con eso tampoco ver sus fuentes.
from .plugin import PLUGIN  # noqa: E402,F401

__all__ = ["PLUGIN"]

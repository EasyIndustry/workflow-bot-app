"""
Configuración del agente que vive en la instalación, no en una sesión puntual.

Hoy sólo `allowed_tools` — la lista de `--allowedTools` que se auto-aprueba en
**toda** sesión nueva. Esto es una política que se va construyendo con el
tiempo — "aprobá Bash una vez, no me lo vuelvas a preguntar nunca más en esta
instalación"— y por eso tiene una sola fila, compartida por toda sesión futura.

Vive en `plugin_items` como `agent_sessions.py` — bookkeeping de la propia
webapp, no un resource que un flujo vaya a leer.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Resource
from backend.core.instance import Instance
from backend.core.resources import ResourceError

RESOURCE = Resource(
    name="agente_config",
    label="Configuración del agente",
    item_label="Ajuste",
    key_field="clave",
    doc="Ajustes del agente que valen para toda sesión nueva, no una en particular.",
    fields=(Field("value", ParamType.STR, label="Valor"),),
)

_CLAVE_ALLOWED_TOOLS = "allowed_tools"


def _store(instance: Instance):
    return instance.resource_store("agente", RESOURCE)


def allowed_tools(instance: Instance) -> str:
    """La lista de `--allowedTools` que se auto-aprueba en toda sesión nueva. Vacía si no se configuró nada."""
    try:
        return _store(instance).read(_CLAVE_ALLOWED_TOOLS).get("value", "")
    except ResourceError:
        return ""


def fijar_allowed_tools(instance: Instance, valor: str) -> str:
    """Reemplaza la lista entera. Devuelve el valor guardado, ya recortado."""
    valor = valor.strip()
    _store(instance).write(_CLAVE_ALLOWED_TOOLS, {"value": valor})
    return valor


def agregar_tool_permitida(instance: Instance, tool: str) -> str:
    """
    Suma una tool a la lista si todavía no estaba — es lo que dispara el botón
    "Permitir siempre" de una burbuja de permiso denegado. Comparación por
    nombre exacto: no intenta fusionar `Bash` con `Bash(git *)`, cada patrón
    que ya esté se deja tal cual.
    """
    actuales = [t.strip() for t in allowed_tools(instance).split(",") if t.strip()]
    tool = tool.strip()
    if tool and tool not in actuales:
        actuales.append(tool)
    return fijar_allowed_tools(instance, ", ".join(actuales))


__all__ = [
    "RESOURCE",
    "agregar_tool_permitida",
    "allowed_tools",
    "fijar_allowed_tools",
]

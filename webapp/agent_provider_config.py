"""
Configuración particular de cada proveedor de CLI (notas, skills, lo que
haga falta guardar por proveedor) — no una en particular de una sesión, sino
de la instalación, igual que `agent_settings.py`.

Vive en `plugin_items` como `agent_sessions.py`/`agent_settings.py`:
bookkeeping de la propia webapp, no un resource que un flujo vaya a leer. Es
key-value por proveedor a propósito —`Field("notas", ...)` es el único campo
hoy— para poder sumar más adelante (un modelo elegido, un endpoint de IA
local para "manual", etc.) sin migrar nada: cada fila ya es un dict libre por
`proveedor_id`.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Resource
from backend.core.instance import Instance
from backend.core.resources import ResourceError

RESOURCE = Resource(
    name="agente_proveedor_config",
    label="Configuración de proveedor",
    item_label="Proveedor",
    key_field="proveedor_id",
    doc="Notas y ajustes propios de un proveedor de CLI — no de una sesión en particular.",
    fields=(
        Field(
            "notas", ParamType.STR, label="Notas / skills",
            doc="Libre: qué modelo usar, qué sabe hacer, cualquier recordatorio para vos.",
        ),
    ),
)


def _store(instance: Instance):
    return instance.resource_store("agente", RESOURCE)


def obtener(instance: Instance, proveedor_id: str) -> dict:
    """`{"notas": "..."}`, o vacío si todavía no se guardó nada para este proveedor."""
    try:
        return _store(instance).read(proveedor_id)
    except ResourceError:
        return {"notas": ""}


def guardar(instance: Instance, proveedor_id: str, notas: str) -> dict:
    item = {"notas": notas.strip()}
    _store(instance).write(proveedor_id, item)
    return item


__all__ = ["RESOURCE", "guardar", "obtener"]

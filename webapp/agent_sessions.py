"""
Quién logueó qué proveedor, desde qué máquina.

Vive en `plugin_items` como cualquier colección de un plugin —vía
`Instance.resource_store`— pero sin registrar un plugin de verdad: es
bookkeeping de la propia webapp, no algo que un flujo vaya a leer con
`ctx.resource(...)`. El "actor" es la clave: hoy sólo existe `agente-mcp`
(ver `backend/mcp/operations.py:run_flow`), pero la tabla ya soporta más de
uno el día que haga falta.

`hostname` y no la IP: una IP puede renovarse sin que la máquina cambie, y lo
que importa acá es si la máquina cambió. Ver issue #11 para la preocupación de
fondo — esto **detecta** un login previo desde otra máquina, no lo impide; a
quien mira la terminal le llega como aviso, no como bloqueo.
"""

from __future__ import annotations

import socket
import time

from backend.core.contract import Field, ParamType, Resource
from backend.core.instance import Instance
from backend.core.resources import ResourceError

RESOURCE = Resource(
    name="sesiones_agente",
    label="Sesiones de agente",
    item_label="Sesión",
    key_field="actor",
    doc="Qué proveedor logueó cada actor-agente, y desde qué máquina.",
    fields=(
        Field("provider", ParamType.STR, label="Proveedor", required=True),
        Field("hostname", ParamType.STR, label="Máquina", required=True),
        Field("logged_in_at", ParamType.FLOAT, label="Último login"),
    ),
)


def hostname_actual() -> str:
    return socket.gethostname()


def _store(instance: Instance):
    return instance.resource_store("agente", RESOURCE)


def registrar_login(instance: Instance, actor: str, provider: str) -> dict:
    """Guarda (o reemplaza) que `actor` logueó `provider` desde esta máquina."""
    return _store(instance).write(
        actor,
        {"provider": provider, "hostname": hostname_actual(), "logged_in_at": time.time()},
    )


def sesion_de(instance: Instance, actor: str) -> dict | None:
    try:
        return _store(instance).read(actor)
    except ResourceError:
        return None


def coincide_con_esta_maquina(instance: Instance, actor: str) -> bool:
    """
    True si no hay sesión previa registrada (nada que comparar) o si la
    máquina coincide. False si `actor` se logueó antes desde otra distinta.
    """
    item = sesion_de(instance, actor)
    return item is None or item.get("hostname") == hostname_actual()


__all__ = [
    "RESOURCE",
    "coincide_con_esta_maquina",
    "hostname_actual",
    "registrar_login",
    "sesion_de",
]

"""
Un plugin de mentira con un campo `secret`, para los tests de #3.

Existe porque hoy **ningún** plugin real declara uno —ni el `connections` de la
app ni los del catálogo—, así que sin esto no hay contra qué probar que la API
tape lo que tiene que tapar. Justamente por eso el agujero de #3 estaba latente
y no abierto: lo abre el primer plugin que guarde un token en una colección en
vez de en `env`. Esto es ese plugin, adelantado.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Plugin, PluginManifest, Resource

CUENTAS = Resource(
    name="cuentas",
    label="Cuentas",
    item_label="Cuenta",
    key_field="name",
    fields=(
        Field("name", ParamType.STR, label="Nombre", required=True),
        Field("url", ParamType.STR, label="URL"),
        Field("token", ParamType.STR, label="Token", secret=True),
    ),
)

MANIFEST = PluginManifest(
    name="cuentas_test",
    label="Cuentas de prueba",
    version="0.0.1",
    doc="Sólo para tests: una colección con un campo secreto y uno que no lo es.",
    resources=(CUENTAS,),
)

PLUGIN = Plugin(manifest=MANIFEST)

__all__ = ["CUENTAS", "MANIFEST", "PLUGIN"]

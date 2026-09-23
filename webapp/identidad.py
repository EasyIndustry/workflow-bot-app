"""
Cómo se llama este Bot.

Con varios Bots abiertos en pestañas del mismo navegador, las pestañas eran
indistinguibles: todas dicen "Bot" y sólo se sabe cuál es cuál mirando la URL
o algo cargado en la pantalla. El nombre de la instalación resuelve eso: se
carga una vez (acá, Config → General) y `main.js` lo usa como título de la
pestaña en cuanto arranca — no hace falta ningún plugin para que esto
funcione, porque cada Bot se pone su propio título al abrirse, sea la pestaña
propia o una que otra máquina abrió con su IP.

El plugin `bots` (catálogo, no en este repo) conecta varios Bots por IP y ya
guarda un alias por conexión — el que la persona tipeó al darla de alta, en
su propia colección. Ese alias puede no coincidir con cómo el Bot remoto se
nombra a sí mismo, así que el plugin tiene acá, sin instalarse nada de su
lado, `GET /api/core/identidad` para leer el nombre que ese Bot eligió para
sí — la misma llamada directa entre Bots que ya usa `bots.probar`/`comparar`
(ver decisiones.md, "Bots que se hablan directo").

Vive en `resource_store("webapp", RESOURCE)`, el mismo mecanismo que
`webapp/updates.py` usa para el repo de cada componente: una colección del
núcleo dueña de la app y no de ningún plugin instalado, para que el dato
sobreviva sin depender de que haya uno.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Resource
from backend.core.resources import ResourceError

RESOURCE = Resource(
    name="identidad",
    label="Identidad",
    item_label="Ajuste",
    key_field="clave",
    doc="Cómo se llama esta instalación.",
    fields=(Field("value", ParamType.STR, label="Valor"),),
)

# La única fila que esta colección guarda hoy. Separado en una clave y no un
# campo suelto de `boot.env` porque `boot.env` son límites de la instalación
# (fs_root, process_allowlist) que impiden arrancar si están mal escritos; el
# nombre no es un límite, es un rótulo, y cambiarlo no debería pedir reiniciar.
CLAVE_NOMBRE = "nombre"


def _store(instance):
    return instance.resource_store("webapp", RESOURCE)


def nombre(instance) -> str:
    """El nombre guardado, o vacío si nunca se puso uno — no hay default inventado."""
    try:
        return (_store(instance).read(CLAVE_NOMBRE).get("value") or "").strip()
    except ResourceError:
        return ""


def guardar_nombre(instance, valor: str) -> str:
    """Guarda el nombre. Vacío borra la fila, para no dejar un "" dando vueltas."""
    valor = (valor or "").strip()
    store = _store(instance)
    if valor:
        store.write(CLAVE_NOMBRE, {"value": valor})
    else:
        try:
            store.delete(CLAVE_NOMBRE)
        except ResourceError:
            pass
    return valor

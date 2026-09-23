"""
El check persistente al lado de un item de colección.

Una Action de fila (`Action.resource`) puede devolver `outputs.indicador =
{"estado": "ok"|"err", "texto": "..."}`, en el éxito y en el error — por
ejemplo, "Probar conexión" del plugin `bots` dice si ese Bot contestó la
última vez que se lo intentó. Guardar eso en el servidor, no en el
navegador de quien apretó el botón, es lo mismo que ya decidió
`backend/core/config.py` para la configuración: sin eso, cada persona ve un
estado distinto según qué pestaña abrió, y se pierde al limpiar el
navegador.

**No vive en la fila del propio item** (`plugin_items` del plugin dueño de
la colección — "bots", acá). Dos motivos, no uno solo:

- `TableStore.write` descarta cualquier campo que empiece con `_` antes de
  guardar (`resources.py`, para que `_updated_at` no se confunda con algo
  que el plugin declaró) — así que ni un `_indicador` adentro del item se
  podría escribir por la vía normal, sólo con un `UPDATE` que esquivara la
  validación del resource del plugin.
- Aunque se pudiera, cambiar la forma de lo que guarda un plugin es tocar
  el contrato de ese plugin desde la app — lo mismo que `identidad.py` evita
  para el nombre del Bot.

Así que esto guarda en su propia colección, bajo `resource_store("webapp",
...)` — el mecanismo genérico del núcleo para que un item viva por fuera de
cualquier plugin instalado, el mismo que ya usan `identidad.py` y
`updates.py`. Una colección normal se identifica por `(org, plugin,
resource, key)`; acá el `plugin` siempre es "webapp", así que el plugin y
el resource *reales* del item (`bots`/`bots`, por ejemplo) van adentro de
la clave compuesta y del propio item, no en las columnas de scope.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Resource
from backend.core.resources import ResourceError

RESOURCE = Resource(
    name="indicadores",
    label="Indicadores",
    item_label="Indicador",
    key_field="clave",
    doc="El último resultado de una Action de fila, por item de una colección.",
    fields=(
        Field("plugin", ParamType.STR, label="Plugin"),
        Field("resource", ParamType.STR, label="Colección"),
        Field("item", ParamType.STR, label="Item"),
        Field("estado", ParamType.STR, label="Estado"),
        Field("texto", ParamType.STR, label="Texto"),
    ),
)

ESTADOS_VALIDOS = ("ok", "err")


def _store(instance):
    return instance.resource_store("webapp", RESOURCE)


def _clave(plugin: str, resource: str, item: str) -> str:
    # ":" no es válido en un `key` de plugin_items (`validate_key`), así que no
    # hay ambigüedad entre dónde termina el plugin y dónde empieza el resource
    # aunque alguno de los tres trajera el separador.
    return f"{plugin}:{resource}:{item}".replace(":", "_")


def guardar(instance, plugin: str, resource: str, item: str, estado: str, texto: str = "") -> dict:
    """Guarda el último resultado. Un estado que no es ok/err no se guarda: la Action no siguió el contrato."""
    if estado not in ESTADOS_VALIDOS:
        return {}
    return _store(instance).write(_clave(plugin, resource, item), {
        "plugin": plugin, "resource": resource, "item": item,
        "estado": estado, "texto": (texto or "").strip(),
    })


def borrar(instance, plugin: str, resource: str, item: str) -> None:
    """Al borrar el item, su indicador deja de tener sentido."""
    try:
        _store(instance).delete(_clave(plugin, resource, item))
    except ResourceError:
        pass  # no había indicador guardado: ya está como se lo quiere dejar


def de_coleccion(instance, plugin: str, resource: str) -> dict[str, dict]:
    """Los indicadores de una colección, por clave del item — para sumarlos al GET de esa colección."""
    salida: dict[str, dict] = {}
    try:
        filas = _store(instance).list_items()
    except ResourceError:
        return salida
    for fila in filas:
        if fila.get("plugin") != plugin or fila.get("resource") != resource:
            continue
        item = fila.get("item")
        if not item:
            continue
        salida[item] = {
            "estado": fila.get("estado"),
            "texto": fila.get("texto") or "",
            "updated_at": fila.get("_updated_at"),
        }
    return salida

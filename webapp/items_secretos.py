"""
La regla de los campos `secret` de un item de colección, en un solo lugar.

Vive acá y no adentro de un handler porque la usan dos caminos que tienen que
decidir **lo mismo**: la API de colecciones (`routes/core_api.py`) y el lado que
recibe una migración (`migracion.py`). Que un item escrito por un PUT y el mismo
item escrito por una migración conserven o borren su secreto según quién lo
escribió sería la peor clase de diferencia: invisible hasta que alguien pierde
un token.

Son dos mitades de una sola decisión, y por eso están juntas:

- `sin_secretos` tapa al leer (#3). Un secreto de una colección no sale por la
  API, ni siquiera para quien se sabe la clave.
- `con_los_secretos_guardados` conserva al escribir. Es la contracara: desde que
  se tapa al leer, quien edita devuelve `None`, y sin esto guardar el nombre de
  una conexión le borraría el token. `None` es "no me lo diste"; `""` lo vacía a
  propósito, que es lo que manda un campo de texto borrado a mano.
"""

from __future__ import annotations


def campos_secretos(definicion) -> set[str]:
    return {c.name for c in definicion.fields if c.secret}


def sin_secretos(definicion, item: dict) -> dict:
    """
    El item con cada campo `secret` en `None`.

    Mismo criterio que `Instance.resource_items_masked`, que es lo que el núcleo
    deja salir por MCP —su docstring dice "o cualquier otra API"—. Se repite acá
    porque el núcleo no tiene el equivalente para **un** item, y leer uno tiene
    que tapar igual que listar: si no, la regla se cumple a medias y alcanza con
    saberse la clave.
    """
    secretos = campos_secretos(definicion)
    if not secretos:
        return item
    return {clave: (None if clave in secretos else valor) for clave, valor in item.items()}


def con_los_secretos_guardados(definicion, store, key: str, item: dict) -> dict:
    """
    Un campo `secret` que llega en `None` conserva el valor que ya estaba.

    Vale para el PUT de la colección y para una migración: en los dos casos
    quien escribe puede no tener el secreto —porque lo leyó tapado, o porque se
    eligió no migrarlo— y en ninguno eso puede significar "borralo".
    """
    secretos = campos_secretos(definicion)
    faltantes = [c for c in secretos if item.get(c) is None]
    if not faltantes:
        return item
    try:
        anterior = store.read(key)
    except Exception:  # noqa: BLE001 — ResourceError vive en el núcleo
        return item  # Es nuevo: no hay nada que conservar.
    return {**item, **{c: anterior[c] for c in faltantes if anterior.get(c) is not None}}

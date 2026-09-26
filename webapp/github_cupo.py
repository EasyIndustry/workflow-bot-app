"""
Cuándo un 403 de GitHub no es un permiso sino el cupo de la API.

Sin token, la API de GitHub da 60 pedidos por hora por IP, y se agotan
fácil: la campana de releases, listar en Config → Actualizaciones, bajar un
par de tarballs, leer el catálogo de plugins. Cuando se acaban, GitHub
responde 403 (a veces 429) con `x-ratelimit-remaining: 0`. Los mensajes de
la app decían "si el repo es privado hace falta un token", que mandaba a
buscar un problema de permisos en un repo público, cuando alcanzaba con
esperar o con cargar un token (5000 por hora).

Lo usan `updates.py` y `plugin_catalog.py`, cada uno con su variable de token.
"""

from __future__ import annotations

import time


def cupo_agotado(codigo: int, cabeceras, token: str | None, variable: str) -> str | None:
    """
    La explicación si el error fue por cupo, o None si fue otra cosa.

    `cabeceras` es lo que trae el `HTTPError` (`exc.headers`); puede no estar.
    """
    if codigo not in (403, 429) or cabeceras is None:
        return None
    if cabeceras.get("x-ratelimit-remaining") != "0":
        return None
    cuando = ""
    try:
        cuando = " Se renueva a las " + time.strftime(
            "%H:%M", time.localtime(int(cabeceras.get("x-ratelimit-reset", "")))) + "."
    except (TypeError, ValueError):
        pass
    if token:
        return f"se agotó el cupo de la API de GitHub para este token.{cuando}"
    return (
        "se agotó el cupo de la API de GitHub sin token (60 pedidos por hora por IP). "
        f"Con {variable} en Config → Variables el cupo es de 5000.{cuando}"
    )


__all__ = ["cupo_agotado"]

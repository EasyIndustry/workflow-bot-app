"""
La vuelta del navegador a una Action (#12).

Una Action podía devolver `abrir_url` y la app abría esa pestaña, pero no
existía el camino de vuelta: cuando el sitio externo terminaba y redirigía
al Bot con datos en la URL (un código de autorización, el aviso de que una
firma o un pago terminó), nadie los recibía. Había que copiar la dirección
de la barra y pegarla en un campo, con un código que vence en minutos.

Es de la app y no sabe qué es OAuth ni ningún plugin: recibe una vuelta y
se la pasa a la Action que la pidió. Nada acá toca el núcleo.

El contrato para un plugin:

- La Action declara dos params, `url_de_vuelta` y `estado_de_vuelta`.
  Cuando corre desde la app (`POST /actions/...`), la app los completa: la
  URL estable `…/api/core/vuelta/<plugin>/<action>` (estable para que se
  pueda registrar una sola vez del otro lado) y un `state` de un solo uso.
- La Action manda esa URL como dirección de retorno y el `state` tal cual
  (en OAuth, `redirect_uri` y `state`), y devuelve `abrir_url`.
- En la vuelta, la app valida el `state` y corre **la misma Action** con los
  params de la query (sin el `state`), el item al que estaba atado, y otra
  vez `url_de_vuelta` (el canje de OAuth pide la misma). Después lleva al
  navegador a la pantalla del plugin con el resultado.

Seguridad: el `state` es aleatorio, vence (`VIGENCIA`), se usa una sola vez
y está atado a plugin, Action e item. Sin uno válido la vuelta se rechaza:
si no, cualquiera que conociera la URL dispararía la Action con los datos
que quisiera. Lo que llega en la query no se loguea (`TaparQueryDeVueltas`).
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass

PARAM_URL = "url_de_vuelta"
PARAM_ESTADO = "estado_de_vuelta"
# El nombre del `state` en la query de vuelta: el que usa OAuth y casi todo
# lo que redirige con un estado.
QUERY_ESTADO = "state"
VIGENCIA = 15 * 60
VIGENCIA_RESULTADO = 5 * 60


class VueltaError(Exception):
    """Una vuelta que no se acepta: sin state, vencido, usado o de otra Action."""


@dataclass
class _Emitido:
    plugin: str
    action: str
    item: str | None
    vence: float


class Vueltas:
    """Los `state` emitidos y los resultados que esperan a la pantalla. En memoria: viven minutos."""

    def __init__(self, reloj=time.time) -> None:
        self._reloj = reloj
        self._lock = threading.Lock()
        self._emitidos: dict[str, _Emitido] = {}
        self._resultados: dict[str, tuple[float, dict]] = {}

    def _limpiar(self, ahora: float) -> None:
        self._emitidos = {k: v for k, v in self._emitidos.items() if v.vence > ahora}
        self._resultados = {k: v for k, v in self._resultados.items() if v[0] > ahora}

    def emitir(self, plugin: str, action: str, item: str | None) -> str:
        ahora = self._reloj()
        estado = secrets.token_urlsafe(24)
        with self._lock:
            self._limpiar(ahora)
            self._emitidos[estado] = _Emitido(plugin, action, item, ahora + VIGENCIA)
        return estado

    def consumir(self, estado: str | None, plugin: str, action: str) -> str | None:
        """
        El item al que estaba atado, o `VueltaError`. Se borra antes de
        comparar: un `state` que llegó a otra Action tampoco vuelve a servir.
        """
        if not estado:
            raise VueltaError("La vuelta no trae el state que emitió el Bot.")
        with self._lock:
            self._limpiar(self._reloj())
            emitido = self._emitidos.pop(estado, None)
        if emitido is None:
            raise VueltaError("El state no es válido, ya se usó o venció. Volvé a apretar el botón.")
        if (emitido.plugin, emitido.action) != (plugin, action):
            raise VueltaError("El state es de otra acción.")
        return emitido.item

    def guardar_resultado(self, datos: dict) -> str:
        clave = secrets.token_urlsafe(12)
        with self._lock:
            self._limpiar(self._reloj())
            self._resultados[clave] = (self._reloj() + VIGENCIA_RESULTADO, datos)
        return clave

    def tomar_resultado(self, clave: str) -> dict | None:
        """Una sola vez: recargar la pantalla no repite el resultado."""
        with self._lock:
            par = self._resultados.pop(clave, None)
        return par[1] if par else None


def declara_vuelta(action) -> bool:
    """Si la Action pide la dirección de vuelta (declara `url_de_vuelta`)."""
    return any(p.name == PARAM_URL for p in (getattr(action, "params", None) or ()))


def url_de_vuelta(base: str, plugin: str, action: str) -> str:
    from urllib.parse import quote

    return f"{base.rstrip('/')}/api/core/vuelta/{quote(plugin, safe='')}/{quote(action, safe='')}"


# ── Que la query no quede en el log de accesos ──────────────────────────

_VUELTA_CON_QUERY = re.compile(r"(/api/core/vuelta/[^\s?\"]+)\?[^\s\"]*")


class TaparQueryDeVueltas(logging.Filter):
    """
    Uvicorn loguea cada request con su query entera: en una vuelta, eso es el
    código de autorización o lo que el sitio externo mande. Se reemplaza por
    `?…` en el registro; la ruta queda, para saber que la vuelta llegó.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(
                _VUELTA_CON_QUERY.sub(r"\1?…", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _VUELTA_CON_QUERY.sub(r"\1?…", record.msg)
        return True


def tapar_en_el_log() -> None:
    """Lo llama el arranque del servidor, cuando uvicorn ya configuró sus loggers."""
    for nombre in ("uvicorn.access", "uvicorn.error"):
        registro = logging.getLogger(nombre)
        if not any(isinstance(f, TaparQueryDeVueltas) for f in registro.filters):
            registro.addFilter(TaparQueryDeVueltas())


__all__ = [
    "PARAM_ESTADO", "PARAM_URL", "QUERY_ESTADO", "TaparQueryDeVueltas", "VueltaError", "Vueltas",
    "declara_vuelta", "tapar_en_el_log", "url_de_vuelta",
]

"""
Lector-escritor para arranques de runs concurrentes.

Nace de un caso real de Legacy: un plugin de automatización de escritorio
(una app de escritorio) usa el 100% de la CPU mientras corre y es sensible al timing de
`sendkeys` — si otro run cualquiera compite por CPU al mismo tiempo, falla. La
solución de Legacy fue cruda: ningún workflow arrancaba hasta que el anterior
terminara entero, siempre, aunque casi todos los pasos son fetches sin ningún
conflicto real.

Acá se separan las dos cosas. Un run normal es un **lector**: muchos corren
juntos. Un run que lo necesita es el **escritor**: espera a que no quede
ningún lector en vuelo, bloquea a los lectores nuevos mientras dura, y los
libera al terminar. Con prioridad de escritor — en cuanto uno está esperando,
ningún lector nuevo entra — para que una corriente constante de fetches no lo
mataría de hambre para siempre.

Quién declara que un run necesita esto es `ToolManifest.concurrency` en el
núcleo (`backend/core/contract.py`, issue #8 — todavía no fusionado a esta
rama). Este archivo sólo hace cumplir la exclusión; no sabe ni le importa por
qué un flujo la pide.
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi.concurrency import run_in_threadpool


class RunGate:
    """
    Un lector-escritor asíncrono, del tamaño exacto de este problema.

    No hay límite al número de lectores concurrentes: la restricción real es
    "nada más mientras el escritor corre", no "como máximo N a la vez" — para
    eso un `asyncio.Semaphore` alcanzaría y sería la herramienta equivocada acá.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._condicion = asyncio.Condition(self._lock)
        self._lectores = 0
        self._escritores_esperando = 0
        self._escritor_corriendo = False

    @property
    def lectores(self) -> int:
        return self._lectores

    @property
    def escritor_corriendo(self) -> bool:
        return self._escritor_corriendo

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        """Un run normal. Corre junto con otros lectores; espera si hay un escritor en curso o en cola."""
        async with self._condicion:
            while self._escritor_corriendo or self._escritores_esperando:
                await self._condicion.wait()
            self._lectores += 1
        try:
            yield
        finally:
            async with self._condicion:
                self._lectores -= 1
                self._condicion.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        """El run que no admite compañía. Espera a que drene todo, corre solo, libera al salir."""
        async with self._condicion:
            self._escritores_esperando += 1
            try:
                while self._lectores > 0 or self._escritor_corriendo:
                    await self._condicion.wait()
                self._escritor_corriendo = True
            finally:
                self._escritores_esperando -= 1
        try:
            yield
        finally:
            async with self._condicion:
                self._escritor_corriendo = False
                self._condicion.notify_all()


async def run_with_gate(instance, gate: RunGate, flow_name: str, case_id: str, *, en_vuelo=None,
                        clave: str | None = None, **kwargs):
    """
    Corre un flujo a través del gate — el punto de integración único.

    Exclusivo si el propio flujo lo pide; concurrente si no. El chequeo es un
    `getattr` con default en `False` a propósito: hasta que
    `Instance.requires_exclusive_run` llegue del núcleo (issue #8), ningún
    flujo es exclusivo y esto se comporta exactamente como hoy — sin
    coordinar un merge entre las dos ramas. El día que el método exista, esta
    línea lo empieza a usar sola.

    `en_vuelo` (un `RunsEnVuelo`) anota el run mientras corre, para la grilla,
    y al terminar guarda el resultado bajo su ticket para quien lo pidió sin
    esperar (`POST /runs`). `clave` es ese ticket cuando ya se reservó antes
    de pasar por el gate; sin él, se genera al arrancar. Mismo criterio de
    compatibilidad: si `Instance.run` acepta `on_step`, se le pasa y la UI ve
    el paso en curso; si no —el núcleo de hoy—, sólo se sabe que corre.
    """
    verificar = getattr(instance, "requires_exclusive_run", None)
    es_exclusivo = bool(verificar(flow_name)) if verificar else False
    modo = gate.exclusive() if es_exclusivo else gate.shared()
    async with modo:
        if en_vuelo is not None:
            clave = en_vuelo.empezar(
                case_id, flow_name, source=kwargs.get("source") or "",
                total=_contar_pasos(instance, flow_name), clave=clave,
            )
            if _acepta_on_step(instance):
                kwargs["on_step"] = _hook_de_progreso(en_vuelo, clave)
            # La otra dirección del mismo punto del recorrido: el núcleo lo
            # pregunta antes de cada nodo, y "Detener" en la grilla pone la
            # marca. Mismo criterio de compatibilidad que `on_step`.
            if _acepta(instance, "is_cancelled"):
                kwargs["is_cancelled"] = _hook_de_cancelacion(en_vuelo, clave)
        try:
            resultado = await run_in_threadpool(instance.run, flow_name, case_id, **kwargs)
        except Exception as exc:
            if en_vuelo is not None and clave is not None:
                en_vuelo.terminar(clave, {"status": "err", "message": f"{type(exc).__name__}: {exc}"})
            raise
        if en_vuelo is not None and clave is not None:
            en_vuelo.terminar(clave, _como_dict(resultado))
        return resultado


def _como_dict(resultado) -> dict:
    """El resultado del núcleo como dict, sea `RunResult` o lo que devuelva un fake."""
    to_dict = getattr(resultado, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return resultado if isinstance(resultado, dict) else {"status": str(resultado)}


def _acepta_on_step(instance) -> bool:
    return _acepta(instance, "on_step")


def _acepta(instance, parametro: str) -> bool:
    try:
        return parametro in inspect.signature(instance.run).parameters
    except (TypeError, ValueError):
        return False


def _hook_de_cancelacion(en_vuelo, clave: str):
    """La forma pedida al núcleo: is_cancelled() -> bool, sin argumentos."""

    def is_cancelled() -> bool:
        return en_vuelo.cancelado(clave)

    return is_cancelled


def _hook_de_progreso(en_vuelo, clave: str):
    """La forma pedida al núcleo: on_step(node_id, display="", index=None, total=None)."""

    def on_step(node_id, display="", index=None, total=None, **_ignorados):
        en_vuelo.paso(clave, node_id, display, index)

    return on_step


def _contar_pasos(instance, flow_name: str) -> int | None:
    """Los nodos de acción del grafo: la escala de la barra. None si no se puede saber."""
    parse = getattr(instance, "parse", None)
    if parse is None:
        return None
    try:
        return len(parse(flow_name).action_nodes())
    except Exception:  # noqa: BLE001 — contar pasos nunca puede impedir correr
        return None


__all__ = ["RunGate", "run_with_gate"]

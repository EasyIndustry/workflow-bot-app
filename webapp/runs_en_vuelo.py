"""
Los runs que están corriendo **ahora**, para que la grilla lo muestre, y el
resultado de los que arrancaron sin esperar, para quien los pidió.

`POST /run` bloquea hasta que el flujo termina, y el núcleo guarda la traza y
el log recién al final (`Instance.run` → `runs.save` / `logs.append_run`).
Mientras tanto la fila de la fuente no dice nada: ni que está corriendo, ni
en qué paso. Este registro es la memoria de "qué está en vuelo" de este
proceso — `run_with_gate` anota el arranque y el fin, y la UI lo consulta.

`POST /runs` (sin esperar) devuelve un **ticket** en el acto: la clave con la
que este registro conoce al run. Quien lo pidió —otro Bot, un agente remoto—
pregunta después por ese ticket (`GET /runs/ticket/<clave>`) y recibe "en
cola", "en vuelo" con el paso, o "terminado" con el resultado entero. El
`run_id` del núcleo existe recién cuando el run terminó; el ticket existe
desde antes de que empiece, y por eso es lo que viaja.

Qué paso va es información que sólo tiene el executor del núcleo. Hoy no la
ofrece: `Instance.run` no acepta un callback por nodo (issue #15 en
workflow-bot-core). Por eso `paso()` existe pero nadie lo llama todavía; el
día que el núcleo lo tenga, `run_with_gate` le pasa `on_step` y la barra deja
de ser "en curso" para ser "3 de 10 · Exportar". El total de pasos sí se
puede contar de antemano —los nodos de acción del grafo—, y se anota para que
la barra tenga escala aunque el flujo tenga bucles.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

# Cuántos resultados de runs sin esperar se recuerdan. Un ticket viejo se
# olvida; la traza sigue en la base (`GET /runs`), esto es sólo la memoria
# corta para quien está esperando.
_RECORDAR_TERMINADOS = 500


@dataclass
class RunEnVuelo:
    clave: str
    case_id: str
    flow: str
    source: str
    started_at: float
    # Nodos de acción del flujo, si se pudieron contar. None = sin escala.
    total: int | None = None
    hechos: int = 0
    paso: str = ""
    # Pedido sin esperar y todavía detrás del gate: figura para que se vea
    # que está por correr, pero no corre.
    en_cola: bool = False
    # Alguien pidió frenarlo. El núcleo lo mira antes de cada nodo
    # (`is_cancelled`), así que el nodo en curso termina y el que sigue ya no
    # arranca: se detiene entre pasos, no a mitad de uno.
    cancelar: bool = False

    def to_dict(self, ahora: float) -> dict:
        return {
            "ticket": self.clave,
            "case_id": self.case_id,
            "flow": self.flow,
            "source": self.source,
            "started_at": self.started_at,
            "elapsed": max(0.0, round(ahora - self.started_at, 1)),
            "total": self.total,
            "hechos": self.hechos,
            "paso": self.paso,
            "en_cola": self.en_cola,
            "cancelando": self.cancelar,
        }


class RunsEnVuelo:
    """Thread-safe: los runs corren en el threadpool y la API los lee desde el loop."""

    def __init__(self, reloj=time.time) -> None:
        self._reloj = reloj
        self._lock = threading.Lock()
        self._vivos: dict[str, RunEnVuelo] = {}
        self._terminados: OrderedDict[str, dict] = OrderedDict()

    def empezar(self, case_id: str, flow: str, *, source: str = "", total: int | None = None,
                clave: str | None = None) -> str:
        """
        Anota el arranque. Con `clave` —un ticket que ya se había reservado— la
        misma entrada pasa de "en cola" a corriendo, con el reloj puesto a cero.
        """
        with self._lock:
            if clave and clave in self._vivos:
                vivo = self._vivos[clave]
                vivo.en_cola = False
                vivo.started_at = self._reloj()
                vivo.total = total if total is not None else vivo.total
                return clave
            clave = clave or uuid.uuid4().hex[:12]
            self._vivos[clave] = RunEnVuelo(
                clave=clave, case_id=str(case_id), flow=flow, source=source or "",
                started_at=self._reloj(), total=total,
            )
        return clave

    def reservar(self, case_id: str, flow: str, *, source: str = "") -> str:
        """Un ticket para un run que se pidió sin esperar y todavía no arrancó."""
        clave = uuid.uuid4().hex[:12]
        with self._lock:
            self._vivos[clave] = RunEnVuelo(
                clave=clave, case_id=str(case_id), flow=flow, source=source or "",
                started_at=self._reloj(), en_cola=True,
            )
        return clave

    def paso(self, clave: str, node_id: str, display: str = "", indice: int | None = None) -> None:
        """El nodo que empieza a correr. `indice` es 1-based si el núcleo lo manda; si no, se cuenta."""
        with self._lock:
            vivo = self._vivos.get(clave)
            if vivo is None:
                return
            vivo.hechos = indice if indice is not None else vivo.hechos + 1
            vivo.paso = display or node_id

    def terminar(self, clave: str, resultado: dict | None = None) -> None:
        """Saca el run de los vivos y, si hay resultado, lo guarda para quien pregunte por el ticket."""
        with self._lock:
            vivo = self._vivos.pop(clave, None)
            if resultado is not None:
                self._terminados[clave] = {
                    **resultado,
                    "ticket": clave,
                    "case_id": (vivo.case_id if vivo else resultado.get("case_id")),
                    "flow": (vivo.flow if vivo else resultado.get("flow")),
                }
                while len(self._terminados) > _RECORDAR_TERMINADOS:
                    self._terminados.popitem(last=False)

    def cancelar(self, clave: str) -> bool:
        """
        Pide frenar un run. True si estaba en vuelo. No lo mata: deja la marca
        que `is_cancelled` va a leer antes del próximo nodo, así que lo que
        está a mitad de camino termina y lo que sigue no empieza.
        """
        with self._lock:
            vivo = self._vivos.get(clave)
            if vivo is None:
                return False
            vivo.cancelar = True
            return True

    def cancelado(self, clave: str) -> bool:
        """Lo que el núcleo pregunta antes de cada nodo."""
        with self._lock:
            vivo = self._vivos.get(clave)
            return bool(vivo and vivo.cancelar)

    def en_vuelo_de(self, case_id: str, source: str = "") -> dict | None:
        """
        El run vivo de una fila, si hay uno. Es lo que permite rechazar un
        segundo `POST /run` para la misma fila mientras el primero corre: desde
        otra PC la grilla puede no haber sondeado todavía y el botón sigue ahí.
        """
        ahora = self._reloj()
        with self._lock:
            for vivo in self._vivos.values():
                if vivo.case_id == str(case_id) and (not source or vivo.source == source):
                    return vivo.to_dict(ahora)
        return None

    def consultar(self, clave: str) -> dict:
        """Qué pasa con un ticket: en cola, en vuelo (con su paso), terminado (con el run), o desconocido."""
        ahora = self._reloj()
        with self._lock:
            vivo = self._vivos.get(clave)
            if vivo is not None:
                return {"estado": "en_cola" if vivo.en_cola else "en_vuelo", "vivo": vivo.to_dict(ahora), "run": None}
            terminado = self._terminados.get(clave)
        if terminado is not None:
            return {"estado": "terminado", "vivo": None, "run": terminado}
        return {"estado": "desconocido", "vivo": None, "run": None}

    def listar(self) -> list[dict]:
        ahora = self._reloj()
        with self._lock:
            vivos = sorted(self._vivos.values(), key=lambda v: v.started_at)
        return [v.to_dict(ahora) for v in vivos]

    def __len__(self) -> int:
        with self._lock:
            return len(self._vivos)


__all__ = ["RunEnVuelo", "RunsEnVuelo"]

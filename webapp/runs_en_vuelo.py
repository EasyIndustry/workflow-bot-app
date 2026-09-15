"""
Los runs que están corriendo **ahora**, para que la grilla lo muestre.

`POST /run` bloquea hasta que el flujo termina, y el núcleo guarda la traza y
el log recién al final (`Instance.run` → `runs.save` / `logs.append_run`).
Mientras tanto la fila de la fuente no dice nada: ni que está corriendo, ni
en qué paso. Este registro es la memoria de "qué está en vuelo" de este
proceso — `run_with_gate` anota el arranque y el fin, y la UI lo consulta.

Qué paso va es información que sólo tiene el executor del núcleo. Hoy no la
ofrece: `Instance.run` no acepta un callback por nodo (issue abierto en
workflow-bot-core). Por eso `paso()` existe pero nadie lo llama todavía; el
día que el núcleo lo tenga, `run_with_gate` le pasa `on_step` y la barra deja
de ser "en curso" para ser "3 de 10 · Exportar". El total de
pasos sí se puede contar de antemano —los nodos de acción del grafo—, y se
anota para que la barra tenga escala aunque el flujo tenga bucles (que la
hacen aproximada, no exacta).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass


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

    def to_dict(self, ahora: float) -> dict:
        return {
            "case_id": self.case_id,
            "flow": self.flow,
            "source": self.source,
            "started_at": self.started_at,
            "elapsed": max(0.0, round(ahora - self.started_at, 1)),
            "total": self.total,
            "hechos": self.hechos,
            "paso": self.paso,
        }


class RunsEnVuelo:
    """Thread-safe: los runs corren en el threadpool y la API los lee desde el loop."""

    def __init__(self, reloj=time.time) -> None:
        self._reloj = reloj
        self._lock = threading.Lock()
        self._vivos: dict[str, RunEnVuelo] = {}

    def empezar(self, case_id: str, flow: str, *, source: str = "", total: int | None = None) -> str:
        clave = uuid.uuid4().hex[:12]
        with self._lock:
            self._vivos[clave] = RunEnVuelo(
                clave=clave, case_id=str(case_id), flow=flow, source=source or "",
                started_at=self._reloj(), total=total,
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

    def terminar(self, clave: str) -> None:
        with self._lock:
            self._vivos.pop(clave, None)

    def listar(self) -> list[dict]:
        ahora = self._reloj()
        with self._lock:
            vivos = sorted(self._vivos.values(), key=lambda v: v.started_at)
        return [v.to_dict(ahora) for v in vivos]

    def __len__(self) -> int:
        with self._lock:
            return len(self._vivos)


__all__ = ["RunEnVuelo", "RunsEnVuelo"]

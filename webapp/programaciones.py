"""
Programar flujos: que uno corra solo, cada cierto tiempo (#11).

Hasta acá un flujo corría sólo si alguien lo disparaba —la grilla, la
pantalla, la API, otro Bot—. Lo periódico (revisar una casilla, renovar un
token que vence, un reporte diario) quedaba afuera o dependía de una tarea
del sistema operativo que llamaba a la API: vivía fuera del Bot, no se veía
en la pantalla y no viajaba con la instalación.

Es de la app y no sabe nada de ningún plugin: programa cualquier flujo,
también uno que sólo use tools nativos del núcleo. Nada acá toca el núcleo.

Qué hace:

- **Una programación por flujo**, con el nombre del flujo como clave. Por
  intervalo ("cada N minutos") o por horario ("a las 8:00", los días que se
  elijan). Se pausa sin borrarla (`activa`).
- Se guarda en la base de la instalación, en una colección propia de la
  webapp, igual que el repo de actualizaciones o el catálogo de plugins. La
  configuración y el estado (última corrida, resultado, salteadas) van en
  colecciones separadas: editar una programación no le borra el historial.
- Cada corrida es un run como cualquier otro: `run_with_gate`, el mismo gate
  y la misma política de actores, con `source="programado"`.
- Si la anterior sigue en vuelo cuando toca la siguiente, no se encima: se
  saltea y queda anotado.
- Al arrancar no recupera las que se perdieron con el Bot apagado. Por
  intervalo corre **una** vez si ya se pasó la hora (un token vencido no
  puede esperar otro intervalo entero), no una por cada vuelta perdida. Por
  horario sigue desde el próximo horario: el reporte de las 8 no sale a las
  11 porque el Bot estuvo apagado.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Callable

from backend.core.contract import Field, ParamType, Resource
from backend.core.resources import ResourceError

log = logging.getLogger(__name__)

SOURCE = "programado"
# Cada cuánto se mira si toca alguna. Una programación por minuto no necesita
# más precisión que esto, y mirar no cuesta nada: son unas filas de la base.
TICK = 15.0
DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
_HORA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

RESOURCE = Resource(
    name="programaciones",
    label="Programaciones",
    item_label="Programación",
    key_field="flujo",
    doc="Flujos que corren solos, cada cierto tiempo o a una hora.",
    fields=(
        Field("activa", ParamType.BOOL, label="Activa", default=True),
        Field("modo", ParamType.ENUM, label="Cuándo", default="intervalo", choices=("intervalo", "horario")),
        Field("cada_minutos", ParamType.INT, label="Cada (minutos)", default=15),
        Field("hora", ParamType.STR, label="Hora", default="08:00"),
        Field("dias", ParamType.STR, label="Días", default=""),
        Field("case_id", ParamType.STR, label="Caso", default=""),
        Field("fila", ParamType.JSON, label="Fila", default={}),
        Field("actor", ParamType.STR, label="Actor", default=""),
    ),
)

RESOURCE_ESTADO = Resource(
    name="programaciones_estado",
    label="Estado de las programaciones",
    item_label="Estado",
    key_field="flujo",
    doc="Lo que pasó con cada programación. Lo escribe el programador, no la pantalla.",
    fields=(
        Field("proxima", ParamType.FLOAT, label="Próxima"),
        Field("ultima", ParamType.FLOAT, label="Última"),
        Field("resultado", ParamType.STR, label="Resultado"),
        Field("mensaje", ParamType.STR, label="Mensaje"),
        Field("run_id", ParamType.STR, label="Run"),
        Field("corridas", ParamType.INT, label="Corridas", default=0),
        Field("salteadas", ParamType.INT, label="Salteadas", default=0),
    ),
)


class ProgramacionError(Exception):
    """Una programación que no se puede guardar así, con un mensaje legible."""


# ── Validar ─────────────────────────────────────────────────────────────


def normalizar(item: dict) -> dict:
    """
    La programación lista para guardar, o `ProgramacionError`.

    Por intervalo, `cada_minutos` desde 1. Por horario, `HH:MM` y días de la
    lista (vacío = todos). `fila` es un objeto: es el row con el que corre.
    """
    modo = (item.get("modo") or "intervalo").strip()
    if modo not in ("intervalo", "horario"):
        raise ProgramacionError(f'Modo desconocido: "{modo}". Es "intervalo" u "horario".')
    limpio = {
        "activa": bool(item.get("activa", True)),
        "modo": modo,
        "case_id": str(item.get("case_id") or "").strip(),
        "actor": str(item.get("actor") or "").strip(),
        "fila": item.get("fila") or {},
    }
    if not isinstance(limpio["fila"], dict):
        raise ProgramacionError("La fila tiene que ser un objeto JSON: {\"campo\": \"valor\"}.")
    if modo == "intervalo":
        try:
            cada = int(item.get("cada_minutos"))
        except (TypeError, ValueError):
            raise ProgramacionError("Cada cuántos minutos: tiene que ser un número entero.") from None
        if cada < 1:
            raise ProgramacionError("Cada cuántos minutos: desde 1.")
        limpio["cada_minutos"] = cada
    else:
        hora = str(item.get("hora") or "").strip()
        if not _HORA.match(hora):
            raise ProgramacionError(f'Hora inválida: "{hora}". Es HH:MM, por ejemplo 08:00.')
        h, m = hora.split(":")
        limpio["hora"] = f"{int(h):02d}:{m}"
        dias = [d.strip().lower() for d in str(item.get("dias") or "").split(",") if d.strip()]
        if otros := [d for d in dias if d not in DIAS]:
            raise ProgramacionError(f"Días desconocidos: {', '.join(otros)}. Van {', '.join(DIAS)}.")
        limpio["dias"] = ",".join(d for d in DIAS if d in dias)
    return limpio


# ── Cuándo toca ─────────────────────────────────────────────────────────


def proxima(prog: dict, ahora: float, ultima: float | None = None) -> float:
    """
    El próximo momento en que corre, como timestamp.

    Por intervalo: la última más el intervalo, pero nunca antes de `ahora`
    (si se pasó —el Bot estuvo apagado—, toca ya, una sola vez). Sin última,
    ya: una programación recién creada se ve correr. Por horario: el próximo
    `hora` en un día permitido, estrictamente después de la última corrida y
    no antes de `ahora`, en la hora local de la máquina.
    """
    if prog.get("modo") == "horario":
        h, m = (int(x) for x in prog["hora"].split(":"))
        dias = {DIAS.index(d) for d in (prog.get("dias") or "").split(",") if d} or set(range(7))
        desde = max(ahora, (ultima or 0) + 1)
        base = datetime.fromtimestamp(desde)
        for delta in range(8):
            dia = (base + timedelta(days=delta)).replace(hour=h, minute=m, second=0, microsecond=0)
            if dia.weekday() in dias and dia.timestamp() >= desde:
                return dia.timestamp()
        raise ProgramacionError("No hay ningún día en que corra.")  # pragma: no cover — dias no vacío
    if ultima is None:
        return ahora
    return max(ultima + int(prog["cada_minutos"]) * 60, ahora)


def describir(prog: dict) -> str:
    """En castellano, para la lista: "cada 15 minutos", "a las 08:00, lun a vie"."""
    if prog.get("modo") == "horario":
        dias = [d for d in (prog.get("dias") or "").split(",") if d]
        if not dias or len(dias) == 7:
            cuando = "todos los días"
        elif dias == list(DIAS[:5]):
            cuando = "de lunes a viernes"
        else:
            cuando = ", ".join(dias)
        return f"a las {prog.get('hora')}, {cuando}"
    cada = int(prog.get("cada_minutos") or 0)
    return "cada minuto" if cada == 1 else f"cada {cada} minutos"


# ── Guardado ────────────────────────────────────────────────────────────


def _store(instance):
    return instance.resource_store("webapp", RESOURCE)


def _store_estado(instance):
    return instance.resource_store("webapp", RESOURCE_ESTADO)


def _sin_meta(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def leer_estado(instance, flujo: str) -> dict:
    try:
        return _sin_meta(_store_estado(instance).read(flujo))
    except ResourceError:
        return {}


def _escribir_estado(instance, flujo: str, **cambios) -> dict:
    estado = {**leer_estado(instance, flujo), **cambios}
    estado.pop("flujo", None)
    _store_estado(instance).write(flujo, estado)
    return estado


def listar(instance) -> list[dict]:
    """Cada programación con su estado y la descripción en castellano."""
    salida = []
    for item in _store(instance).list_items():
        prog = _sin_meta(item)
        salida.append({**prog, "descripcion": describir(prog), "estado": leer_estado(instance, prog["flujo"])})
    return salida


def guardar(instance, flujo: str, item: dict, *, ahora: float | None = None) -> dict:
    """Guarda (o reemplaza) la programación de un flujo y recalcula la próxima."""
    limpio = normalizar(item)
    # `get` devuelve None para uno que no existe y levanta para un nombre
    # inválido: las dos cosas son "no hay ese flujo".
    try:
        existe = instance.workflows.get(flujo) is not None
    except Exception:  # noqa: BLE001
        existe = False
    if not existe:
        raise ProgramacionError(f'No hay un flujo "{flujo}".')
    _store(instance).write(flujo, limpio)
    estado = leer_estado(instance, flujo)
    ahora = time.time() if ahora is None else ahora
    _escribir_estado(instance, flujo, proxima=proxima(limpio, ahora, estado.get("ultima")))
    return {**limpio, "flujo": flujo, "descripcion": describir(limpio), "estado": leer_estado(instance, flujo)}


def borrar(instance, flujo: str) -> None:
    try:
        _store(instance).delete(flujo)
    except ResourceError:
        raise ProgramacionError(f'"{flujo}" no tiene programación.') from None
    try:
        _store_estado(instance).delete(flujo)
    except ResourceError:
        pass


# ── El programador ──────────────────────────────────────────────────────


class Programador:
    """
    Mira cada `TICK` segundos qué programación toca y la lanza.

    `instancia` es un callable y no la instancia: la webapp la reemplaza al
    instalar un plugin o actualizar el núcleo (`core_api._recargar`), y un
    programador que se quedara con la vieja correría contra una base cerrada.
    `correr(instance, flujo, case_id, fila, actor)` es la corrida en sí —en la
    webapp, `run_with_gate` con el gate y los runs en vuelo—; separada para
    poder probar esto sin levantar un servidor.
    """

    def __init__(self, instancia: Callable, correr: Callable, *, reloj: Callable[[], float] = time.time):
        self._instancia = instancia
        self._correr = correr
        self._reloj = reloj
        self._corriendo: dict[str, asyncio.Task] = {}
        self._tarea: asyncio.Task | None = None

    # Arranque y cierre ────────────────────────────────────────────────

    def al_arrancar(self) -> None:
        """
        Recalcula todas las próximas desde ahora: es lo que evita recuperar de
        golpe las perdidas con el Bot apagado (ver `proxima`).
        """
        instance = self._instancia()
        ahora = self._reloj()
        for prog in listar(instance):
            try:
                _escribir_estado(instance, prog["flujo"],
                                 proxima=proxima(prog, ahora, prog["estado"].get("ultima")))
            except Exception:  # noqa: BLE001 — una programación rota no frena a las demás
                log.exception("programación %s: no se pudo calcular la próxima", prog.get("flujo"))

    def iniciar(self) -> None:
        if self._tarea is None or self._tarea.done():
            self.al_arrancar()
            self._tarea = asyncio.create_task(self._ciclo(), name="programador")

    async def parar(self) -> None:
        if self._tarea is not None:
            self._tarea.cancel()
            try:
                await self._tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._tarea = None

    async def _ciclo(self) -> None:
        while True:
            try:
                await self.revisar()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — el programador no se muere por una vuelta rota
                log.exception("programador: falló una vuelta")
            await asyncio.sleep(TICK)

    # Una vuelta ───────────────────────────────────────────────────────

    async def revisar(self) -> list[str]:
        """Lanza las que tocan. Devuelve qué pasó con cada una, para los tests."""
        instance = self._instancia()
        ahora = self._reloj()
        hechas = []
        for prog in listar(instance):
            flujo = prog["flujo"]
            estado = prog["estado"]
            if not prog.get("activa", True):
                continue
            prox = estado.get("proxima")
            if prox is None:
                prox = proxima(prog, ahora, estado.get("ultima"))
                _escribir_estado(instance, flujo, proxima=prox)
            if prox > ahora:
                continue
            siguiente = proxima(prog, ahora + 1, ahora) if prog.get("modo") == "horario" \
                else ahora + int(prog["cada_minutos"]) * 60
            vivo = self._corriendo.get(flujo)
            if vivo is not None and not vivo.done():
                # No se encima: la anterior sigue. Queda anotado y se espera
                # a la próxima vuelta del intervalo.
                _escribir_estado(instance, flujo, proxima=siguiente,
                                 salteadas=int(estado.get("salteadas") or 0) + 1,
                                 mensaje="salteada: la anterior seguía corriendo")
                hechas.append(f"{flujo}: salteada")
                continue
            _escribir_estado(instance, flujo, proxima=siguiente, ultima=ahora,
                             resultado="corriendo", mensaje="")
            self._corriendo[flujo] = asyncio.create_task(self._una(flujo, prog), name=f"programado:{flujo}")
            hechas.append(f"{flujo}: lanzada")
        return hechas

    async def _una(self, flujo: str, prog: dict) -> None:
        instance = self._instancia()
        case_id = prog.get("case_id") or f"programado {flujo}"
        try:
            resultado = await self._correr(instance, flujo, case_id, prog.get("fila") or {}, prog.get("actor") or None)
            datos = resultado.to_dict() if hasattr(resultado, "to_dict") else dict(resultado or {})
            fallo = bool(datos.get("failed")) or datos.get("status") == "err"
            cambios = {"resultado": "err" if fallo else "ok",
                       "mensaje": str(datos.get("message") or datos.get("error") or "")[:500],
                       "run_id": str(datos.get("run_id") or "")}
        except Exception as exc:  # noqa: BLE001 — el flujo no existe, tiene errores, el actor no puede
            cambios = {"resultado": "err", "mensaje": f"{type(exc).__name__}: {exc}"[:500], "run_id": ""}
        try:
            estado = leer_estado(self._instancia(), flujo)
            _escribir_estado(self._instancia(), flujo, corridas=int(estado.get("corridas") or 0) + 1, **cambios)
        except Exception:  # noqa: BLE001 — la programación se borró mientras corría
            log.info("programación %s: no se pudo anotar el resultado", flujo)


__all__ = [
    "DIAS", "Programador", "ProgramacionError", "RESOURCE", "RESOURCE_ESTADO", "SOURCE",
    "borrar", "describir", "guardar", "leer_estado", "listar", "normalizar", "proxima",
]

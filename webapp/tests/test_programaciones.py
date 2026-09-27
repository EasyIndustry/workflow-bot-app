"""Tests de `webapp/programaciones.py`: flujos que corren solos (#11)."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.core.instance import Instance  # noqa: E402
from webapp import programaciones as prog  # noqa: E402

FLUJO = 'flowchart TD\n    B(inicio)\n    L["core.log | message=hola"]\n    B --> L\n'


def _ts(texto: str) -> float:
    return datetime.fromisoformat(texto).timestamp()


@pytest.fixture
def instancia(tmp_path):
    inst = Instance(tmp_path)
    inst.workflows.save_mmd("reporte", FLUJO)
    yield inst
    inst.close()


# ── Validar ─────────────────────────────────────────────────────────────


def test_intervalo_pide_minutos_desde_uno():
    assert prog.normalizar({"modo": "intervalo", "cada_minutos": "15"})["cada_minutos"] == 15
    with pytest.raises(prog.ProgramacionError, match="desde 1"):
        prog.normalizar({"modo": "intervalo", "cada_minutos": 0})


def test_horario_normaliza_hora_y_dias():
    limpio = prog.normalizar({"modo": "horario", "hora": "8:05", "dias": "vie, lun"})
    assert limpio["hora"] == "08:05"
    assert limpio["dias"] == "lun,vie"  # en el orden de la semana
    with pytest.raises(prog.ProgramacionError, match="Hora inválida"):
        prog.normalizar({"modo": "horario", "hora": "25:00"})
    with pytest.raises(prog.ProgramacionError, match="Días desconocidos"):
        prog.normalizar({"modo": "horario", "hora": "08:00", "dias": "lunes"})


def test_describir():
    assert prog.describir({"modo": "intervalo", "cada_minutos": 15}) == "cada 15 minutos"
    assert prog.describir({"modo": "horario", "hora": "08:00", "dias": "lun,mar,mie,jue,vie"}) == \
        "a las 08:00, de lunes a viernes"
    assert prog.describir({"modo": "horario", "hora": "08:00", "dias": ""}) == "a las 08:00, todos los días"


# ── Cuándo toca ─────────────────────────────────────────────────────────


def test_intervalo_recien_creada_corre_ya():
    assert prog.proxima({"modo": "intervalo", "cada_minutos": 15}, 1000.0) == 1000.0


def test_intervalo_suma_a_la_ultima():
    assert prog.proxima({"modo": "intervalo", "cada_minutos": 15}, 1000.0, ultima=900.0) == 900.0 + 900


def test_intervalo_perdido_corre_una_vez_no_todas():
    """Bot apagado tres horas con 'cada 15': al arrancar toca ya, una sola vez."""
    ahora = 100_000.0
    assert prog.proxima({"modo": "intervalo", "cada_minutos": 15}, ahora, ultima=ahora - 3 * 3600) == ahora


def test_horario_el_mismo_dia_o_el_siguiente():
    p = {"modo": "horario", "hora": "08:00", "dias": ""}
    assert prog.proxima(p, _ts("2026-09-28T07:00")) == _ts("2026-09-28T08:00")
    assert prog.proxima(p, _ts("2026-09-28T09:00")) == _ts("2026-09-29T08:00")


def test_horario_perdido_no_se_recupera():
    """El reporte de las 8 no sale a las 11 porque el Bot estuvo apagado."""
    p = {"modo": "horario", "hora": "08:00", "dias": ""}
    assert prog.proxima(p, _ts("2026-09-28T11:00"), ultima=_ts("2026-09-27T08:00")) == _ts("2026-09-29T08:00")


def test_horario_salta_a_los_dias_permitidos():
    """El sábado 26/09/2026, 'de lunes a viernes' va al lunes 28."""
    p = {"modo": "horario", "hora": "08:00", "dias": "lun,mar,mie,jue,vie"}
    assert prog.proxima(p, _ts("2026-09-26T07:00")) == _ts("2026-09-28T08:00")


# ── Guardado ────────────────────────────────────────────────────────────


def test_guardar_exige_un_flujo_que_exista(instancia):
    with pytest.raises(prog.ProgramacionError, match="No hay un flujo"):
        prog.guardar(instancia, "no existe", {"modo": "intervalo", "cada_minutos": 5})


def test_guardar_y_listar_con_estado(instancia):
    guardada = prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 5}, ahora=1000.0)
    assert guardada["descripcion"] == "cada 5 minutos"
    assert guardada["estado"]["proxima"] == 1000.0
    [item] = prog.listar(instancia)
    assert item["flujo"] == "reporte" and item["estado"]["proxima"] == 1000.0


def test_editar_no_borra_el_historial(instancia):
    prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 5}, ahora=1000.0)
    prog._escribir_estado(instancia, "reporte", ultima=1000.0, corridas=3)
    prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 10}, ahora=1100.0)
    estado = prog.leer_estado(instancia, "reporte")
    assert estado["corridas"] == 3
    assert estado["proxima"] == 1000.0 + 600  # desde la última, con el intervalo nuevo


def test_borrar(instancia):
    prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 5})
    prog.borrar(instancia, "reporte")
    assert prog.listar(instancia) == []
    with pytest.raises(prog.ProgramacionError):
        prog.borrar(instancia, "reporte")


# ── El programador ──────────────────────────────────────────────────────


class _Reloj:
    def __init__(self, ahora: float):
        self.ahora = ahora

    def __call__(self) -> float:
        return self.ahora


class _Resultado:
    def __init__(self, failed=False, message="", run_id="r1"):
        self._d = {"failed": failed, "message": message, "run_id": run_id}

    def to_dict(self):
        return self._d


def test_corre_cuando_toca_y_anota_el_resultado(instancia):
    corridas = []

    async def correr(_inst, flujo, case_id, fila, actor):
        corridas.append((flujo, case_id, fila, actor))
        return _Resultado(run_id="run-42")

    async def escenario():
        reloj = _Reloj(1000.0)
        prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 5, "fila": {"id": "7"}}, ahora=1000.0)
        p = prog.Programador(lambda: instancia, correr, reloj=reloj)
        assert await p.revisar() == ["reporte: lanzada"]
        await asyncio.gather(*p._corriendo.values())
        reloj.ahora = 1100.0  # antes de los 5 minutos: no toca
        assert await p.revisar() == []
        return prog.leer_estado(instancia, "reporte")

    estado = asyncio.run(escenario())
    assert corridas == [("reporte", "programado reporte", {"id": "7"}, None)]
    assert estado["resultado"] == "ok" and estado["run_id"] == "run-42" and estado["corridas"] == 1
    assert estado["ultima"] == 1000.0 and estado["proxima"] == 1300.0


def test_no_se_encima_si_la_anterior_sigue(instancia):
    liberar = asyncio.Event

    async def escenario():
        seguir = liberar()

        async def correr(*_a):
            await seguir.wait()
            return _Resultado()

        reloj = _Reloj(1000.0)
        prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 1}, ahora=1000.0)
        p = prog.Programador(lambda: instancia, correr, reloj=reloj)
        assert await p.revisar() == ["reporte: lanzada"]
        reloj.ahora = 1060.0  # toca otra vez, pero la primera sigue
        assert await p.revisar() == ["reporte: salteada"]
        seguir.set()
        await asyncio.gather(*p._corriendo.values())
        return prog.leer_estado(instancia, "reporte")

    estado = asyncio.run(escenario())
    assert estado["salteadas"] == 1 and estado["corridas"] == 1


def test_pausada_no_corre(instancia):
    async def correr(*_a):
        raise AssertionError("no tenía que correr")

    async def escenario():
        prog.guardar(instancia, "reporte", {"activa": False, "modo": "intervalo", "cada_minutos": 1}, ahora=0.0)
        return await prog.Programador(lambda: instancia, correr, reloj=_Reloj(10_000.0)).revisar()

    assert asyncio.run(escenario()) == []


def test_un_error_al_correr_queda_anotado(instancia):
    async def correr(*_a):
        raise RuntimeError("el flujo tiene errores: falta un tool")

    async def escenario():
        prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 1}, ahora=0.0)
        p = prog.Programador(lambda: instancia, correr, reloj=_Reloj(0.0))
        await p.revisar()
        await asyncio.gather(*p._corriendo.values())
        return prog.leer_estado(instancia, "reporte")

    estado = asyncio.run(escenario())
    assert estado["resultado"] == "err"
    assert "falta un tool" in estado["mensaje"]


def test_al_arrancar_no_recupera_las_perdidas(instancia):
    """Tres horas apagado con 'cada 15': una sola corrida, no doce."""
    corridas = []

    async def correr(*_a):
        corridas.append(1)
        return _Resultado()

    async def escenario():
        prog.guardar(instancia, "reporte", {"modo": "intervalo", "cada_minutos": 15}, ahora=0.0)
        prog._escribir_estado(instancia, "reporte", ultima=0.0, proxima=900.0)
        reloj = _Reloj(3 * 3600.0)
        p = prog.Programador(lambda: instancia, correr, reloj=reloj)
        p.al_arrancar()
        for _ in range(5):
            await p.revisar()
            await asyncio.gather(*p._corriendo.values())
        return prog.leer_estado(instancia, "reporte")

    estado = asyncio.run(escenario())
    assert len(corridas) == 1
    assert estado["proxima"] == 3 * 3600.0 + 900

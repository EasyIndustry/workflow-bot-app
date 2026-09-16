"""
El registro de runs en vuelo y su enganche en `run_with_gate`.

Lo que se prueba es el contrato con la grilla: mientras `Instance.run` no
volvió, el run figura con su caso, su flujo y cuánto lleva; al terminar
—bien o mal— desaparece. Y la compatibilidad hacia adelante: con un núcleo
que acepte `on_step`, el paso en curso llega; con el de hoy, no rompe.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp.run_gate import RunGate, run_with_gate  # noqa: E402
from webapp.runs_en_vuelo import RunsEnVuelo  # noqa: E402


class Reloj:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def test_un_run_figura_mientras_corre_con_lo_que_lleva_y_se_va_al_terminar():
    reloj = Reloj()
    registro = RunsEnVuelo(reloj=reloj)

    clave = registro.empezar("CASO-1", "flujo_demo", source="casos", total=10)
    reloj.t += 12.4
    [vivo] = registro.listar()

    assert vivo["case_id"] == "CASO-1"
    assert vivo["flow"] == "flujo_demo"
    assert vivo["source"] == "casos"
    assert vivo["elapsed"] == 12.4
    assert (vivo["total"], vivo["hechos"], vivo["paso"]) == (10, 0, "")

    registro.terminar(clave)
    assert registro.listar() == []


def test_paso_cuenta_solo_si_el_nucleo_no_manda_indice_y_usa_el_indice_si_lo_manda():
    registro = RunsEnVuelo()
    clave = registro.empezar("1", "f")

    registro.paso(clave, "N1", "refrescar row")
    registro.paso(clave, "EXP", "Exportar")
    assert registro.listar()[0]["hechos"] == 2
    assert registro.listar()[0]["paso"] == "Exportar"

    registro.paso(clave, "MF", indice=7)
    assert registro.listar()[0]["hechos"] == 7
    assert registro.listar()[0]["paso"] == "MF"  # sin display, el id

    registro.paso("clave-inexistente", "X")  # un run que ya terminó no revive


# ── run_with_gate ────────────────────────────────────────────────────────


class Grafo:
    def action_nodes(self):
        return [("a", None), ("b", None), ("c", None)]


class InstanciaDeHoy:
    """`run` sin `on_step`: el núcleo actual."""

    def __init__(self, registro):
        self.registro = registro
        self.visto_en_vuelo = None

    def parse(self, flow_name):
        return Grafo()

    def run(self, flow_name, case_id, **kwargs):
        assert "on_step" not in kwargs
        self.visto_en_vuelo = self.registro.listar()
        return "ok"


class InstanciaConOnStep(InstanciaDeHoy):
    def run(self, flow_name, case_id, *, on_step=None, **kwargs):
        on_step("N1", "refrescar row", 1, 3)
        on_step("EXP", display="Exportar", index=2)
        self.visto_en_vuelo = self.registro.listar()
        return "ok"


def test_mientras_corre_figura_con_el_total_de_pasos_y_al_volver_ya_no():
    registro = RunsEnVuelo()
    instancia = InstanciaDeHoy(registro)

    resultado = asyncio.run(
        run_with_gate(instancia, RunGate(), "f", "CASO-1", en_vuelo=registro, source="casos")
    )

    assert resultado == "ok"
    [vivo] = instancia.visto_en_vuelo
    assert (vivo["case_id"], vivo["flow"], vivo["source"], vivo["total"]) == ("CASO-1", "f", "casos", 3)
    assert vivo["hechos"] == 0  # el núcleo de hoy no avisa por nodo
    assert registro.listar() == []


def test_con_un_nucleo_que_acepta_on_step_el_paso_en_curso_llega_al_registro():
    registro = RunsEnVuelo()
    instancia = InstanciaConOnStep(registro)

    asyncio.run(run_with_gate(instancia, RunGate(), "f", "1", en_vuelo=registro))

    [vivo] = instancia.visto_en_vuelo
    assert (vivo["hechos"], vivo["paso"]) == (2, "Exportar")


def test_si_el_run_explota_el_registro_queda_limpio():
    registro = RunsEnVuelo()

    class InstanciaQueExplota(InstanciaDeHoy):
        def run(self, flow_name, case_id, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(run_with_gate(InstanciaQueExplota(registro), RunGate(), "f", "1", en_vuelo=registro))
    assert len(registro) == 0


def test_sin_registro_run_with_gate_sigue_igual_que_antes():
    class Pelada:
        def run(self, flow_name, case_id, **kwargs):
            return kwargs

    assert asyncio.run(run_with_gate(Pelada(), RunGate(), "f", "1", row={"a": 1})) == {"row": {"a": 1}}


# ── tickets: runs pedidos sin esperar ──────────────────────────────────


def test_un_ticket_pasa_de_en_cola_a_en_vuelo_a_terminado_con_su_resultado():
    reloj = Reloj()
    registro = RunsEnVuelo(reloj=reloj)

    ticket = registro.reservar("CASO-9", "flujo_demo", source="casos")
    assert registro.consultar(ticket)["estado"] == "en_cola"
    assert registro.listar()[0]["en_cola"] is True

    reloj.t += 30
    assert registro.empezar("CASO-9", "flujo_demo", total=4, clave=ticket) == ticket
    consulta = registro.consultar(ticket)
    assert consulta["estado"] == "en_vuelo"
    assert consulta["vivo"]["elapsed"] == 0.0  # el reloj arranca cuando corre, no cuando se encoló
    assert consulta["vivo"]["total"] == 4 and consulta["vivo"]["en_cola"] is False

    registro.terminar(ticket, {"status": "ok", "run_id": "run-1"})
    consulta = registro.consultar(ticket)
    assert consulta["estado"] == "terminado"
    assert consulta["run"] == {"status": "ok", "run_id": "run-1", "ticket": ticket, "case_id": "CASO-9", "flow": "flujo_demo"}
    assert registro.listar() == []
    assert registro.consultar("no-existe")["estado"] == "desconocido"


def test_run_with_gate_guarda_el_resultado_bajo_el_ticket_tambien_si_explota():
    registro = RunsEnVuelo()

    class Resultado:
        def to_dict(self):
            return {"status": "ok", "run_id": "run-7"}

    class Instancia(InstanciaDeHoy):
        def run(self, flow_name, case_id, **kwargs):
            return Resultado()

    ticket = registro.reservar("1", "f")
    asyncio.run(run_with_gate(Instancia(registro), RunGate(), "f", "1", en_vuelo=registro, clave=ticket))
    assert registro.consultar(ticket)["run"]["run_id"] == "run-7"

    class Explota(InstanciaDeHoy):
        def run(self, flow_name, case_id, **kwargs):
            raise RuntimeError("boom")

    ticket2 = registro.reservar("2", "f")
    with pytest.raises(RuntimeError):
        asyncio.run(run_with_gate(Explota(registro), RunGate(), "f", "2", en_vuelo=registro, clave=ticket2))
    terminado = registro.consultar(ticket2)
    assert terminado["estado"] == "terminado" and terminado["run"]["status"] == "err"
    assert "boom" in terminado["run"]["message"]

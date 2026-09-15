"""
Tests de `RunGate` — el lector-escritor de arranques.

Cada test controla el orden con `asyncio.Event`, no con `sleep` a ciegas: un
timing basado en sleeps es exactamente el tipo de test que pasa en la máquina
de uno y flaquea en CI. `asyncio.run()` alcanza; no hace falta pytest-asyncio
para esto.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp.run_gate import RunGate, run_with_gate  # noqa: E402


def test_dos_lectores_corren_juntos():
    async def main():
        gate = RunGate()
        orden: list[str] = []

        async def lector(nombre: str):
            async with gate.shared():
                orden.append(f"{nombre}:in")
                await asyncio.sleep(0.01)
                orden.append(f"{nombre}:out")

        await asyncio.gather(lector("a"), lector("b"))

        # Los dos entraron antes de que cualquiera saliera: conviven de verdad.
        assert orden[0].endswith(":in")
        assert orden[1].endswith(":in")
        assert gate.lectores == 0

    asyncio.run(main())


def test_escritor_espera_a_que_drenen_los_lectores():
    async def main():
        gate = RunGate()
        orden: list[str] = []
        lector_adentro = asyncio.Event()
        dejar_salir = asyncio.Event()

        async def lector():
            async with gate.shared():
                orden.append("lector:in")
                lector_adentro.set()
                await dejar_salir.wait()
                orden.append("lector:out")

        async def escritor():
            await lector_adentro.wait()
            orden.append("escritor:esperando")
            async with gate.exclusive():
                orden.append("escritor:in")

        t1 = asyncio.create_task(lector())
        t2 = asyncio.create_task(escritor())

        await lector_adentro.wait()
        await asyncio.sleep(0.01)  # darle tiempo al escritor a encolarse
        assert orden == ["lector:in", "escritor:esperando"]

        dejar_salir.set()
        await asyncio.gather(t1, t2)

        assert orden == ["lector:in", "escritor:esperando", "lector:out", "escritor:in"]

    asyncio.run(main())


def test_lector_nuevo_espera_si_hay_un_escritor_esperando_o_corriendo():
    async def main():
        gate = RunGate()
        orden: list[str] = []
        lector1_adentro = asyncio.Event()
        dejar_salir_lector1 = asyncio.Event()
        escritor_encolado = asyncio.Event()

        async def lector1():
            async with gate.shared():
                orden.append("l1:in")
                lector1_adentro.set()
                await dejar_salir_lector1.wait()
                orden.append("l1:out")

        async def escritor():
            await lector1_adentro.wait()
            escritor_encolado.set()
            async with gate.exclusive():
                orden.append("escritor:in")
                await asyncio.sleep(0.01)
                orden.append("escritor:out")

        async def lector2():
            await escritor_encolado.wait()
            await asyncio.sleep(0.01)  # asegurar que el escritor ya está en la cola
            async with gate.shared():
                orden.append("l2:in")

        t1 = asyncio.create_task(lector1())
        t2 = asyncio.create_task(escritor())
        t3 = asyncio.create_task(lector2())

        await escritor_encolado.wait()
        await asyncio.sleep(0.02)
        dejar_salir_lector1.set()
        await asyncio.gather(t1, t2, t3)

        # El escritor entra y sale entero antes de que l2 pueda entrar: un
        # lector nuevo no se cuela mientras el escritor espera o corre.
        assert orden.index("escritor:out") < orden.index("l2:in")

    asyncio.run(main())


def test_dos_escritores_se_serializan():
    async def main():
        gate = RunGate()
        orden: list[str] = []

        async def escritor(nombre: str):
            async with gate.exclusive():
                orden.append(f"{nombre}:in")
                await asyncio.sleep(0.01)
                orden.append(f"{nombre}:out")

        await asyncio.gather(escritor("a"), escritor("b"))

        primer_out = min(orden.index("a:out"), orden.index("b:out"))
        segundo_in = max(orden.index("a:in"), orden.index("b:in"))
        assert segundo_in > primer_out
        assert not gate.escritor_corriendo

    asyncio.run(main())


def test_libera_el_gate_aunque_el_cuerpo_explote():
    async def main():
        gate = RunGate()

        with pytest.raises(RuntimeError):
            async with gate.shared():
                raise RuntimeError("boom")
        assert gate.lectores == 0

        with pytest.raises(RuntimeError):
            async with gate.exclusive():
                raise RuntimeError("boom")
        assert not gate.escritor_corriendo

        # El gate sigue sirviendo después de una excepción: no queda trabado.
        async with gate.shared():
            pass

    asyncio.run(main())


# ── run_with_gate: el punto de integración con Instance ──────────────────


def test_run_with_gate_es_concurrente_si_instance_no_declara_el_metodo():
    """
    Hasta que `Instance.requires_exclusive_run` llegue del núcleo (issue #8),
    ningún flujo es exclusivo. `run_with_gate` no debe romper contra un
    `Instance` que todavía no lo tiene.
    """

    class InstanceSinElMetodoTodavia:
        def run(self, flow_name, case_id, **kwargs):
            return f"corrió {flow_name}/{case_id}"

    async def main():
        gate = RunGate()
        resultado = await run_with_gate(InstanceSinElMetodoTodavia(), gate, "f", "1")
        assert resultado == "corrió f/1"
        assert gate.lectores == 0

    asyncio.run(main())


def test_run_with_gate_usa_exclusive_si_instance_lo_declara():
    llamadas: list[str] = []

    class InstanceConElMetodo:
        def requires_exclusive_run(self, flow_name):
            return flow_name == "pesado"

        def run(self, flow_name, case_id, **kwargs):
            llamadas.append(flow_name)
            return "ok"

    async def main():
        gate = RunGate()
        # Mientras corre, el flujo exclusivo tiene que verse como escritor:
        # ocupamos el gate desde afuera y confirmamos que run_with_gate espera.
        lector_adentro = asyncio.Event()
        seguir = asyncio.Event()

        async def ocupar_como_lector():
            async with gate.shared():
                lector_adentro.set()
                await seguir.wait()

        tarea = asyncio.create_task(ocupar_como_lector())
        await lector_adentro.wait()

        corrida = asyncio.create_task(
            run_with_gate(InstanceConElMetodo(), gate, "pesado", "1")
        )
        await asyncio.sleep(0.01)
        assert llamadas == []  # todavía no corrió: está esperando que el lector salga

        seguir.set()
        resultado = await corrida
        await tarea

        assert resultado == "ok"
        assert llamadas == ["pesado"]

    asyncio.run(main())

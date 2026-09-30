"""
Decisión manual (core#37): lo que la webapp expone alrededor de un run en
espera.

La pausa y el retomar son del núcleo. Lo que se prueba acá es lo de la app:
que diga que no puede cuando el núcleo vendorizado no sabe pausar (en vez de
un 500 o un botón que no hace nada), que una fila en espera no arranque otra
corrida encima, y que el resume y el descarte lleguen al núcleo y vuelvan con
el run. El núcleo que sí sabe se imita con una subclase de `Instance` que
cumple el contrato del issue.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.flow.executor import RunResult  # noqa: E402
from backend.core.instance import Instance  # noqa: E402
from backend.core.users import UserError  # noqa: E402
from webapp.routes import core_api  # noqa: E402

FLUJO = (
    "flowchart TD\n"
    "    SN(inicio)\n"
    "    D1{Revisión § aprobado}\n"
    "    N2[\"Seguir § flow.retry_gate\"]\n"
    "    SN --> D1\n"
    "    D1 -->|si| N2\n"
)


class InstanciaQuePausa(Instance):
    """Imita el contrato de core#37: `resume` y `discard_wait`."""

    llamadas: list = []

    def resume(self, run_id, value, *, actor=None):
        type(self).llamadas.append(("resume", run_id, value, actor))
        if value not in ("si", "no"):
            raise ValueError(f'"{value}" no es ninguna rama de la decisión')
        if run_id == "no-espera":
            raise UserError("El run no está esperando una decisión")
        return RunResult(run_id=run_id, case_id="AP1", status="ok", message="ok")

    def discard_wait(self, run_id, *, actor=None):
        type(self).llamadas.append(("descartar", run_id, actor))
        return RunResult(run_id=run_id, case_id="AP1", status="err", message="Decisión descartada")


def _cliente(tmp_path, clase=Instance):
    core_api._instance.close()
    core_api._instance = clase(tmp_path)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _guardar_en_espera(case_id="AP1", source="casos", run_id="r-espera"):
    resultado = RunResult(run_id=run_id, case_id=case_id, status=core_api.ESPERANDO,
                          message="Esperando decisión en D1")
    core_api._instance.runs.save(resultado, flow="f", source=source)


def test_sin_soporte_del_nucleo_lo_dice_en_vez_de_fingir(tmp_path):
    client = _cliente(tmp_path)
    assert client.get("/api/core/capacidades").json() == {"decision_manual": False}

    r = client.post("/api/core/runs/r1/resume", json={"value": "si"})
    assert r.status_code == 501
    assert "core#37" in r.json()["detail"]
    assert client.post("/api/core/runs/r1/descartar", json={}).status_code == 501


def test_con_soporte_resume_y_descarte_llegan_al_nucleo(tmp_path):
    InstanciaQuePausa.llamadas = []
    client = _cliente(tmp_path, InstanciaQuePausa)
    assert client.get("/api/core/capacidades").json() == {"decision_manual": True}

    r = client.post("/api/core/runs/r-espera/resume", json={"value": "si", "actor": "ana"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert ("resume", "r-espera", "si", "ana") in InstanciaQuePausa.llamadas

    r = client.post("/api/core/runs/r-espera/descartar", json={"actor": "ana"})
    assert r.status_code == 200
    assert r.json()["status"] == "err"
    assert ("descartar", "r-espera", "ana") in InstanciaQuePausa.llamadas


def test_un_valor_que_no_es_rama_es_400_y_un_run_que_no_espera_409(tmp_path):
    client = _cliente(tmp_path, InstanciaQuePausa)
    r = client.post("/api/core/runs/r-espera/resume", json={"value": "quizas"})
    assert r.status_code == 400
    assert "ninguna rama" in r.json()["detail"]

    r = client.post("/api/core/runs/no-espera/resume", json={"value": "si"})
    assert r.status_code == 409


def test_una_fila_en_espera_no_arranca_otra_corrida(tmp_path):
    client = _cliente(tmp_path)
    core_api._instance.workflows.save_mmd("f", FLUJO)
    _guardar_en_espera()

    for ruta in ("/api/core/run", "/api/core/runs"):
        r = client.post(ruta, json={"flow": "f", "case_id": "AP1", "source": "casos", "row": {}})
        assert r.status_code == 409, ruta
        detalle = r.json()["detail"]
        assert detalle["esperando"] is True
        assert detalle["run_id"] == "r-espera"
        assert "decisión pendiente" in detalle["message"]


def test_otra_fila_de_la_misma_fuente_corre_normal(tmp_path):
    client = _cliente(tmp_path)
    core_api._instance.workflows.save_mmd("f", "flowchart TD\n    SN(inicio)\n")
    _guardar_en_espera(case_id="AP1")

    r = client.post("/api/core/run", json={"flow": "f", "case_id": "AP2", "source": "casos", "row": {}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

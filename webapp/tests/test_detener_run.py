"""
Detener un run en vuelo, y que una fila no corra dos veces a la vez.

Las dos salen del mismo caso: una fila ejecutada desde otra PC se veía arrancar
en la original y nada impedía volver a ejecutarla. El servidor es el que tiene
que decir no —la grilla de la otra PC puede no haber sondeado todavía—, y si
algo está mal tiene que poder frenarse aunque quede por la mitad.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402


def _cliente(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def test_una_fila_que_ya_corre_no_arranca_de_nuevo(tmp_path):
    client = _cliente(tmp_path)
    core_api._instance.workflows.save_mmd("f", "flowchart TD\n    SN(inicio)\n")
    ticket = core_api._en_vuelo.empezar("AP962", "f", source="casos")
    try:
        r = client.post("/api/core/run", json={"flow": "f", "case_id": "AP962", "source": "casos", "row": {}})
        assert r.status_code == 409
        assert r.json()["detail"]["ticket"] == ticket
        assert "ya está corriendo" in r.json()["detail"]["message"]
    finally:
        core_api._en_vuelo.terminar(ticket)


def test_detener_pone_la_marca_y_un_ticket_terminado_da_404(tmp_path):
    client = _cliente(tmp_path)
    ticket = core_api._en_vuelo.empezar("AP962", "f", source="casos")

    r = client.post(f"/api/core/runs/en-vuelo/{ticket}/stop")
    assert r.status_code == 200
    assert core_api._en_vuelo.cancelado(ticket) is True
    assert client.get("/api/core/runs/en-vuelo").json()[0]["cancelando"] is True

    core_api._en_vuelo.terminar(ticket)
    assert client.post(f"/api/core/runs/en-vuelo/{ticket}/stop").status_code == 404

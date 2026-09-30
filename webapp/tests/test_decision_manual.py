"""
Decisión manual (core#37, núcleo v0.3.1-beta.18): lo que la webapp expone
alrededor de un run en espera, contra el núcleo real.

La pausa y el retomar son del núcleo; lo que se prueba acá es lo de la app:
que la capacidad salga del catálogo, que `resume`/`descartar` lleguen al
núcleo y vuelvan con el run, que los errores del núcleo —todos `UserError`—
salgan con un código que la grilla pueda distinguir, y que una fila en espera
no arranque otra corrida encima (ni como 403, que es lo que hacía el
`except UserError` de `/run` con `PendingDecision`).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402

FLUJO = (
    "flowchart TD\n"
    "    SN1(inicio)\n"
    '    N1["Antes § marca.poner | x=antes-{id}"]\n'
    "    D1{Revisión del diseño § aprobado | manual | ayuda=Mirá el PDF antes de elegir}\n"
    '    N2["Mover § marca.poner | x=si {visto}"]\n'
    '    N3["Rehacer § marca.poner | x=no {visto}"]\n'
    "    SN1 --> N1\n"
    "    N1 --> D1\n"
    "    D1 -->|si| N2\n"
    "    D1 -->|rehacer| N3\n"
)


def _cliente(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path, local_plugins={"marca": "webapp.tests.plugin_marca:PLUGIN"})
    core_api._instance.workflows.save("revision", FLUJO)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _correr(client, case_id="AP1"):
    return client.post("/api/core/run", json={
        "flow": "revision", "case_id": case_id, "source": "casos", "row": {"id": case_id},
    })


def test_la_capacidad_sale_del_catalogo(tmp_path):
    client = _cliente(tmp_path)
    assert client.get("/api/core/capacidades").json() == {"decision_manual": True}


def test_la_corrida_se_pausa_y_trae_lo_que_el_modal_necesita(tmp_path):
    client = _cliente(tmp_path)
    r = _correr(client)
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "waiting"
    espera = run["waiting"]
    assert espera["variable"] == "aprobado"
    assert espera["display"] == "Revisión del diseño"
    assert espera["ayuda"] == "Mirá el PDF antes de elegir"
    assert [(o["value"], o["to"], o["to_display"], o["to_fn"]) for o in espera["options"]] == [
        ("si", "N2", "Mover", "marca.poner"), ("rehacer", "N3", "Rehacer", "marca.poner"),
    ]
    # El detalle —lo que lee el modal— trae lo mismo, y no el checkpoint.
    detalle = client.get(f"/api/core/runs/{run['run_id']}").json()
    assert detalle["waiting"] == espera
    assert "checkpoint" not in detalle and "flow_text" not in str(detalle)


def test_retomar_sigue_por_la_rama_elegida_con_el_contexto_de_antes(tmp_path):
    client = _cliente(tmp_path)
    run_id = _correr(client).json()["run_id"]

    r = client.post(f"/api/core/runs/{run_id}/resume", json={"value": "rehacer"})
    assert r.status_code == 200
    run = r.json()
    assert run["run_id"] == run_id
    assert run["status"] == "ok"
    nodos = [t["node_id"] for t in run["trace"]]
    assert nodos == ["N1", "D1", "N3"]
    n3 = run["trace"][-1]
    assert n3["outputs"]["visto"] == "no antes-AP1"  # la salida de N1 sobrevivió a la pausa
    # Terminó: ya no está en vuelo y la fila se puede volver a correr.
    assert client.get("/api/core/runs/en-vuelo").json() == []
    assert _correr(client).json()["status"] == "waiting"


def test_una_fila_en_espera_no_arranca_otra_corrida(tmp_path):
    client = _cliente(tmp_path)
    run_id = _correr(client).json()["run_id"]

    for ruta in ("/api/core/run", "/api/core/runs"):
        r = client.post(ruta, json={"flow": "revision", "case_id": "AP1", "source": "casos", "row": {"id": "AP1"}})
        assert r.status_code == 409, ruta
        detalle = r.json()["detail"]
        assert detalle["esperando"] is True
        assert detalle["run_id"] == run_id


def test_pending_decision_del_nucleo_es_409_y_no_403(tmp_path):
    # Sin fuente la espera no se encuentra por fila (`_frenar_si_espera` mira
    # la fuente), así que el que frena es el núcleo con PendingDecision. Antes
    # el `except UserError` de `/run` lo devolvía como un permiso negado.
    client = _cliente(tmp_path)
    cuerpo = {"flow": "revision", "case_id": "AP9", "source": "", "row": {"id": "AP9"}}
    run_id = client.post("/api/core/run", json=cuerpo).json()["run_id"]
    otra = client.post("/api/core/run", json={**cuerpo, "source": "otra"})
    assert otra.status_code == 409
    assert otra.json()["detail"]["run_id"] == run_id


def test_otra_fila_corre_mientras_una_espera(tmp_path):
    client = _cliente(tmp_path)
    _correr(client, "AP1")
    r = _correr(client, "AP2")
    assert r.status_code == 200
    assert r.json()["status"] == "waiting"  # llegó a su propia decisión: el hilo no quedó tomado


def test_errores_del_nucleo_con_codigos_distinguibles(tmp_path):
    client = _cliente(tmp_path)
    run_id = _correr(client).json()["run_id"]

    r = client.post(f"/api/core/runs/{run_id}/resume", json={"value": "quizas"})
    assert r.status_code == 409
    assert '"si"' in r.json()["detail"] and '"rehacer"' in r.json()["detail"]  # el mensaje lista las opciones
    assert client.get(f"/api/core/runs/{run_id}").json()["status"] == "waiting"  # no tocó el run

    assert client.post("/api/core/runs/no-existe/resume", json={"value": "si"}).status_code == 404
    assert client.post("/api/core/runs/no-existe/descartar", json={}).status_code == 404


def test_descartar_cierra_la_espera_y_la_fila_vuelve_a_correr(tmp_path):
    client = _cliente(tmp_path)
    run_id = _correr(client).json()["run_id"]

    r = client.post(f"/api/core/runs/{run_id}/descartar", json={"actor": "local"})
    assert r.status_code == 200
    assert r.json()["status"] == "err"
    assert r.json()["error_kind"] == "discarded"
    assert client.post(f"/api/core/runs/{run_id}/resume", json={"value": "si"}).status_code == 409
    assert _correr(client).status_code == 200


def test_sin_soporte_del_nucleo_lo_dice_en_vez_de_fingir(tmp_path, monkeypatch):
    client = _cliente(tmp_path)
    monkeypatch.setattr(core_api, "_soporta_decision_manual", lambda: False)
    assert client.get("/api/core/capacidades").json() == {"decision_manual": False}
    r = client.post("/api/core/runs/r1/resume", json={"value": "si"})
    assert r.status_code == 501
    assert "core#37" in r.json()["detail"]
    assert client.post("/api/core/runs/r1/descartar", json={}).status_code == 501

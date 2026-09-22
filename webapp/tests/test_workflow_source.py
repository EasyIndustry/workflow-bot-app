"""
`PUT /workflows/{name}` lleva `source`, la fuente para la que el flujo está
pensado (núcleo v0.3.1-beta.11, core#31).

Antes un flujo no tenía dónde anotar su fuente y el editor tenía que inferirla
de la última corrida para ofrecer las columnas de la fila; un flujo nuevo, que
es cuando más se escriben tarjetas, se quedaba sin lista. Lo que se prueba es
el contrato con la vista: lo que se manda vuelve en el flujo, en la lista y en
la cabecera `%%` del archivo, y guardar sin repetirlo no lo borra.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402

FLUJO = "flowchart TD\n    SN1([inicio])\n"


def _cliente(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path, local_plugins=core_api.LOCAL_PLUGINS)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _guardar(client, nombre, **cuerpo):
    r = client.put(f"/api/core/workflows/{nombre}", json={"content": FLUJO, **cuerpo})
    assert r.status_code == 200, r.text
    return r.json()["workflow"]


def test_la_fuente_declarada_vuelve_en_el_flujo_la_lista_y_la_cabecera(tmp_path):
    client = _cliente(tmp_path)

    wf = _guardar(client, "casos", source="casos-nuevos")
    assert wf["source"] == "casos-nuevos"

    listado = client.get("/api/core/workflows").json()
    assert [w["source"] for w in listado if w["name"] == "casos"] == ["casos-nuevos"]

    # La cabecera es parte del archivo: el flujo viaja entre Bots con su fuente.
    exportado = core_api._instance.workflows.to_mmd("casos")
    assert "%% source: casos-nuevos" in exportado


def test_guardar_sin_fuente_la_deja_vacia_y_sin_declarar_no_hay_cabecera(tmp_path):
    client = _cliente(tmp_path)
    wf = _guardar(client, "suelto")
    assert wf["source"] == ""
    assert "%% source" not in core_api._instance.workflows.to_mmd("suelto")


def test_cambiar_la_fuente_reemplaza_la_anterior(tmp_path):
    client = _cliente(tmp_path)
    _guardar(client, "casos", source="casos-nuevos")
    wf = _guardar(client, "casos", source="casos-viejos")
    assert wf["source"] == "casos-viejos"
    assert "casos-nuevos" not in core_api._instance.workflows.to_mmd("casos")

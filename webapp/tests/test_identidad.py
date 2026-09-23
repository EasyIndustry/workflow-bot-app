"""
Cómo se llama este Bot (`webapp/identidad.py`, `GET`/`PUT /identidad`).

El caso que motiva esto: varios Bots abiertos en pestañas del mismo
navegador son indistinguibles por el título ("Bot" siempre). El nombre lo
guarda esta instalación y viaja por `/overview` para que `main.js` titule la
pestaña sin depender de que haya ningún plugin instalado.
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


def test_sin_nombre_puesto_viene_vacio_en_los_dos_lados(tmp_path):
    client = _cliente(tmp_path)

    assert client.get("/api/core/identidad").json()["nombre"] == ""
    assert client.get("/api/core/overview").json()["nombre"] == ""


def test_guardar_recorta_espacios_y_se_ve_en_overview(tmp_path):
    client = _cliente(tmp_path)

    r = client.put("/api/core/identidad", json={"nombre": "  Bot de Producción  "})
    assert r.status_code == 200
    assert r.json()["nombre"] == "Bot de Producción"

    assert client.get("/api/core/identidad").json()["nombre"] == "Bot de Producción"
    assert client.get("/api/core/overview").json()["nombre"] == "Bot de Producción"


def test_guardar_vacio_borra_en_vez_de_dejar_una_fila_vacia(tmp_path):
    client = _cliente(tmp_path)
    client.put("/api/core/identidad", json={"nombre": "Bot de Producción"})

    r = client.put("/api/core/identidad", json={"nombre": "   "})

    assert r.json()["nombre"] == ""
    assert client.get("/api/core/identidad").json()["nombre"] == ""


def test_no_depende_de_ningun_plugin_instalado(tmp_path):
    """
    La colección vive bajo el plugin "webapp" (`resource_store("webapp", ...)`,
    igual que `webapp/updates.py`), no bajo el `bots` del catálogo: una
    instalación pelada, sin plugins, tiene que poder nombrarse igual.
    """
    client = _cliente(tmp_path)
    plugins = core_api._instance.registry.catalog()["plugins"]
    assert [p for p in plugins if p["source"] != "builtin"] == []

    r = client.put("/api/core/identidad", json={"nombre": "Bot pelado"})

    assert r.json()["nombre"] == "Bot pelado"

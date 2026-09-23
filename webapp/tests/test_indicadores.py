"""
El check persistente de una fila (`webapp/indicadores.py`).

Una Action de fila (`Action.resource`) puede devolver `outputs.indicador`,
en el ok y en el err. Se persiste en el servidor —no en el navegador de
quien apretó el botón, ver el docstring de `indicadores.py`— y
`GET /resources/{plugin}/{resource}` lo suma a cada item como
`_indicador`, calculado ahí y no guardado en la fila del plugin dueño de
la colección.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402

PLUGIN = "conexiones_test"
COLECCION = "conexiones"
RUTA = f"/api/core/resources/{PLUGIN}/{COLECCION}"


@pytest.fixture
def client(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(
        tmp_path,
        local_plugins={**core_api.LOCAL_PLUGINS,
                       PLUGIN: "webapp.tests.plugin_con_accion_de_fila:PLUGIN"},
    )
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    yield TestClient(app)


def _guardar(client, nombre, falla=False):
    r = client.put(f"{RUTA}/{nombre}", json={"item": {"nombre": nombre, "falla": falla}})
    assert r.status_code == 200, r.text


def _probar(client, nombre):
    r = client.post(f"/api/core/actions/{PLUGIN}/probar", json={"item": nombre})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _item(client, nombre):
    (fila,) = [i for i in client.get(RUTA).json()["items"] if i["nombre"] == nombre]
    return fila


def test_sin_probar_nunca_no_hay_indicador(client):
    _guardar(client, "prod")

    assert _item(client, "prod").get("_indicador") is None


def test_un_ok_deja_el_indicador_en_el_listado(client):
    _guardar(client, "prod")

    resultado = _probar(client, "prod")
    assert resultado["status"] == "ok"

    marca = _item(client, "prod")["_indicador"]
    assert marca["estado"] == "ok"
    assert marca["texto"] == "contestó"
    assert marca["updated_at"]


def test_un_err_tambien_deja_indicador_y_no_se_pierde_al_relistar(client):
    """El doc lo pide explícito: el check también se guarda en el error, no sólo en el ok."""
    _guardar(client, "prod", falla=True)

    resultado = _probar(client, "prod")
    assert resultado["status"] == "err"

    marca = _item(client, "prod")["_indicador"]
    assert marca["estado"] == "err"
    assert marca["texto"] == "no contestó"

    # Releer no lo pierde: no es un dato que viaje sólo en la respuesta de la Action.
    marca_otra_vez = _item(client, "prod")["_indicador"]
    assert marca_otra_vez == marca


def test_un_ok_posterior_apaga_el_check_de_error(client):
    _guardar(client, "prod", falla=True)
    _probar(client, "prod")
    assert _item(client, "prod")["_indicador"]["estado"] == "err"

    client.put(f"{RUTA}/prod", json={"item": {"nombre": "prod", "falla": False}})
    _probar(client, "prod")

    assert _item(client, "prod")["_indicador"]["estado"] == "ok"


def test_borrar_el_item_borra_su_indicador(client):
    _guardar(client, "prod")
    _probar(client, "prod")
    assert _item(client, "prod").get("_indicador")

    r = client.delete(f"{RUTA}/prod")
    assert r.status_code == 200, r.text

    # No queda huérfano en la colección de indicadores: otro item con el mismo
    # nombre más adelante no heredaría un check que no le corresponde.
    _guardar(client, "prod")
    assert _item(client, "prod").get("_indicador") is None


def test_no_depende_de_ningun_plugin_bots(client):
    """El mecanismo es genérico: cualquier plugin con una Action de fila lo tiene, no sólo `bots`."""
    assert PLUGIN != "bots"
    _guardar(client, "prod")
    _probar(client, "prod")
    assert _item(client, "prod")["_indicador"]["estado"] == "ok"

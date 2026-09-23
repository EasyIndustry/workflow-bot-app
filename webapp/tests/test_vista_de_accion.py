"""
La forma de `outputs.vista`, que es contrato entre un plugin y la pantalla.

El que dibuja es JavaScript (`views/plugins.js`) y no lo ve pytest, así que lo
que se fija acá es **la forma**: qué claves tiene que traer un plugin para que
la app le dibuje una tabla con selección. Si alguien cambia el renderer y deja
de leer una de éstas, o si alguien cambia estos nombres, el plugin del catálogo
que ya los usa deja de dibujarse — y esto es lo que lo dice.

El recorrido de verdad —tildar, confirmar, disparar la acción de seguimiento—
se corre en el navegador por CDP; esto no lo reemplaza.
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

DEMO = "vista_demo"


@pytest.fixture
def client(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(
        tmp_path,
        local_plugins={**core_api.LOCAL_PLUGINS,
                       DEMO: "webapp.tests.plugin_vista_demo:PLUGIN"},
    )
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    yield TestClient(app)


def _correr(client, accion, params):
    r = client.post(f"/api/core/actions/{DEMO}/{accion}", json={"params": params})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_una_accion_puede_devolver_una_vista(client):
    resultado = _correr(client, "comparar", {"destino": "Impresión 2"})

    vista = resultado["outputs"]["vista"]
    assert vista["tipo"] == "tabla"
    assert vista["clave"] == "clave"
    assert [c["campo"] for c in vista["columnas"]] == ["clave", "estado", "campos"]


def test_una_fila_puede_no_ser_elegible_y_traer_su_nota(client):
    """
    Las dos claves reservadas. `_elegible: false` es la fila que no tiene nada
    que hacer; `_nota` es dónde se explica por qué —el caso de un item con
    campos secretos, que no se puede comparar con nada.
    """
    vista = _correr(client, "comparar", {"destino": "x"})["outputs"]["vista"]
    por_clave = {f["clave"]: f for f in vista["filas"]}

    assert por_clave["QA viejo"]["_elegible"] is False
    assert "secretos" in por_clave["conexión SAP"]["_nota"]
    # El resto no las declara: el default es que se puedan elegir.
    assert "_elegible" not in por_clave["cierre"]


def test_la_seleccion_dice_a_que_accion_va_y_con_que_contexto(client):
    """
    `params` es lo que la acción de seguimiento necesita y el botón no sabe: el
    destino, qué se comparó. Sin esto, migrar no sabría a dónde.
    """
    seleccion = _correr(client, "comparar", {"destino": "Impresión 2"})["outputs"]["vista"]["seleccion"]

    assert seleccion["accion"] == "migrar"
    assert seleccion["param"] == "claves"
    assert seleccion["params"] == {"destino": "Impresión 2"}
    assert "a ciegas" in seleccion["aviso"]


def test_la_accion_de_seguimiento_existe_y_es_peligrosa(client):
    """
    Que exista: el botón la llama por nombre y un nombre que no está sería un
    botón que no hace nada. Que sea `dangerous`: es lo que hace que la pantalla
    pregunte antes de escribir en otra máquina.
    """
    # Del mismo `GET /tools` del que la pantalla dibuja todo: si la Action no
    # sale por ahí, el front no la ve y el botón no existiría.
    catalogo = client.get("/api/core/tools").json()
    plugin = next(p for p in catalogo["plugins"] if p["name"] == DEMO)
    acciones = {a["name"]: a for a in plugin["actions"]}

    assert "migrar" in acciones
    assert acciones["migrar"]["dangerous"] is True


def test_la_accion_de_seguimiento_recibe_lo_tildado(client):
    resultado = _correr(client, "migrar", {"destino": "Impresión 2",
                                           "claves": ["alta de caso", "cierre"]})

    assert "Se migraron 2" in resultado["message"]
    assert [f["clave"] for f in resultado["outputs"]["vista"]["filas"]] == [
        "alta de caso", "cierre"]

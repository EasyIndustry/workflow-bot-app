"""
Los campos `secret` de una colección no salen por la API HTTP (#3).

`GET /resources/{plugin}/{resource}` y `.../{key}` devolvían descifrado lo que
un `Resource` declaró `secret`: eran el único de los cuatro caminos de lectura
que no lo tapaba, contra lo que dicen el docstring de `resource_items_masked`
("lo que puede salir por el servidor MCP o cualquier otra API") y la regla del
repo ("los secretos no salen por ninguna API"). Y sin autenticación, con una
instalación que escucha en toda la red local porque el acceso directo arranca
con `--red`.

La otra mitad, y la que puede doler más: tapar al leer sin tocar el PUT
convierte cualquier edición en pérdida de datos, porque la pantalla devuelve el
`None` que acaba de leer. Por eso los dos lados se prueban juntos.
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

PLUGIN = "cuentas_test"
COLECCION = "cuentas"
RUTA = f"/api/core/resources/{PLUGIN}/{COLECCION}"


@pytest.fixture
def client(tmp_path):
    core_api._instance.close()
    core_api._instance = Instance(
        tmp_path,
        local_plugins={**core_api.LOCAL_PLUGINS,
                       PLUGIN: "webapp.tests.plugin_con_secreto:PLUGIN"},
    )
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    yield TestClient(app)


def _guardar(client, nombre, item):
    r = client.put(f"{RUTA}/{nombre}", json={"item": item})
    assert r.status_code == 200, r.text
    return r.json()


def _item_guardado(client, nombre):
    """Lo que hay en la base de verdad, sin pasar por la API."""
    store = core_api._store(PLUGIN, COLECCION)
    return store.read(nombre)


def test_listar_no_devuelve_el_secreto(client):
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    r = client.get(RUTA)

    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["token"] is None
    # Lo que no es secreto sigue saliendo: tapar no es dejar de listar.
    assert item["name"] == "prod"
    assert item["url"] == "https://api.test"
    assert "abc123" not in r.text


def test_leer_uno_tampoco_lo_devuelve(client):
    """Saberse la clave era el atajo que dejaba la ruta de listar tapada sola."""
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    r = client.get(f"{RUTA}/prod")

    assert r.status_code == 200, r.text
    assert r.json()["token"] is None
    assert r.json()["url"] == "https://api.test"
    assert "abc123" not in r.text


def test_la_respuesta_del_put_tampoco(client):
    """Puede traer un secreto que quien llamó no mandó: el que se conservó."""
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    devuelto = _guardar(client, "prod", {"name": "prod", "url": "https://otra.test", "token": None})

    assert devuelto["token"] is None
    assert devuelto["url"] == "https://otra.test"


def test_guardar_sin_el_secreto_no_lo_borra(client):
    """
    El caso que convierte este arreglo en pérdida de datos si se hace a medias:
    la pantalla lee el item con el token en `None` y lo vuelve a mandar así.
    """
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    leido = client.get(f"{RUTA}/prod").json()
    assert leido["token"] is None
    _guardar(client, "prod", {"name": "prod", "url": "https://otra.test", "token": leido["token"]})

    guardado = _item_guardado(client, "prod")
    assert guardado["token"] == "abc123"
    assert guardado["url"] == "https://otra.test"


def test_un_campo_que_no_esta_tampoco_borra(client):
    """Mandar el item sin la clave del secreto es lo mismo que mandarla en `None`."""
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    _guardar(client, "prod", {"name": "prod", "url": "https://otra.test"})

    assert _item_guardado(client, "prod")["token"] == "abc123"


def test_se_puede_vaciar_a_proposito_con_cadena_vacia(client):
    """
    Conservar en `None` no puede dejar sin forma de borrar un secreto. `""` es
    lo que manda un campo de texto borrado a mano, y sí lo vacía.
    """
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": ""})

    assert _item_guardado(client, "prod")["token"] == ""


def test_se_puede_cambiar_el_secreto(client):
    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    _guardar(client, "prod", {"name": "prod", "url": "https://api.test", "token": "nuevo"})

    assert _item_guardado(client, "prod")["token"] == "nuevo"


def test_un_item_nuevo_sin_secreto_se_crea_igual(client):
    """No hay item anterior del que conservar nada: no tiene que explotar."""
    _guardar(client, "nueva", {"name": "nueva", "url": "https://api.test"})

    assert _item_guardado(client, "nueva").get("token") in (None, "")


def test_una_coleccion_sin_campos_secretos_sale_entera(client):
    """El `connections` de la app es este caso: nada que tapar, nada que cambie."""
    r = client.put("/api/core/resources/connections/actions/Comentario",
                   json={"item": {"name": "Comentario", "url": "https://api.test/x",
                                  "method": "POST"}})
    assert r.status_code == 200, r.text

    listado = client.get("/api/core/resources/connections/actions").json()["items"]

    assert listado[0]["url"] == "https://api.test/x"

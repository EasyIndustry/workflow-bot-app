"""
`GET /tools/{tool}/params-extra`: qué params extra acepta un nodo según lo que
ya tiene elegido.

Existe porque un tool con `extra_params` dice que acepta más de los declarados
pero no cuáles — los de Connections dependen de las `{variables}` que la Action
elegida tenga en la URL y el payload. Sin esto había que abrir la otra pantalla,
anotar los nombres y escribirlos a mano en el `.mmd`.

Lo que se prueba es el contrato con la tarjeta del flujo, que pregunta por
cualquier tool que acepte extras sin conocer ninguno por nombre: el que no tiene
cómo describirlos contesta la lista vacía, no un error.
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
    core_api._instance = Instance(tmp_path, local_plugins=core_api.LOCAL_PLUGINS)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _guardar_action(client, nombre, item):
    r = client.put(f"/api/core/resources/connections/actions/{nombre}", json={"item": item})
    assert r.status_code == 200, r.text


def _pedir(client, tool, **params):
    r = client.get(f"/api/core/tools/{tool}/params-extra", params=params)
    assert r.status_code == 200, r.text
    return r.json()["params"]


def test_las_variables_de_la_action_elegida_llegan_como_params(tmp_path):
    client = _cliente(tmp_path)
    _guardar_action(client, "Comentario", {
        "name": "Comentario", "url": "https://api.test/bandeja/{id_externo}",
        "method": "POST", "payload": {"texto": "{texto}", "pais": "{pais}"},
    })

    extras = _pedir(client, "connections.llamar", connection="Comentario")

    assert [p["name"] for p in extras] == ["id_externo", "texto", "pais"]
    # Con la forma de un param del manifest: la tarjeta los dibuja con el mismo
    # campo que los declarados, sin un caso aparte.
    assert extras[0].keys() >= {"name", "type", "required", "default", "choices", "doc"}


def test_un_campo_con_literal_no_se_ofrece(tmp_path):
    """Ofrecer `"texto": ""` sería prometer un pisado que al ejecutar no pasa."""
    client = _cliente(tmp_path)
    _guardar_action(client, "Comentario", {
        "name": "Comentario", "url": "https://api.test/x", "method": "POST",
        "payload": {"texto": "", "pais": "{pais}"},
    })

    assert [p["name"] for p in _pedir(client, "connections.llamar", connection="Comentario")] == ["pais"]


def test_sin_conexion_elegida_o_inexistente_no_hay_nada_que_ofrecer(tmp_path):
    client = _cliente(tmp_path)

    assert _pedir(client, "connections.llamar") == []
    assert _pedir(client, "connections.llamar", connection="No existe") == []


def test_un_tool_sin_descriptor_contesta_vacio_y_no_rompe(tmp_path):
    """La tarjeta pregunta por todos los que aceptan extras; casi ninguno sabe."""
    client = _cliente(tmp_path)
    tools = client.get("/api/core/tools").json()["tools"]
    otro = next(t["id"] for t in tools if not t["id"].startswith("connections."))

    assert _pedir(client, otro) == []


def test_un_tool_que_no_existe_es_404(tmp_path):
    client = _cliente(tmp_path)
    assert client.get("/api/core/tools/no.existe/params-extra").status_code == 404


def test_el_catalogo_dice_de_que_coleccion_salen_los_valores(tmp_path):
    """
    Lo que hace que la tarjeta dibuje un buscador en vez de un texto pelado.

    Viaja en `GET /tools`, así que el front no pide nada nuevo para saberlo; y
    no entra en `choices`, que sí se valida — con una lista cerrada,
    `connection={variable}` dejaría de ser un valor válido.
    """
    client = _cliente(tmp_path)
    tools = {t["id"]: t for t in client.get("/api/core/tools").json()["tools"]}

    for tool in ("connections.llamar", "connections.llamar_y_fusionar"):
        [param] = [p for p in tools[tool]["params"] if p["name"] == "connection"]
        assert param["options_from"] == "actions"
        assert param["choices"] == []

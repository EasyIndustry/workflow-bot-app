"""
La primera visita de un navegador a la página pide limpiar lo guardado.

En una PC que corrió el Bot viejo en la misma dirección, Chrome y Edge servían
su página guardada aunque el servidor mandara la nueva, y la app se veía en
blanco pidiendo archivos que ya no existen. `Clear-Site-Data` se lo saca de
encima; la cookie de marca hace que sea una sola vez, porque "storage" también
borra el localStorage propio de la app.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from webapp import server  # noqa: E402


def _cliente():
    """Una app mínima con la misma decisión que `server.index`, sin levantar la instancia."""
    app = FastAPI()

    @app.get("/")
    def indice(request: Request):
        limpieza = server.limpieza_para(request.cookies)
        respuesta = PlainTextResponse("app", headers=limpieza)
        if limpieza:
            respuesta.set_cookie(server.COOKIE_LIMPIO, "1", max_age=3600, samesite="lax")
        return respuesta

    return TestClient(app)


def test_la_primera_visita_pide_borrar_cache_y_storage_y_deja_la_marca():
    r = _cliente().get("/")
    assert r.headers["Clear-Site-Data"] == '"cache", "storage"'
    assert server.COOKIE_LIMPIO in r.cookies


def test_con_la_marca_no_se_vuelve_a_borrar():
    cliente = _cliente()
    cliente.get("/")
    r = cliente.get("/")
    assert "Clear-Site-Data" not in r.headers


def test_la_decision_sola():
    assert server.limpieza_para({}) == {"Clear-Site-Data": '"cache", "storage"'}
    assert server.limpieza_para({server.COOKIE_LIMPIO: "1"}) == {}

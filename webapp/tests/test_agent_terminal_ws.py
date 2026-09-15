"""
Test de integración de `WS /api/core/agent/terminal`, contra un proveedor de
mentira (`sh`) — nunca contra un CLI de vendor real, que no está instalado en
ningún entorno de test.
"""

from __future__ import annotations

import importlib
import pathlib
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp import agent_providers, agent_sessions  # noqa: E402
from webapp.agent_terminal import TIENE_PTY  # noqa: E402
from webapp.routes import core_api  # noqa: E402

pytestmark = pytest.mark.skipif(not TIENE_PTY, reason="pty no disponible en esta plataforma")

PRUEBA = agent_providers.Proveedor(
    id="prueba",
    label="Prueba",
    binario="sh",
    instalar=("sh", "-c", "echo instalando-prueba"),
    login=("sh", "-c", "echo logueando-prueba; exit 0"),
)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    core_api._instance.close()
    core_api._instance = Instance(
        tmp_path, local_plugins={"connections": "webapp.connections.plugin:PLUGIN"}
    )
    monkeypatch.setattr(
        agent_providers, "proveedor", lambda id_: PRUEBA if id_ == "prueba" else None
    )
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _leer_todo(ws) -> bytes:
    recibido = b""
    while True:
        try:
            mensaje = ws.receive()
        except Exception:
            break
        if mensaje.get("type") == "websocket.close":
            break
        if "bytes" in mensaje and mensaje["bytes"] is not None:
            recibido += mensaje["bytes"]
        elif "text" in mensaje and mensaje["text"] is not None:
            recibido += mensaje["text"].encode()
    return recibido


def test_login_ok_registra_la_sesion(cliente):
    with cliente.websocket_connect(
        "/api/core/agent/terminal?provider=prueba&mode=login&actor=agente-mcp"
    ) as ws:
        salida = _leer_todo(ws)

    assert b"logueando-prueba" in salida
    item = agent_sessions.sesion_de(core_api._instance, "agente-mcp")
    assert item is not None
    assert item["provider"] == "prueba"
    assert item["hostname"] == agent_sessions.hostname_actual()


def test_proveedor_desconocido_cierra_con_error(cliente):
    with cliente.websocket_connect(
        "/api/core/agent/terminal?provider=no-existe&mode=login"
    ) as ws:
        mensaje = ws.receive_json()
        assert "error" in mensaje


def test_avisa_si_la_sesion_previa_era_de_otra_maquina(cliente, monkeypatch):
    monkeypatch.setattr(agent_sessions, "hostname_actual", lambda: "pc-vieja")
    agent_sessions.registrar_login(core_api._instance, "agente-mcp", "prueba")
    monkeypatch.setattr(agent_sessions, "hostname_actual", lambda: "pc-nueva")

    with cliente.websocket_connect(
        "/api/core/agent/terminal?provider=prueba&mode=login&actor=agente-mcp"
    ) as ws:
        primero = ws.receive_json()
        assert "aviso" in primero
        assert "pc-vieja" in primero["aviso"]
        _leer_todo(ws)


def test_install_no_registra_sesion(cliente):
    with cliente.websocket_connect(
        "/api/core/agent/terminal?provider=prueba&mode=install"
    ) as ws:
        salida = _leer_todo(ws)

    assert b"instalando-prueba" in salida
    assert agent_sessions.sesion_de(core_api._instance, "agente-mcp") is None

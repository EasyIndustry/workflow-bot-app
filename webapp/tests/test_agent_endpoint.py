"""
Test de `GET /api/core/agent` — la receta de conexión para un agente MCP.

No prueba nada de `backend/mcp` en sí (eso lo cubre `backend/tests/test_mcp.py`);
sólo que el endpoint arma correctamente `command`/`args`/`cwd`/`root` a partir
de una instancia real, contra un `root` temporal para no tocar la base del
repo.
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
    core_api._instance = Instance(
        tmp_path, local_plugins={"connections": "webapp.connections.plugin:PLUGIN"}
    )
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def test_la_conexion_apunta_a_este_interprete_y_a_este_root(tmp_path):
    client = _cliente(tmp_path)

    r = client.get("/api/core/agent")

    assert r.status_code == 200
    datos = r.json()
    # El MCP de la webapp, no backend.mcp pelado: pone root y `connections`.
    assert datos["connection"]["args"] == ["-m", "webapp.mcp_servidor"]
    assert datos["connection"]["command"] == sys.executable
    # cwd es donde está el código (de donde `backend` es importable), no el
    # `root` de datos: en una instalación son dos carpetas distintas, y con
    # el root de datos el servidor moría con "No module named 'backend'".
    assert datos["connection"]["cwd"] == str(core_api.REPO)
    assert (pathlib.Path(datos["connection"]["cwd"]) / "backend").is_dir()
    assert datos["connection"]["cwd"] != str(tmp_path)
    # Claude Code ignora `cwd` en .mcp.json: sin esto, en una instalación
    # reportaba CONNECTION_CLOSED porque `backend` no se importaba.
    assert datos["connection"]["env"] == {"PYTHONPATH": str(core_api.REPO), "BOT_ROOT": str(core_api.ROOT)}
    assert datos["root"] == str(tmp_path)


def test_con_pythonw_la_receta_usa_el_python_con_consola(tmp_path, monkeypatch):
    client = _cliente(tmp_path)
    falso = tmp_path / "rt"
    falso.mkdir()
    (falso / "python.exe").write_bytes(b"")
    monkeypatch.setattr(core_api.sys, "executable", str(falso / "pythonw.exe"))

    datos = client.get("/api/core/agent").json()

    assert datos["connection"]["command"] == str(falso / "python.exe")


def test_dice_si_falta_el_paquete_mcp(tmp_path, monkeypatch):
    client = _cliente(tmp_path)
    monkeypatch.setattr(core_api.importlib.util, "find_spec", lambda _n: None)

    datos = client.get("/api/core/agent").json()

    assert datos["mcp_instalado"] is False

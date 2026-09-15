"""
`webapp.mcp_servidor`: el MCP del núcleo con `root` y los plugins de la app
puestos por defecto. Sin esto, desde una instalación `check_flow` decía que
`connections.llamar` no existía y `root` caía en `backend/`.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

pytest.importorskip("mcp")

from webapp import mcp_servidor  # noqa: E402

RAIZ = r"C:\instalacion"
PLUGINS = {"connections": r"C:\programa\webapp\connections"}


def test_pone_root_y_plugins_si_la_tool_los_acepta():
    args = mcp_servidor.completar("check_flow", {"flow": "x"}, root=RAIZ, plugins=PLUGINS)
    assert args == {"flow": "x", "root": RAIZ, "plugins": PLUGINS}


def test_lo_que_manda_el_agente_gana():
    propios = {"root": r"D:\otra", "plugins": {"connections": r"D:\mia", "extra": r"D:\e.py"}}
    args = mcp_servidor.completar("check_flow", dict(propios), root=RAIZ, plugins=PLUGINS)
    assert args["root"] == r"D:\otra"
    assert args["plugins"] == {"connections": r"D:\mia", "extra": r"D:\e.py"}


def test_root_vacio_cuenta_como_no_pasado():
    args = mcp_servidor.completar("list_tools", {"root": ""}, root=RAIZ, plugins=PLUGINS)
    assert args["root"] == RAIZ


def test_tool_sin_esos_params_queda_igual():
    # list_ports no toma ni root ni plugins: agregárselos sería "argumentos
    # inválidos" del lado del núcleo.
    assert mcp_servidor.completar("list_ports", None, root=RAIZ, plugins=PLUGINS) == {}
    assert mcp_servidor.completar("no_existe", {"a": 1}, root=RAIZ, plugins=PLUGINS) == {"a": 1}


def test_los_plugins_de_la_app_son_los_que_carga_la_webapp():
    # Misma carpeta que webapp/server.py registra como plugin local.
    ruta = pathlib.Path(mcp_servidor.PLUGINS_DE_LA_APP["connections"])
    assert ruta.name == "connections" and (ruta / "plugin.py").is_file()

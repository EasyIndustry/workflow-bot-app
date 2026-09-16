"""
`webapp.mcp_servidor`: el MCP del núcleo con la instalación y los plugins de
la app por defecto, más lo que sólo esta app conoce (fuentes, notas,
previsualizar una fuente). Lo que el núcleo ya hace (core#16, #17) no se
vuelve a probar acá: se prueba que se le pasa bien y que los extras encajan.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

pytest.importorskip("mcp")

from webapp import mcp_servidor  # noqa: E402
from backend.mcp import server as nucleo  # noqa: E402

# Rutas reales: las tools del núcleo van por subproceso y cargan los plugins desde disco.
PLUGINS = mcp_servidor.PLUGINS_DE_LA_APP


@pytest.fixture
def extras(tmp_path):
    for carpeta in ("data", "plugins", "workspace"):
        (tmp_path / carpeta).mkdir()
    e = mcp_servidor.Extras(str(tmp_path))
    yield e
    if e._instance is not None:
        e._instance.close()


def _llamar(extras, nombre, args=None):
    """Como lo hace el servidor: con los defaults del núcleo puestos y despachado por `call_tool`."""
    esquemas = {t.name: t.input_schema for t in [*nucleo.TOOLS, *mcp_servidor.EXTRA_TOOLS]}
    argumentos = nucleo.con_defaults(args, esquemas.get(nombre, {}), root=extras.root, plugins=PLUGINS)
    return nucleo.call_tool(nombre, argumentos, handlers={**nucleo.HANDLERS, **extras.handlers()})


def test_el_servidor_lleva_los_extras_y_las_instrucciones(tmp_path):
    servidor = mcp_servidor.build_server(str(tmp_path), PLUGINS)
    assert "preview_source" in servidor.instructions
    assert "describe_installation" in servidor.instructions  # las del núcleo, que arrancan por la orientación
    assert "data/bot.db" in servidor.instructions


def test_los_extras_pisan_solo_lo_que_deben():
    propios = set(mcp_servidor.Extras("x").handlers())
    del_nucleo = {t.name for t in nucleo.TOOLS}
    # describe/write/delete se envuelven (mismo nombre, mismo esquema); preview_source es nueva.
    assert propios & del_nucleo == {"describe_installation", "write_resource_item", "delete_resource_item"}
    assert {t.name for t in mcp_servidor.EXTRA_TOOLS} == {"preview_source"}
    assert not ({t.name for t in mcp_servidor.EXTRA_TOOLS} & del_nucleo)


def test_describe_trae_fuentes_y_notas_ademas_de_lo_del_nucleo(extras):
    definicion = extras.instance.resource_definition("conocimiento", "notas")
    extras.instance.resource_store("conocimiento", definicion).write("QA casos", {
        "tema": "QA casos", "texto": "Bandeja de prueba.", "origen": "agente",
    })
    r = _llamar(extras, "describe_installation")
    assert not r.is_error
    d = r.structured_content
    assert {"flows", "plugins", "actors", "boot", "runs"} <= set(d)  # lo del núcleo
    assert d["fuentes"] == [] and d["notas"][0]["tema"] == "QA casos"  # lo de la app
    assert "QA casos" in d["resumen"]


def test_escribir_una_nota_deja_el_manual(extras):
    r = _llamar(extras, "write_resource_item", {
        "plugin": "conocimiento", "resource": "notas", "key": "QA casos",
        "item": {"tema": "QA casos", "texto": "Bandeja de prueba.", "origen": "agente"},
    })
    assert not r.is_error, r.content[0].text
    assert (pathlib.Path(extras.root) / "AGENTS.md").is_file()
    r = _llamar(extras, "delete_resource_item", {"plugin": "conocimiento", "resource": "notas", "key": "QA casos"})
    assert not r.is_error, r.content[0].text


def test_preview_de_una_fuente_inexistente_vuelve_como_err_del_tool(extras):
    r = _llamar(extras, "preview_source", {"name": "no-hay"})
    assert not r.is_error  # el ToolResult dice err; el transporte no falla
    assert r.structured_content["result"]["status"] == "err"


def test_argumentos_que_no_encajan(extras):
    r = _llamar(extras, "preview_source", {"otro": 1})
    assert r.is_error and "argumentos inválidos" in r.content[0].text

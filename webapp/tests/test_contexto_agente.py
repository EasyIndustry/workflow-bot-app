"""
`webapp.contexto_agente`: el manual agéntico de una instalación. Lo que un
agente lee antes de tocar nada tiene que salir de la instalación misma y no
de un texto que envejezca, y no puede filtrar un secreto.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.core.instance import Instance  # noqa: E402
from webapp import contexto_agente  # noqa: E402

LOCAL_PLUGINS = {
    "connections": "webapp.connections.plugin:PLUGIN",
    "conocimiento": "webapp.conocimiento.plugin:PLUGIN",
}

FLUJO = """flowchart TD
    SN(inicio)
    A["log § core.log | message=hola {id}"]
    SN --> A
"""


@pytest.fixture
def instalacion(tmp_path):
    for carpeta in ("data", "plugins", "workspace"):
        (tmp_path / carpeta).mkdir()
    inst = Instance(tmp_path, local_plugins=LOCAL_PLUGINS)
    yield tmp_path, inst
    inst.close()


def _guardar_fuente(inst, nombre="QA casos", token="{env.TOKEN}"):
    definicion = inst.resource_definition("connections", "sources")
    inst.resource_store("connections", definicion).write(nombre, {
        "name": nombre, "url": "http://api.local/casos", "key_field": "id",
        "headers": {"Authorization": f"Bearer {token}"}, "default_flow": "saludar",
    })


def test_describe_lo_del_nucleo_mas_lo_de_la_app(instalacion):
    raiz, inst = instalacion
    inst.workflows.save("saludar", FLUJO)
    _guardar_fuente(inst)
    definicion = inst.resource_definition("conocimiento", "notas")
    inst.resource_store("conocimiento", definicion).write("QA casos", {
        "tema": "QA casos", "texto": "Es la bandeja de intranet de prueba.",
    })

    d = contexto_agente.describir(inst)

    assert d["boot"]["root"] == str(raiz)
    flujo = next(f for f in d["flows"] if f["name"] == "saludar")
    assert flujo["tools"] == ["core.log"]
    assert [f["name"] for f in d["fuentes"]] == ["QA casos"]
    assert d["fuentes"][0]["default_flow"] == "saludar"
    assert d["notas"] == [{"tema": "QA casos", "texto": "Es la bandeja de intranet de prueba.", "origen": "persona"}]
    assert "QA casos (clave id, flujo por defecto saludar)" in d["resumen"]
    assert "Notas de conocimiento: 1 — QA casos" in d["resumen"]
    assert "flujo(s) guardado(s)" in d["resumen"]  # el resumen del núcleo sigue adelante


def test_no_filtra_secretos_ni_headers(instalacion):
    """De una fuente viaja lo que hace falta para nombrarla; los headers, nunca."""
    _raiz, inst = instalacion
    _guardar_fuente(inst, token="secreto-en-claro")
    d = contexto_agente.describir(inst)
    texto = str(d) + contexto_agente.agents_md(d)
    assert "secreto-en-claro" not in texto
    assert "headers" not in d["fuentes"][0]


def test_agents_md_dice_por_donde_empezar_y_las_reglas(instalacion):
    raiz, inst = instalacion
    texto = contexto_agente.agents_md(contexto_agente.describir(inst), url_app="http://127.0.0.1:8000")
    assert "describe_installation" in texto
    assert "dry_run_flow" in texto and "run_flow" in texto
    assert "bot.db" in texto  # la regla de no abrir la base
    assert "http://127.0.0.1:8000" in texto
    assert str(raiz) in texto


def test_escribir_deja_agents_md_y_puntero_para_claude(instalacion):
    raiz, inst = instalacion
    destino = contexto_agente.escribir(inst, raiz)
    assert destino == raiz / "AGENTS.md" and destino.is_file()
    assert (raiz / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_no_pisa_un_claude_md_propio(instalacion):
    raiz, inst = instalacion
    (raiz / "CLAUDE.md").write_text("# mis reglas\n", encoding="utf-8")
    contexto_agente.escribir(inst, raiz)
    assert (raiz / "CLAUDE.md").read_text(encoding="utf-8") == "# mis reglas\n"


def test_regenerar_no_tumba_a_quien_llama(instalacion, tmp_path):
    _raiz, inst = instalacion
    contexto_agente.regenerar(inst, tmp_path / "no" / "existe")


def test_el_paquete_conocimiento_exporta_plugin_para_la_cli():
    """Las tools del MCP van por subproceso y cargan `--plugin conocimiento=<carpeta>`: el registry busca PLUGIN en el paquete."""
    import importlib
    paquete = importlib.import_module("webapp.conocimiento")
    assert paquete.PLUGIN.manifest.name == "conocimiento"

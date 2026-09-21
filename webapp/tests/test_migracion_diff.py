"""
`POST /diff`: qué difiere entre esta instalación y otro Bot.

El origen se lee de la base propia y el destino por HTTP. Acá el "otro Bot" es
una segunda instancia real, servida por los **mismos handlers** de `core_api` en
vez de por un socket: lo que se prueba es el contrato entre dos Bots, así que si
mañana la ruta de listar cambia lo que devuelve, este test lo tiene que ver.

Lo que más importa: un item de una colección con campos `secret` nunca puede dar
`igual`. Los dos lados lo tapan (#3), así que podría diferir justo ahí — decir
"igual" sería afirmar algo que nadie puede ver. Es el estado `indeterminado`, y
es la razón por la que la pantalla de migración no puede prometer un diff
completo de los secretos.
"""

from __future__ import annotations

import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp import migracion  # noqa: E402
from webapp.routes import core_api  # noqa: E402

PLUGIN = "cuentas_test"
COLECCION = "cuentas"
LOCALES = {**core_api.LOCAL_PLUGINS, PLUGIN: "webapp.tests.plugin_con_secreto:PLUGIN"}
OTRO = "http://192.168.1.50:8000"


def _bot_remoto(instancia):
    """Un `_pedir` que contesta como el otro Bot, por los handlers de verdad."""
    def pedir(url, camino):
        anterior = core_api._instance
        core_api._instance = instancia
        try:
            if camino == "/api/core/workflows":
                return core_api.list_workflows()
            if camino.startswith("/api/core/workflows/"):
                return core_api.get_workflow(urllib.parse.unquote(camino.rsplit("/", 1)[1]))
            if camino.startswith("/api/core/resources/"):
                plugin, coleccion = camino.split("/api/core/resources/")[1].split("/")
                return core_api.list_resource(plugin, coleccion)
            if camino == "/api/core/env":
                return core_api.get_env()
            raise AssertionError(f"camino inesperado: {camino}")
        finally:
            core_api._instance = anterior
    return pedir


@pytest.fixture
def dos_bots(tmp_path, monkeypatch):
    """(client de este Bot, instancia del otro). El `_pedir` ya queda enganchado."""
    core_api._instance.close()
    core_api._instance = Instance(tmp_path / "aca", local_plugins=LOCALES)
    otro = Instance(tmp_path / "alla", local_plugins=LOCALES)
    monkeypatch.setattr(migracion, "_pedir", _bot_remoto(otro))
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    yield TestClient(app), otro
    otro.close()


def _flujo(instancia, nombre, contenido, **extra):
    instancia.workflows.save(nombre, content=contenido, **extra)


def _item(instancia, nombre, item):
    definicion = instancia.resource_definition(PLUGIN, COLECCION)
    instancia.resource_store(PLUGIN, definicion).write(nombre, item)


def _diff(client, **cuerpo):
    r = client.post("/api/core/diff", json={"destino": OTRO, **cuerpo})
    assert r.status_code == 200, r.text
    return r.json()


def _por_clave(informe):
    return {i["clave"]: i for i in informe["items"]}


MMD = 'flowchart TD\n    B(inicio)\n    N["core.log | message={}"]\n    B --> N\n'


# ── Flujos ──────────────────────────────────────────────────────────────


def test_un_flujo_identico_de_los_dos_lados_es_igual(dos_bots):
    client, otro = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"))
    _flujo(otro, "alta", MMD.format("hola"))

    informe = _diff(client, que="flujos")

    assert _por_clave(informe)["alta"]["estado"] == "igual"
    assert informe["resumen"]["igual"] == 1


def test_el_contenido_distinto_se_reporta_por_campo(dos_bots):
    """`campos` es lo que deja marcar por campo y no sólo por item."""
    client, otro = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"), folder="produccion")
    _flujo(otro, "alta", MMD.format("chau"), folder="produccion")

    entrada = _por_clave(_diff(client, que="flujos"))["alta"]

    assert entrada["estado"] == "distinto"
    assert entrada["campos"] == ["content"]


def test_de_que_lado_falta_cada_uno(dos_bots):
    client, otro = dos_bots
    _flujo(core_api._instance, "sólo acá", MMD.format("x"))
    _flujo(otro, "sólo allá", MMD.format("y"))

    items = _por_clave(_diff(client, que="flujos"))

    assert items["sólo acá"]["estado"] == "solo_origen"
    assert items["sólo allá"]["estado"] == "solo_destino"


def test_updated_at_no_cuenta_como_diferencia(dos_bots):
    """Son dos bases distintas: difiere siempre y no dice nada del contenido."""
    client, otro = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"))
    _flujo(otro, "alta", MMD.format("hola"))

    informe = _diff(client, que="flujos")

    assert "updated_at" not in informe["campos_comparados"]
    assert informe["resumen"]["distinto"] == 0


def test_el_detalle_viene_solo_si_se_pide(dos_bots):
    """El `content` de un flujo son miles de caracteres: por defecto no va."""
    client, otro = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"))
    _flujo(otro, "alta", MMD.format("chau"))

    sin = _por_clave(_diff(client, que="flujos"))["alta"]
    con = _por_clave(_diff(client, que="flujos", detalle=True))["alta"]

    assert "origen" not in sin
    assert MMD.format("hola") == con["origen"]["content"]
    assert MMD.format("chau") == con["destino"]["content"]


# ── Items de una colección, y los secretos ──────────────────────────────


def test_un_item_con_campos_secretos_nunca_dice_igual(dos_bots):
    """
    Los dos lados tapan el token, así que podría diferir justo ahí. Es el caso
    que la pantalla tiene que mostrar como "revisar a mano".
    """
    client, otro = dos_bots
    _item(core_api._instance, "prod", {"name": "prod", "url": "https://api.test", "token": "aca"})
    _item(otro, "prod", {"name": "prod", "url": "https://api.test", "token": "alla"})

    informe = _diff(client, que="registros", plugin=PLUGIN, coleccion=COLECCION)

    assert _por_clave(informe)["prod"]["estado"] == "indeterminado"
    assert informe["campos_secretos"] == ["token"]
    assert "token" not in informe["campos_comparados"]


def test_un_campo_visible_distinto_si_se_ve(dos_bots):
    """Que haya un secreto no tapa lo demás: `distinto` gana a `indeterminado`."""
    client, otro = dos_bots
    _item(core_api._instance, "prod", {"name": "prod", "url": "https://aca.test", "token": "x"})
    _item(otro, "prod", {"name": "prod", "url": "https://alla.test", "token": "x"})

    entrada = _por_clave(_diff(client, que="registros", plugin=PLUGIN, coleccion=COLECCION))["prod"]

    assert entrada["estado"] == "distinto"
    assert entrada["campos"] == ["url"]


def test_ningun_valor_secreto_aparece_en_el_informe(dos_bots):
    """El diff no es una segunda puerta por la que salga lo que #3 cerró."""
    client, otro = dos_bots
    _item(core_api._instance, "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})
    _item(otro, "prod", {"name": "prod", "url": "https://otra.test", "token": "xyz789"})

    r = client.post("/api/core/diff", json={
        "destino": OTRO, "que": "registros", "plugin": PLUGIN,
        "coleccion": COLECCION, "detalle": True,
    })

    assert "abc123" not in r.text
    assert "xyz789" not in r.text


def test_una_coleccion_sin_secretos_si_puede_decir_igual(dos_bots):
    client, otro = dos_bots
    accion = {"name": "Comentario", "url": "https://api.test/x", "method": "POST"}
    for instancia in (core_api._instance, otro):
        definicion = instancia.resource_definition("connections", "actions")
        instancia.resource_store("connections", definicion).write("Comentario", accion)

    informe = _diff(client, que="registros", plugin="connections", coleccion="actions")

    assert _por_clave(informe)["Comentario"]["estado"] == "igual"
    assert informe["campos_secretos"] == []


def test_campos_secretos_viene_siempre_aunque_este_vacio(dos_bots):
    """Para que el renderer no distinga "no hay" de "no me lo dijeron"."""
    client, _ = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"))

    assert _diff(client, que="flujos")["campos_secretos"] == []


# ── Variables de entorno ────────────────────────────────────────────────


def test_una_variable_comun_se_compara_entera(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("TIMEOUT", "30", secret=False)
    otro.env.save("TIMEOUT", "60", secret=False)

    entrada = _por_clave(_diff(client, que="env"))["TIMEOUT"]

    assert entrada["estado"] == "distinto"
    assert entrada["campos"] == ["value"]


def test_una_variable_secreta_nunca_dice_igual(dos_bots):
    """
    En `env` la secrecía es de cada variable: acá conviven una que se compara
    entera y una de la que no se sabe nada.
    """
    client, otro = dos_bots
    core_api._instance.env.save("TIMEOUT", "30", secret=False)
    otro.env.save("TIMEOUT", "30", secret=False)
    core_api._instance.env.save("API_KEY", "aca", secret=True)
    otro.env.save("API_KEY", "alla", secret=True)

    items = _por_clave(_diff(client, que="env"))

    assert items["TIMEOUT"]["estado"] == "igual"
    assert items["API_KEY"]["estado"] == "indeterminado"


def test_el_valor_de_una_variable_secreta_no_viaja(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("API_KEY", "abc123", secret=True)
    otro.env.save("API_KEY", "xyz789", secret=True)

    r = client.post("/api/core/diff", json={"destino": OTRO, "que": "env", "detalle": True})

    assert "abc123" not in r.text
    assert "xyz789" not in r.text


def test_una_variable_que_nadie_cargo_no_es_una_variable(dos_bots):
    """
    Las `undeclared` —referenciadas por un flujo y nunca cargadas— aparecen en
    el listado porque son las que rompen una ejecución, pero no hay nada que
    comparar ni que migrar.
    """
    client, _ = dos_bots
    _flujo(core_api._instance, "usa", MMD.format("{env.NUNCA_CARGADA}"))

    assert "NUNCA_CARGADA" not in _por_clave(_diff(client, que="env"))


# ── Lo que sale mal ─────────────────────────────────────────────────────


def test_el_resumen_cuenta_los_cinco_estados(dos_bots):
    client, _ = dos_bots
    _flujo(core_api._instance, "alta", MMD.format("hola"))

    assert set(_diff(client, que="flujos")["resumen"]) == set(migracion.ESTADOS)


def test_comparar_contra_uno_mismo_no_se_intenta(dos_bots, monkeypatch):
    client, _ = dos_bots
    monkeypatch.setattr(core_api, "_url_app", lambda: OTRO)

    r = client.post("/api/core/diff", json={"destino": OTRO, "que": "flujos"})

    assert r.status_code == 400
    assert "este mismo Bot" in r.json()["detail"]


def test_registros_sin_coleccion_lo_dice(dos_bots):
    client, _ = dos_bots

    r = client.post("/api/core/diff", json={"destino": OTRO, "que": "registros"})

    assert r.status_code == 400
    assert "colección" in r.json()["detail"]


def test_el_destino_caido_se_lee_como_un_aviso(dos_bots, monkeypatch):
    """Quien lee esto está mirando una pantalla, no un traceback."""
    client, _ = dos_bots

    def caido(url, camino):
        raise migracion.MigracionError(f"No se pudo conectar con {url}: timed out")

    monkeypatch.setattr(migracion, "_pedir", caido)
    r = client.post("/api/core/diff", json={"destino": OTRO, "que": "flujos"})

    assert r.status_code == 400
    assert "No se pudo conectar" in r.json()["detail"]

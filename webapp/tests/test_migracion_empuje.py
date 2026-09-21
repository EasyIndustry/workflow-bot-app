"""
`POST /migrar`: escribir en otro Bot lo que se eligió de acá.

Empuja y no tira, y ésa es la parte que hay que entender del diseño: desde #3 un
secreto no sale por la API de nadie, así que el único que puede leer los de una
instalación es la instalación misma. Correr en el origen es lo único que permite
moverlos, y de paso cada Bot los vuelve a cifrar con su propia llave — no hay que
copiar ninguna, y un secreto robado en una no vale en la otra.

Lo que se verifica de los secretos se mira **en la base del destino**, no en la
respuesta: la respuesta justamente no los trae.

El otro Bot es una segunda instancia real servida por los handlers de verdad, en
vez de un socket, para que el contrato entre dos Bots quede fijado acá.
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

MMD = 'flowchart TD\n    B(inicio)\n    N["core.log | message={}"]\n    B --> N\n'


def _escritor(instancia):
    """Un `_escribir` que entra al otro Bot por sus propios handlers."""
    def escribir(url, camino, cuerpo):
        anterior = core_api._instance
        core_api._instance = instancia
        try:
            if camino.startswith("/api/core/workflows/"):
                nombre = urllib.parse.unquote(camino.rsplit("/", 1)[1])
                return core_api.put_workflow(nombre, core_api.WorkflowBody(**cuerpo))
            if camino.startswith("/api/core/env/"):
                nombre = urllib.parse.unquote(camino.rsplit("/", 1)[1])
                return core_api.put_env(nombre, core_api.EnvBody(**cuerpo))
            if camino.startswith("/api/core/resources/"):
                plugin, coleccion, clave = camino.split("/api/core/resources/")[1].split("/")
                return core_api.put_resource_item(
                    plugin, coleccion, urllib.parse.unquote(clave),
                    core_api.ResourceItem(**cuerpo))
            raise AssertionError(f"camino inesperado: {camino}")
        finally:
            core_api._instance = anterior
    return escribir


@pytest.fixture
def dos_bots(tmp_path, monkeypatch):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path / "aca", local_plugins=LOCALES)
    otro = Instance(tmp_path / "alla", local_plugins=LOCALES)
    monkeypatch.setattr(migracion, "_escribir", _escritor(otro))
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    yield TestClient(app), otro
    otro.close()


def _migrar(client, **cuerpo):
    r = client.post("/api/core/migrar", json={"destino": OTRO, **cuerpo})
    assert r.status_code == 200, r.text
    return r.json()


def _item_alla(otro, clave):
    definicion = otro.resource_definition(PLUGIN, COLECCION)
    return otro.resource_store(PLUGIN, definicion).read(clave)


# ── Flujos ──────────────────────────────────────────────────────────────


def test_un_flujo_llega_con_su_contenido(dos_bots):
    client, otro = dos_bots
    core_api._instance.workflows.save("alta", content=MMD.format("hola"),
                                      folder="produccion", description="la buena")

    informe = _migrar(client, que="flujos", claves=["alta"])

    assert informe["migrados"] == 1
    llegado = otro.workflows.get("alta")
    assert llegado.content == MMD.format("hola")
    assert llegado.folder == "produccion"
    assert llegado.description == "la buena"


def test_solo_se_migra_lo_elegido(dos_bots):
    client, otro = dos_bots
    for nombre in ("una", "otra"):
        core_api._instance.workflows.save(nombre, content=MMD.format(nombre))

    _migrar(client, que="flujos", claves=["una"])

    assert otro.workflows.get("una") is not None
    assert otro.workflows.get("otra") is None


def test_un_nombre_con_acentos_y_espacios_llega(dos_bots):
    client, otro = dos_bots
    core_api._instance.workflows.save("Impresión de moldes", content=MMD.format("x"))

    _migrar(client, que="flujos", claves=["Impresión de moldes"])

    assert otro.workflows.get("Impresión de moldes") is not None


def test_pisa_lo_que_habia(dos_bots):
    """Migrar es pisar: la pantalla es la que pregunta antes, no el endpoint."""
    client, otro = dos_bots
    core_api._instance.workflows.save("alta", content=MMD.format("nuevo"))
    otro.workflows.save("alta", content=MMD.format("viejo"))

    _migrar(client, que="flujos", claves=["alta"])

    assert otro.workflows.get("alta").content == MMD.format("nuevo")


# ── Items de colección, con su secreto ──────────────────────────────────


def test_el_secreto_de_un_item_llega_al_destino(dos_bots):
    """
    Lo que no se puede hacer por la API —leer el secreto— se hace local, y por
    eso la migración corre en el origen.
    """
    client, otro = dos_bots
    definicion = core_api._instance.resource_definition(PLUGIN, COLECCION)
    core_api._instance.resource_store(PLUGIN, definicion).write(
        "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    informe = _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
                      claves=["prod"])

    assert informe["migrados"] == 1
    assert _item_alla(otro, "prod")["token"] == "abc123"
    assert _item_alla(otro, "prod")["url"] == "https://api.test"


def test_la_respuesta_no_trae_el_secreto(dos_bots):
    client, _ = dos_bots
    definicion = core_api._instance.resource_definition(PLUGIN, COLECCION)
    core_api._instance.resource_store(PLUGIN, definicion).write(
        "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    r = client.post("/api/core/migrar", json={
        "destino": OTRO, "que": "registros", "plugin": PLUGIN,
        "coleccion": COLECCION, "claves": ["prod"]})

    assert "abc123" not in r.text


def test_el_destino_lo_guarda_cifrado_con_su_llave(dos_bots):
    """
    No se copia ninguna llave: el destino recibe el valor y lo cifra con la suya.
    Se mira la fila cruda, que es donde se vería si viajó el sobre o el valor.
    """
    client, otro = dos_bots
    definicion = core_api._instance.resource_definition(PLUGIN, COLECCION)
    core_api._instance.resource_store(PLUGIN, definicion).write(
        "prod", {"name": "prod", "url": "https://api.test", "token": "abc123"})

    _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION, claves=["prod"])

    fila = otro.db.one(
        "SELECT data FROM plugin_items WHERE plugin = ? AND resource = ? AND key = ?",
        (PLUGIN, COLECCION, "prod"))
    assert "abc123" not in fila["data"]
    assert _item_alla(otro, "prod")["token"] == "abc123"


# ── Variables de entorno ────────────────────────────────────────────────


def test_una_variable_secreta_llega_y_sigue_secreta(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("API_KEY", "abc123", secret=True)

    informe = _migrar(client, que="env", claves=["API_KEY"])

    assert informe["migrados"] == 1
    assert otro.env.resolve()["API_KEY"] == "abc123"
    assert otro.env.get("API_KEY").secret is True


def test_una_variable_comun_llega_como_comun(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("TIMEOUT", "30", secret=False)

    _migrar(client, que="env", claves=["TIMEOUT"])

    assert otro.env.resolve()["TIMEOUT"] == "30"
    assert otro.env.get("TIMEOUT").secret is False


def test_una_variable_que_ya_no_esta_no_voltea_las_demas(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("TIMEOUT", "30", secret=False)

    informe = _migrar(client, que="env", claves=["NO_EXISTE", "TIMEOUT"])

    assert informe["migrados"] == 1
    assert informe["fallados"] == 1
    fallado = [r for r in informe["resultados"] if r["clave"] == "NO_EXISTE"][0]
    assert "ya no está" in fallado["error"]
    assert otro.env.resolve()["TIMEOUT"] == "30"


# ── Clave por clave, y lo que sale mal ──────────────────────────────────


def test_lo_que_el_destino_rechaza_no_frena_al_resto(dos_bots, monkeypatch):
    """
    No hay transacción del otro lado: deshacer a medias sería peor que informar.
    El informe tiene que decir cuál falló y por qué.
    """
    client, otro = dos_bots
    for nombre in ("buena", "mala"):
        core_api._instance.workflows.save(nombre, content=MMD.format(nombre))

    escribir_real = migracion._escribir

    def a_veces_falla(url, camino, cuerpo):
        if camino.endswith("mala"):
            raise migracion.MigracionError("el destino no sabe de ese tool")
        return escribir_real(url, camino, cuerpo)

    monkeypatch.setattr(migracion, "_escribir", a_veces_falla)
    informe = _migrar(client, que="flujos", claves=["mala", "buena"])

    assert informe["migrados"] == 1
    assert informe["fallados"] == 1
    assert otro.workflows.get("buena") is not None
    assert otro.workflows.get("mala") is None
    assert "no sabe de ese tool" in informe["resultados"][0]["error"]


def test_sin_nada_elegido_no_se_escribe(dos_bots):
    client, _ = dos_bots

    r = client.post("/api/core/migrar", json={"destino": OTRO, "que": "flujos", "claves": []})

    assert r.status_code == 400
    assert "No se eligió nada" in r.json()["detail"]


def test_migrar_contra_uno_mismo_no_se_intenta(dos_bots, monkeypatch):
    client, _ = dos_bots
    monkeypatch.setattr(core_api, "_url_app", lambda: OTRO)

    r = client.post("/api/core/migrar",
                    json={"destino": OTRO, "que": "flujos", "claves": ["alta"]})

    assert r.status_code == 400
    assert "este mismo Bot" in r.json()["detail"]


def test_registros_sin_coleccion_lo_dice(dos_bots):
    client, _ = dos_bots

    r = client.post("/api/core/migrar",
                    json={"destino": OTRO, "que": "registros", "claves": ["x"]})

    assert r.status_code == 400
    assert "colección" in r.json()["detail"]

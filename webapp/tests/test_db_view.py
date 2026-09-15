"""
Tests del visor de la base (`webapp/db_view.py`).

Base en memoria con el esquema real del núcleo: lo que se prueba es que el
visor lista lo que el esquema declara, pagina de la más nueva a la más vieja y,
sobre todo, que no deja pasar un secreto — ni el cifrado de `env`, ni los que
`settings` y `plugin_items` guardan en claro porque un manifest los marcó.
"""

from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.adapters.storage_sqlite import IN_MEMORY, SqliteStorageAdapter  # noqa: E402
from backend.core.contract import Field, PluginManifest, Resource, Setting  # noqa: E402
from backend.core.schema import MIGRATIONS, SCHEMA  # noqa: E402
from webapp import db_view  # noqa: E402


@pytest.fixture
def db():
    almacen = SqliteStorageAdapter(IN_MEMORY)
    almacen.migrate(SCHEMA, MIGRATIONS)
    yield almacen
    almacen.close()


@pytest.fixture
def registry():
    manifest = PluginManifest(
        name="conex", label="Conex",
        settings=(Setting(key="apiToken", secret=True), Setting(key="carpeta")),
        resources=(Resource(name="cuentas", label="Cuentas",
                            fields=(Field(name="name"), Field(name="clave", secret=True))),),
    )
    return SimpleNamespace(plugins=[SimpleNamespace(name="conex", manifest=manifest)])


def test_lista_las_tablas_del_esquema_con_conteo(db):
    db.execute("INSERT INTO env (org, name, value, secret, updated_by, updated_at) VALUES ('local','A','1',0,'t',0)")
    tablas = {t["name"]: t for t in db_view.tablas(db)}
    assert set(tablas) == set(SCHEMA)
    assert tablas["env"]["count"] == 1
    assert tablas["workflows"]["count"] == 0


def test_tabla_desconocida_es_error_y_no_sql(db, registry):
    with pytest.raises(db_view.TablaDesconocida):
        db_view.filas(db, registry, "sqlite_master")
    with pytest.raises(db_view.TablaDesconocida):
        db_view.columnas(db, "env; DROP TABLE env")


def test_pagina_de_la_mas_nueva_a_la_mas_vieja(db, registry):
    for i in range(7):
        db.execute("INSERT INTO env (org, name, value, secret, updated_by, updated_at) VALUES ('local',?,?,0,'t',0)",
                   (f"V{i}", str(i)))
    pagina = db_view.filas(db, registry, "env", limit=3, offset=0)
    assert pagina["total"] == 7
    assert [f["name"] for f in pagina["rows"]] == ["V6", "V5", "V4"]
    assert "name" in pagina["columns"] and "value" in pagina["columns"]
    segunda = db_view.filas(db, registry, "env", limit=3, offset=3)
    assert [f["name"] for f in segunda["rows"]] == ["V3", "V2", "V1"]


def test_limite_acotado(db, registry):
    pagina = db_view.filas(db, registry, "env", limit=99999, offset=-4)
    assert pagina["limit"] == db_view.LIMITE_MAXIMO
    assert pagina["offset"] == 0


def test_env_tapa_los_secretos_y_deja_las_variables(db, registry):
    db.execute("INSERT INTO env (org, name, value, secret, updated_by, updated_at) VALUES ('local','TOKEN','cifrado',1,'t',0)")
    db.execute("INSERT INTO env (org, name, value, secret, updated_by, updated_at) VALUES ('local','PAIS','AR',0,'t',0)")
    filas = {f["name"]: f for f in db_view.filas(db, registry, "env")["rows"]}
    assert filas["TOKEN"]["value"] == db_view.TAPADO
    assert filas["PAIS"]["value"] == "AR"


def test_settings_tapa_lo_que_el_manifest_marca_secreto(db, registry):
    db.execute("INSERT INTO settings (org, key, value, updated_by, updated_at) VALUES ('local','apiToken','\"abc\"','t',0)")
    db.execute("INSERT INTO settings (org, key, value, updated_by, updated_at) VALUES ('local','carpeta','\"/x\"','t',0)")
    filas = {f["key"]: f for f in db_view.filas(db, registry, "settings")["rows"]}
    assert filas["apiToken"]["value"] == db_view.TAPADO
    assert filas["carpeta"]["value"] == '"/x"'


def test_plugin_items_tapa_el_campo_secreto_adentro_del_json(db, registry):
    data = json.dumps({"name": "prod", "clave": "s3cr3t"})
    db.execute("INSERT INTO plugin_items (org, plugin, resource, key, data, updated_by, updated_at) "
               "VALUES ('local','conex','cuentas','prod',?, 't', 0)", (data,))
    db.execute("INSERT INTO plugin_items (org, plugin, resource, key, data, updated_by, updated_at) "
               "VALUES ('local','otro','cosas','x','{\"clave\":\"visible\"}', 't', 0)")
    filas = {(f["plugin"], f["key"]): f for f in db_view.filas(db, registry, "plugin_items")["rows"]}
    tapada = json.loads(filas[("conex", "prod")]["data"])
    assert tapada == {"name": "prod", "clave": db_view.TAPADO}
    # Otro plugin con un campo del mismo nombre no declarado secreto: se ve.
    assert json.loads(filas[("otro", "x")]["data"]) == {"clave": "visible"}


def test_plugin_items_con_json_roto_se_tapa_entero(db, registry):
    db.execute("INSERT INTO plugin_items (org, plugin, resource, key, data, updated_by, updated_at) "
               "VALUES ('local','conex','cuentas','rota','{no es json', 't', 0)")
    fila = db_view.filas(db, registry, "plugin_items")["rows"][0]
    assert fila["data"] == db_view.TAPADO

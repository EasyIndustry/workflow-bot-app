"""
Tests del plugin `connections`.

Corren igual que los del núcleo: base en memoria, adapters falsos, nada de red
de verdad. La única diferencia con `backend/tests` es la raíz que se agrega a
`sys.path`, porque este plugin vive bajo `webapp/`, no bajo `backend/`.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from backend.core.contract import Action, ToolContext, ToolManifest  # noqa: E402
from backend.core.registry import ToolRegistry  # noqa: E402
from backend.tests.fakes import FakeHttp  # noqa: E402

from webapp.connections.plugin import _dig, _fetch_page, build_plugin  # noqa: E402


def _ctx_factory(node_params, config=None, context=None, resources=None):
    def factory(declaracion, ports=None):
        if isinstance(declaracion, Action):
            declaracion = ToolManifest(
                id=f"action.{declaracion.name}", label=declaracion.label,
                category="ACCIÓN", params=declaracion.params,
            )
        declarados, extras = declaracion.split_params(node_params, config or {})
        return ToolContext(
            run_id="run-test", case_id="0044",
            params=declarados, extras=extras,
            config=config or {}, context=context or {},
            log=lambda *_a, **_k: None, resources=resources, ports=ports or {},
        )

    return factory


def _registry(http: FakeHttp) -> ToolRegistry:
    reg = ToolRegistry(adapters={"http": http})
    reg._add_plugin("connections", "webapp.connections.plugin:PLUGIN", build_plugin())
    return reg


# ── El plugin carga limpio ──────────────────────────────────────────────


def test_el_plugin_carga_sin_errores():
    reg = _registry(FakeHttp())
    assert not reg.errors
    plugin = next(p for p in reg.plugins if p.name == "connections")
    assert plugin.ports == ("http",)
    assert {r.name for r in plugin.manifest.resources} == {"sources", "actions"}
    assert {a.name for a in plugin.manifest.actions} == {"preview", "test", "probar_llamada"}
    assert set(reg.tool_ids) == {"connections.llamar", "connections.llamar_y_fusionar"}


# ── _dig: caminos con puntos ─────────────────────────────────────────────


def test_dig_camino_vacio_devuelve_la_raiz():
    assert _dig({"a": 1}, "") == {"a": 1}


def test_dig_camino_anidado():
    assert _dig({"data": {"items": [1, 2, 3]}}, "data.items") == [1, 2, 3]


def test_dig_camino_que_no_existe():
    assert _dig({"data": {}}, "data.items") is None


# ── _fetch_page: sin paginación externa (se trae todo, se corta en memoria) ─


def test_fetch_page_sin_paginacion_pagina_en_memoria():
    http = FakeHttp().stub("https://api.test/casos", text='[{"id":1},{"id":2},{"id":3}]')
    cfg = {"url": "https://api.test/casos", "method": "GET"}

    resultado = _fetch_page(http, cfg, offset=1, limit=2, timeout=5)

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 2}, {"id": 3}]
    assert resultado["total"] == 3  # el total es el de la lista entera, no de la página


def test_fetch_page_sin_paginacion_busca_en_la_fuente_entera_antes_de_paginar():
    http = FakeHttp().stub(
        "https://api.test/casos",
        text='[{"id":1,"nombre":"ana"},{"id":2,"nombre":"beto"},{"id":3,"nombre":"ana maria"}]',
    )
    cfg = {"url": "https://api.test/casos", "method": "GET"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5, search="ana")

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 1, "nombre": "ana"}, {"id": 3, "nombre": "ana maria"}]
    assert resultado["total"] == 2  # el total ya refleja el filtro, no la fuente entera


def test_fetch_page_filtra_por_columna_con_igualdad_exacta():
    http = FakeHttp().stub(
        "https://api.test/casos",
        text='[{"id":1,"pais":"AR"},{"id":2,"pais":"CL"},{"id":3,"pais":"AR"}]',
    )
    cfg = {"url": "https://api.test/casos"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5, filters={"pais": "AR"})

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 1, "pais": "AR"}, {"id": 3, "pais": "AR"}]
    assert resultado["total"] == 2


def test_fetch_page_facetas_no_se_achican_con_el_propio_filtro():
    http = FakeHttp().stub(
        "https://api.test/casos",
        text='[{"id":1,"pais":"AR"},{"id":2,"pais":"CL"},{"id":3,"pais":"AR"}]',
    )
    cfg = {"url": "https://api.test/casos"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5, filters={"pais": "AR"})

    # Las filas ya quedaron sólo con "AR", pero el desplegable de "pais" sigue
    # ofreciendo "CL": elegir un valor en una columna no le achica las
    # opciones a esa misma columna, ni a las demás.
    assert resultado["facets"]["pais"] == ["AR", "CL"]
    assert resultado["facets"]["id"] == ["1", "2", "3"]


def test_fetch_page_faceta_se_omite_si_tiene_demasiados_valores_unicos():
    filas = [{"id": i} for i in range(60)]
    http = FakeHttp().stub("https://api.test/casos", text=json.dumps(filas))
    cfg = {"url": "https://api.test/casos"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5)

    assert "id" not in resultado["facets"]  # 60 valores únicos: no es para un desplegable


def test_fetch_page_con_paginacion_externa_el_search_solo_filtra_la_pagina_traida():
    http = FakeHttp().stub(
        "https://api.test/casos?page=1", text='[{"id":1,"nombre":"ana"},{"id":2,"nombre":"beto"}]',
    )
    cfg = {"url": "https://api.test/casos", "page_param": "page", "page_size": 2}

    resultado = _fetch_page(http, cfg, offset=0, limit=2, timeout=5, search="ana")

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 1, "nombre": "ana"}]


def test_fetch_page_resuelve_results_path():
    http = FakeHttp().stub(
        "https://api.test/casos", text='{"data": {"items": [{"id": 1}], "total": 1}}'
    )
    cfg = {"url": "https://api.test/casos", "results_path": "data.items"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5)

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 1}]


def test_fetch_page_si_la_respuesta_no_es_lista_es_error():
    http = FakeHttp().stub("https://api.test/casos", text='{"no": "es una lista"}')
    cfg = {"url": "https://api.test/casos"}

    resultado = _fetch_page(http, cfg, offset=0, limit=10, timeout=5)

    assert resultado["error"] is not None
    assert resultado["rows"] == []


# ── _fetch_page: con paginación externa declarada ────────────────────────


def test_fetch_page_con_paginacion_externa_pide_solo_esa_pagina():
    http = FakeHttp()
    # offset=100 con page_size=50 tiene que pedir la página 3.
    http.stub("https://api.test/casos?page=3&size=50", text='[{"id": 101}]')
    cfg = {
        "url": "https://api.test/casos",
        "page_param": "page", "page_size_param": "size", "page_size": 50,
    }

    resultado = _fetch_page(http, cfg, offset=100, limit=50, timeout=5)

    assert resultado["error"] is None
    assert resultado["rows"] == [{"id": 101}]
    # Se le pidió a la API la URL con los params de paginación, no la base.
    assert http.calls[0]["url"] == "https://api.test/casos?page=3&size=50"


def test_fetch_page_con_paginacion_externa_usa_total_path_si_esta():
    http = FakeHttp().stub(
        "https://api.test/casos?page=1", text='{"rows": [{"id": 1}], "count": 9000}'
    )
    cfg = {
        "url": "https://api.test/casos", "page_param": "page",
        "results_path": "rows", "total_path": "count",
    }

    resultado = _fetch_page(http, cfg, offset=0, limit=50, timeout=5)

    assert resultado["total"] == 9000


# ── connections.llamar — el tool de flujo ────────────────────────────────


def test_llamar_resuelve_variables_del_contexto_del_run():
    http = FakeHttp().stub(
        "https://api.test/casos/123", text='{"estado": "listo"}',
    )
    guardada = {
        "url": "https://api.test/casos/{id_externo}",
        "method": "POST",
        "headers": {},
        "payload": {"nota": "{comentario}"},
        "results_path": "estado",
    }
    resources = lambda coleccion: {"actions": [{"name": "consulta", **guardada}]}.get(coleccion, [])

    resultado = _registry(http).execute(
        "connections.llamar",
        _ctx_factory(
            {"connection": "consulta"},
            context={"id_externo": "123", "comentario": "todo bien"},
            resources=resources,
        ),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["result"] == "listo"
    llamada = http.calls[0]
    assert llamada["url"] == "https://api.test/casos/123"
    assert llamada["body"] == '{"nota": "todo bien"}'


def test_llamar_conexion_inexistente_lista_las_disponibles():
    resources = lambda coleccion: {"actions": [{"name": "otra"}]}.get(coleccion, [])

    resultado = _registry(FakeHttp()).execute(
        "connections.llamar",
        _ctx_factory({"connection": "no-existe"}, resources=resources),
    )

    assert resultado.status == "err"
    assert "otra" in resultado.message


def test_llamar_un_extra_del_nodo_pisa_al_contexto():
    """
    Varios nodos pueden compartir una Action con un campo vacío (ej. 'texto'
    de un comentario) y cada uno mandar su propio literal — el extra del nodo
    gana sobre la variable de mismo nombre que ya hubiera en el contexto.
    """
    http = FakeHttp().stub("https://api.test/comentario", text="{}")
    guardada = {
        "url": "https://api.test/comentario", "method": "POST", "headers": {},
        "payload": {"texto": "{texto}"},
    }
    resources = lambda coleccion: {"actions": [{"name": "comentario", **guardada}]}.get(coleccion, [])

    resultado = _registry(http).execute(
        "connections.llamar",
        _ctx_factory(
            {"connection": "comentario", "texto": "Es KIDS"},
            context={"texto": "del contexto, no se usa"},
            resources=resources,
        ),
    )

    assert resultado.status == "ok"
    assert http.calls[0]["body"] == '{"texto": "Es KIDS"}'


def test_llamar_placeholder_sin_resolver_queda_literal():
    http = FakeHttp().stub("https://api.test/casos/{id_externo}", text="{}")
    guardada = {"url": "https://api.test/casos/{id_externo}", "method": "GET", "headers": {}}
    resources = lambda coleccion: {"actions": [{"name": "c", **guardada}]}.get(coleccion, [])

    resultado = _registry(http).execute(
        "connections.llamar",
        # Sin "id_externo" en el contexto: el placeholder no se puede resolver.
        _ctx_factory({"connection": "c"}, context={}, resources=resources),
    )

    assert resultado.status == "ok"
    assert http.calls[0]["url"] == "https://api.test/casos/{id_externo}"


# ── connections.llamar_y_fusionar — vuelca la respuesta al contexto ──────


def test_llamar_y_fusionar_vuelca_los_campos_de_primer_nivel():
    http = FakeHttp().stub(
        "https://api.test/casos/AT119", text='{"pais": "Argentina", "feston": "3 a 3"}',
    )
    guardada = {"url": "https://api.test/casos/{id_externo}", "method": "GET", "headers": {}}
    resources = lambda coleccion: {"actions": [{"name": "refresh", **guardada}]}.get(coleccion, [])

    resultado = _registry(http).execute(
        "connections.llamar_y_fusionar",
        _ctx_factory(
            {"connection": "refresh"},
            context={"id_externo": "AT119"},
            resources=resources,
        ),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["pais"] == "Argentina"
    assert resultado.outputs["feston"] == "3 a 3"
    # response/status/result se conservan además de los campos sueltos.
    assert resultado.outputs["response"] == {"pais": "Argentina", "feston": "3 a 3"}


def test_llamar_y_fusionar_conexion_inexistente():
    resources = lambda coleccion: {"actions": [{"name": "otra"}]}.get(coleccion, [])

    resultado = _registry(FakeHttp()).execute(
        "connections.llamar_y_fusionar",
        _ctx_factory({"connection": "no-existe"}, resources=resources),
    )

    assert resultado.status == "err"
    assert "otra" in resultado.message


# ── Action "preview" — probar un source sin guardarlo ────────────────────


def test_preview_trae_filas_sin_guardar_nada():
    http = FakeHttp().stub("https://api.test/pendientes", text='[{"id": 1}, {"id": 2}]')

    resultado = _registry(http).execute_action(
        "connections", "preview",
        _ctx_factory({"url": "https://api.test/pendientes", "limit": 10, "offset": 0}),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["rows"] == [{"id": 1}, {"id": 2}]
    assert resultado.outputs["total"] == 2


# ── Action "test" — probar una Action ya guardada ────────────────────────


def test_test_ejecuta_la_conexion_guardada():
    http = FakeHttp().stub("https://api.test/ping", text='{"ok": true}')
    guardada = {"url": "https://api.test/ping", "method": "GET", "headers": {}}
    resources = lambda coleccion: {"actions": [{"name": "ping", **guardada}]}.get(coleccion, [])

    resultado = _registry(http).execute_action(
        "connections", "test",
        _ctx_factory({"connection": "ping"}, resources=resources),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["status"] == 200


def test_test_sobre_conexion_inexistente():
    resultado = _registry(FakeHttp()).execute_action(
        "connections", "test",
        _ctx_factory({"connection": "no-existe"}, resources=lambda _c: []),
    )

    assert resultado.status == "err"


# ── Action "probar_llamada" — probar una Action antes de guardarla ───────


def test_probar_llamada_resuelve_variables_del_formulario():
    http = FakeHttp().stub("https://api.test/casos/123", text='{"estado": "listo"}')

    resultado = _registry(http).execute_action(
        "connections", "probar_llamada",
        _ctx_factory({
            "url": "https://api.test/casos/{id_externo}",
            "method": "POST",
            "payload": {"nota": "{comentario}"},
            "results_path": "estado",
            "vars": {"id_externo": "123", "comentario": "todo bien"},
        }),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["result"] == "listo"
    llamada = http.calls[0]
    assert llamada["url"] == "https://api.test/casos/123"
    assert llamada["body"] == '{"nota": "todo bien"}'


def test_probar_llamada_sin_variable_declarada_queda_literal():
    http = FakeHttp().stub("https://api.test/casos/{id_externo}", text="{}")

    resultado = _registry(http).execute_action(
        "connections", "probar_llamada",
        _ctx_factory({"url": "https://api.test/casos/{id_externo}"}),
    )

    assert resultado.status == "ok"
    assert http.calls[0]["url"] == "https://api.test/casos/{id_externo}"


def test_probar_llamada_no_necesita_nada_guardado():
    """Corre sólo con lo que trae el formulario — nada de `resources`."""
    http = FakeHttp().stub("https://api.test/ping", text='{"ok": true}')

    resultado = _registry(http).execute_action(
        "connections", "probar_llamada",
        _ctx_factory({"url": "https://api.test/ping"}),
    )

    assert resultado.status == "ok"
    assert resultado.outputs["status"] == 200

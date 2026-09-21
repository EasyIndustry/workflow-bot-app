"""
`POST /migrar`: mandarle a otro Bot, en un sobre cifrado, lo que se eligió acá.

Dos cosas se prueban juntas porque son la misma decisión:

1. **Empuja y no tira.** Desde #3 un secreto no sale por la API de nadie, así
   que el único que puede leer los de una instalación es la instalación misma.
   Correr en el origen es lo único que permite moverlos, y el destino los vuelve
   a cifrar con su propia llave — no se copia ninguna.
2. **Sin emparejamiento no se migra.** No hay camino en claro ni con aviso: un
   fallback dejaría que sea quien ataca el que elige el camino sin cifrar,
   presentándose como un destino que no entiende sobres.

Lo que se verifica de los secretos se mira **en la base del destino**, no en la
respuesta: la respuesta justamente no los trae.

El otro Bot es una segunda instancia real servida por los handlers de verdad, en
vez de un socket, para que el contrato entre dos Bots quede fijado acá.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp import emparejamiento, migracion  # noqa: E402
from webapp.routes import core_api  # noqa: E402

PLUGIN = "cuentas_test"
COLECCION = "cuentas"
LOCALES = {**core_api.LOCAL_PLUGINS, PLUGIN: "webapp.tests.plugin_con_secreto:PLUGIN"}
OTRO = "http://192.168.1.50:8000"

MMD = 'flowchart TD\n    B(inicio)\n    N["core.log | message={}"]\n    B --> N\n'


def _app():
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return app


def _cliente(desde="127.0.0.1"):
    """Comparar y migrar sólo contestan desde la propia máquina: el TestClient
    se presenta como "testclient" si no se le dice, y quedaría del lado de la red."""
    return TestClient(_app(), client=(desde, 50000))


def _entregador(destino):
    """
    Un `_entregar` que entra al otro Bot por su handler de verdad.

    Pasa por `POST /migrar/recibir`, así que el 403 del sobre que no abre y el
    informe clave por clave son los reales, no una imitación.
    """
    def entregar(url, sobre):
        anterior = core_api._instance
        core_api._instance = destino
        try:
            with TestClient(_app()) as cliente:
                r = cliente.post("/api/core/migrar/recibir", json=sobre)
        finally:
            core_api._instance = anterior
        if r.status_code >= 400:
            raise migracion.MigracionError(r.json().get("detail", f"contestó {r.status_code}"))
        return r.json()
    return entregar


@pytest.fixture
def dos_bots(tmp_path, monkeypatch):
    """Dos Bots **ya emparejados**: el destino generó el código y el origen lo pegó."""
    core_api._instance.close()
    core_api._instance = Instance(tmp_path / "aca", local_plugins=LOCALES)
    otro = Instance(tmp_path / "alla", local_plugins=LOCALES)

    generado = emparejamiento.generar(otro.boot.data_dir, "Impresión 2")
    emparejamiento.importar(
        core_api._instance.boot.data_dir, generado["codigo"], OTRO, "Impresión 2")

    monkeypatch.setattr(migracion, "_entregar", _entregador(otro))
    yield _cliente(), otro
    otro.close()


def _migrar(client, **cuerpo):
    r = client.post("/api/core/migrar", json={"destino": OTRO, **cuerpo})
    assert r.status_code == 200, r.text
    return r.json()


def _item_alla(otro, clave):
    definicion = otro.resource_definition(PLUGIN, COLECCION)
    return otro.resource_store(PLUGIN, definicion).read(clave)


def _guardar_item(instancia, clave, item):
    definicion = instancia.resource_definition(PLUGIN, COLECCION)
    instancia.resource_store(PLUGIN, definicion).write(clave, item)


# ── Sin emparejamiento no se migra ──────────────────────────────────────


def test_sin_emparejamiento_no_se_migra(tmp_path, monkeypatch):
    """
    El caso que hace que todo lo demás valga: si acá hubiera un camino en claro,
    alcanzaría con hacerse pasar por un destino viejo para forzarlo.
    """
    core_api._instance.close()
    core_api._instance = Instance(tmp_path / "solo", local_plugins=LOCALES)
    core_api._instance.workflows.save("alta", content=MMD.format("hola"))

    with _cliente() as client:
        r = client.post("/api/core/migrar",
                        json={"destino": OTRO, "que": "flujos", "claves": ["alta"]})

    assert r.status_code == 400
    assert "emparejamiento" in r.json()["detail"]


def test_un_destino_viejo_no_es_una_puerta_en_claro(dos_bots, monkeypatch):
    """Un 404 en el endpoint que recibe se lee como "actualizá el destino"."""
    client, _ = dos_bots
    core_api._instance.workflows.save("alta", content=MMD.format("hola"))

    def sin_endpoint(url, sobre):
        raise migracion.MigracionError(
            f"{url} tiene una versión de la app que no sabe recibir una migración. "
            "Hay que actualizarlo desde Config → Actualizaciones.")

    monkeypatch.setattr(migracion, "_entregar", sin_endpoint)
    r = client.post("/api/core/migrar",
                    json={"destino": OTRO, "que": "flujos", "claves": ["alta"]})

    assert r.status_code == 400
    assert "actualizarlo" in r.json()["detail"]


def test_un_sobre_de_otra_clave_no_abre(dos_bots):
    """Que el sobre abra **es** la autenticación de esta ruta."""
    _, otro = dos_bots
    ajeno = emparejamiento.generar(otro.boot.data_dir, "un tercero")
    # Mismo id, clave cambiada: es lo que tendría quien copió el id de algún lado.
    falso = {"id": ajeno["id"], "clave": emparejamiento._nueva_clave()}

    with pytest.raises(emparejamiento.EmparejamientoError) as error:
        emparejamiento.abrir(otro.boot.data_dir, emparejamiento.sellar(falso, {"que": "flujos"}))

    assert "no hay un emparejamiento que lo explique" in str(error.value)


def test_el_mensaje_no_dice_si_el_id_existia(dos_bots):
    """
    Si el error de "clave equivocada" fuera distinto del de "ese id no existe",
    alcanzaría con leer cuál vuelve para saber si el id acertó. Salió distinto
    en la primera versión y se vio recién probándolo contra dos Bots.
    """
    _, otro = dos_bots
    real = emparejamiento._leer(otro.boot.data_dir)[0]
    con_clave_ajena = {"id": real["id"], "clave": emparejamiento._nueva_clave()}

    with pytest.raises(emparejamiento.EmparejamientoError) as clave_mala:
        emparejamiento.abrir(otro.boot.data_dir,
                             emparejamiento.sellar(con_clave_ajena, {"x": 1}))
    with pytest.raises(emparejamiento.EmparejamientoError) as id_inexistente:
        emparejamiento.abrir(otro.boot.data_dir,
                             {"v": emparejamiento.VERSION_SOBRE,
                              "emparejamiento": "0" * 16, "sobre": "loquesea"})

    assert str(clave_mala.value) == str(id_inexistente.value)


def test_un_sobre_vencido_no_abre(dos_bots, monkeypatch):
    """
    El `ttl` es lo único que hoy acota el replay. Si alguien lo saca, esto se
    pone rojo — que es la idea, porque sin `ttl` un sobre capturado sirve para
    siempre y con eso se revierte un secreto rotado a su valor viejo.
    """
    _, otro = dos_bots
    fila = emparejamiento._leer(otro.boot.data_dir)[0]
    sobre = emparejamiento.sellar(fila, {"que": "flujos", "items": []})

    monkeypatch.setattr(emparejamiento, "TTL_SOBRE", -1)
    with pytest.raises(emparejamiento.EmparejamientoError) as error:
        emparejamiento.abrir(otro.boot.data_dir, sobre)

    assert "vencido" in str(error.value)


def test_un_sobre_de_otra_version_lo_dice(dos_bots):
    _, otro = dos_bots
    fila = emparejamiento._leer(otro.boot.data_dir)[0]
    sobre = {**emparejamiento.sellar(fila, {"que": "flujos"}), "v": 99}

    with pytest.raises(emparejamiento.EmparejamientoError) as error:
        emparejamiento.abrir(otro.boot.data_dir, sobre)

    assert "versión de sobre" in str(error.value)


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
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "abc123"})

    informe = _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
                      claves=["prod"], incluir_secretos=True)

    assert informe["migrados"] == 1
    assert _item_alla(otro, "prod")["token"] == "abc123"
    assert _item_alla(otro, "prod")["url"] == "https://api.test"


def test_la_respuesta_no_trae_el_secreto(dos_bots):
    client, _ = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "abc123"})

    r = client.post("/api/core/migrar", json={
        "destino": OTRO, "que": "registros", "plugin": PLUGIN,
        "coleccion": COLECCION, "claves": ["prod"], "incluir_secretos": True})

    assert "abc123" not in r.text


def test_el_secreto_no_viaja_en_claro(dos_bots, monkeypatch):
    """Lo que sale a la red es el sobre: el valor no tiene que estar ahí."""
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "abc123"})

    visto = {}
    entregar_real = migracion._entregar

    def espiar(url, sobre):
        visto["sobre"] = sobre
        return entregar_real(url, sobre)

    monkeypatch.setattr(migracion, "_entregar", espiar)
    _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
            claves=["prod"], incluir_secretos=True)

    import json
    assert "abc123" not in json.dumps(visto["sobre"])
    assert _item_alla(otro, "prod")["token"] == "abc123"


def test_por_default_el_secreto_no_viaja_y_el_destino_conserva_el_suyo(dos_bots):
    """
    El caso que hace útil el default: corregir la URL de una conexión sin
    tocarle el token al otro lado. El item viaja con el secreto en `None` y el
    destino conserva el que ya tenía — la misma regla que el PUT de la
    colección, y por eso sale del mismo módulo.
    """
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://nueva.test", "token": "el de aca"})
    _guardar_item(otro, "prod",
                  {"name": "prod", "url": "https://vieja.test", "token": "el de alla"})

    informe = _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
                      claves=["prod"])

    assert informe["migrados"] == 1
    assert _item_alla(otro, "prod")["url"] == "https://nueva.test"
    assert _item_alla(otro, "prod")["token"] == "el de alla"


def test_con_incluir_secretos_si_lo_pisa(dos_bots):
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "el de aca"})
    _guardar_item(otro, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "el de alla"})

    _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
            claves=["prod"], incluir_secretos=True)

    assert _item_alla(otro, "prod")["token"] == "el de aca"


def test_un_item_nuevo_sin_secretos_llega_sin_el(dos_bots):
    """No hay nada que conservar del otro lado: queda vacío, y eso es correcto."""
    client, otro = dos_bots
    _guardar_item(core_api._instance, "nueva",
                  {"name": "nueva", "url": "https://api.test", "token": "abc123"})

    _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION, claves=["nueva"])

    assert _item_alla(otro, "nueva")["url"] == "https://api.test"
    assert _item_alla(otro, "nueva").get("token") in (None, "")


def test_una_variable_secreta_se_omite_y_se_dice_cual(dos_bots):
    """
    Una variable **es** su valor: no se puede mandar sin él, como sí se puede
    con un campo de un item. Se omite entera, y con nombre — un salteo
    silencioso es peor que el pisón.
    """
    client, otro = dos_bots
    core_api._instance.env.save("API_KEY", "abc123", secret=True)
    core_api._instance.env.save("TIMEOUT", "30", secret=False)

    informe = _migrar(client, que="env", claves=["API_KEY", "TIMEOUT"])

    assert informe["migrados"] == 1
    assert informe["fallados"] == 1
    omitida = [r for r in informe["resultados"] if r["clave"] == "API_KEY"][0]
    assert "no se pidió incluir secretos" in omitida["error"]
    assert otro.env.get("API_KEY") is None
    assert otro.env.resolve()["TIMEOUT"] == "30"


def test_el_destino_lo_guarda_cifrado_con_su_llave(dos_bots):
    """No se copia ninguna llave: el destino recibe el valor y lo cifra con la suya."""
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "abc123"})

    _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
            claves=["prod"], incluir_secretos=True)

    fila = otro.db.one(
        "SELECT data FROM plugin_items WHERE plugin = ? AND resource = ? AND key = ?",
        (PLUGIN, COLECCION, "prod"))
    assert "abc123" not in fila["data"]
    assert _item_alla(otro, "prod")["token"] == "abc123"


# ── Variables de entorno ────────────────────────────────────────────────


def test_una_variable_secreta_llega_y_sigue_secreta(dos_bots):
    client, otro = dos_bots
    core_api._instance.env.save("API_KEY", "abc123", secret=True)

    informe = _migrar(client, que="env", claves=["API_KEY"], incluir_secretos=True)

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


def test_lo_que_el_destino_no_puede_guardar_no_frena_al_resto(dos_bots):
    """
    Un Bot sin ese plugin es el caso real, y el mensaje tiene que nombrarlo: no
    hay transacción del otro lado, así que informar es mejor que deshacer.
    """
    client, otro = dos_bots
    _guardar_item(core_api._instance, "prod",
                  {"name": "prod", "url": "https://api.test", "token": "x"})
    # El destino deja de conocer la colección, como un Bot sin el plugin.
    otro.resource_definition = lambda plugin, coleccion: None

    informe = _migrar(client, que="registros", plugin=PLUGIN, coleccion=COLECCION,
                      claves=["prod"])

    assert informe["fallados"] == 1
    assert "no tiene la colección" in informe["resultados"][0]["error"]
    assert PLUGIN in informe["resultados"][0]["error"]


def test_sin_nada_elegido_no_se_escribe(dos_bots):
    client, _ = dos_bots

    r = client.post("/api/core/migrar", json={"destino": OTRO, "que": "flujos", "claves": []})

    assert r.status_code == 400
    assert "No se eligió nada" in r.json()["detail"]


def test_comparar_y_migrar_no_contestan_por_la_red(dos_bots):
    """
    Empujar es una acción de quien opera **este** Bot. Nada legítimo la pide
    desde la red: la pantalla corre acá, y un plugin que la ofrezca corre
    adentro del propio Bot y llega por loopback. Abierta, cualquiera de la LAN
    disparaba una migración ajena y, probando direcciones, averiguaba con quién
    está emparejado este Bot.
    """
    _, _ = dos_bots
    de_afuera = _cliente("192.168.1.77")

    assert de_afuera.post("/api/core/diff",
                          json={"destino": OTRO, "que": "flujos"}).status_code == 403
    assert de_afuera.post("/api/core/migrar",
                          json={"destino": OTRO, "que": "flujos",
                                "claves": ["x"]}).status_code == 403


def test_recibir_un_sobre_si_contesta_por_la_red(dos_bots):
    """El otro lado de la misma moneda: ahí la credencial es la clave."""
    _, otro = dos_bots
    fila = emparejamiento._leer(otro.boot.data_dir)[0]
    sobre = emparejamiento.sellar(fila, {"que": "flujos", "items": []})

    anterior = core_api._instance
    core_api._instance = otro
    try:
        r = _cliente("192.168.1.77").post("/api/core/migrar/recibir", json=sobre)
    finally:
        core_api._instance = anterior

    assert r.status_code == 200, r.text


def test_sin_emparejamiento_el_error_nombra_las_dos_causas(dos_bots):
    """
    La dirección sale casi siempre de una colección, así que "no hay
    emparejamiento" puede ser que falte emparejar o que esté mal escrita allá.
    Sin nombrar las dos, se busca el problema en el lugar equivocado.
    """
    client, _ = dos_bots
    core_api._instance.workflows.save("alta", content=MMD.format("hola"))

    r = client.post("/api/core/migrar", json={"destino": "http://192.168.1.99:8000",
                                              "que": "flujos", "claves": ["alta"]})

    assert r.status_code == 400
    detalle = r.json()["detail"]
    assert "falta emparejar" in detalle
    assert "revisala ahí" in detalle


def test_migrar_contra_uno_mismo_no_se_intenta(dos_bots, monkeypatch):
    client, _ = dos_bots
    monkeypatch.setattr(core_api, "_url_app", lambda: OTRO)

    r = client.post("/api/core/migrar",
                    json={"destino": OTRO, "que": "flujos", "claves": ["alta"]})

    assert r.status_code == 400
    assert "este mismo Bot" in r.json()["detail"]

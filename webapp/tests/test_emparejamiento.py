"""
El emparejamiento entre dos Bots: la clave compartida y su código.

Lo que importa que quede fijado:

- **La clave no sale por la API**, ni para mostrarla. El código se ve una vez,
  al generarlo, y no se puede volver a pedir — una clave que se relee por la API
  es una clave que sale por la API.
- **El id es propio y estable**, no la URL: son PCs con DHCP y un emparejamiento
  identificado por IP apunta en silencio a otra máquina cuando cambia.
- **No depende de ningún plugin.** Si el plugin `bots` no está instalado, esto
  funciona igual: es la restricción de que si un plugin no está, nada se rompe.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp import emparejamiento  # noqa: E402
from webapp.routes import core_api  # noqa: E402

OTRO = "http://192.168.1.50:8000"


def _cliente(desde: str):
    """Un cliente que se presenta desde esa IP: es lo que mira el guardia local."""
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app, client=(desde, 50000))


@pytest.fixture
def client(tmp_path):
    core_api._instance.close()
    # Sin plugins locales: el emparejamiento no puede depender de ninguno.
    core_api._instance = Instance(tmp_path, local_plugins={})
    yield _cliente("127.0.0.1")


@pytest.fixture
def data_dir(client):
    return core_api._instance.boot.data_dir


def test_generar_devuelve_el_codigo_una_sola_vez(client):
    r = client.post("/api/core/emparejamientos", json={"nombre": "Impresión 2"})
    assert r.status_code == 200, r.text
    generado = r.json()
    assert "." in generado["codigo"]

    listado = client.get("/api/core/emparejamientos").json()["items"]

    assert [i["nombre"] for i in listado] == ["Impresión 2"]
    # Ni la clave ni el código vuelven a salir.
    assert "clave" not in listado[0]
    assert "codigo" not in listado[0]
    assert generado["codigo"].split(".")[1] not in json.dumps(listado)


def test_el_que_empuja_importa_el_codigo(client, data_dir, tmp_path):
    otro = Instance(tmp_path / "alla", local_plugins={})
    generado = emparejamiento.generar(otro.boot.data_dir, "Impresión 2")

    r = client.post("/api/core/emparejamientos/importar",
                    json={"codigo": generado["codigo"], "url": OTRO, "nombre": "Impresión 2"})

    assert r.status_code == 200, r.text
    assert r.json()["url"] == OTRO
    # El mismo id de los dos lados: es lo que deja reconocer el sobre.
    assert r.json()["id"] == generado["id"]
    assert emparejamiento.para_url(data_dir, OTRO)["id"] == generado["id"]
    otro.close()


def test_un_codigo_cortado_lo_dice_en_castellano(client):
    """Copiar de menos es el error real: el código tiene un punto en el medio."""
    r = client.post("/api/core/emparejamientos/importar",
                    json={"codigo": "abcdef123456", "url": OTRO})

    assert r.status_code == 400
    assert "código de emparejamiento" in r.json()["detail"]


def test_un_codigo_con_la_clave_mal_copiada_no_entra(client, tmp_path):
    otro = Instance(tmp_path / "alla", local_plugins={})
    generado = emparejamiento.generar(otro.boot.data_dir, "x")
    ident, clave = generado["codigo"].split(".")

    r = client.post("/api/core/emparejamientos/importar",
                    json={"codigo": f"{ident}.{clave[:-6]}", "url": OTRO})

    assert r.status_code == 400
    assert "copió cortado" in r.json()["detail"]
    otro.close()


def test_la_url_se_puede_cambiar_sin_perder_el_emparejamiento(client, data_dir, tmp_path):
    """El caso de DHCP: la máquina es la misma, la IP no."""
    otro = Instance(tmp_path / "alla", local_plugins={})
    generado = emparejamiento.generar(otro.boot.data_dir, "Impresión 2")
    client.post("/api/core/emparejamientos/importar",
                json={"codigo": generado["codigo"], "url": OTRO, "nombre": "Impresión 2"})

    nueva = "http://192.168.1.77:8000"
    client.post("/api/core/emparejamientos/importar",
                json={"codigo": generado["codigo"], "url": nueva, "nombre": "Impresión 2"})

    listado = client.get("/api/core/emparejamientos").json()["items"]
    assert len(listado) == 1
    assert listado[0]["id"] == generado["id"]
    assert listado[0]["url"] == nueva
    otro.close()


def test_olvidar_lo_saca(client, tmp_path):
    otro = Instance(tmp_path / "alla", local_plugins={})
    generado = emparejamiento.generar(otro.boot.data_dir, "x")
    client.post("/api/core/emparejamientos/importar",
                json={"codigo": generado["codigo"], "url": OTRO})

    r = client.delete(f"/api/core/emparejamientos/{generado['id']}")

    assert r.status_code == 200
    assert client.get("/api/core/emparejamientos").json()["items"] == []
    otro.close()


def test_olvidar_uno_que_no_esta_es_404(client):
    assert client.delete("/api/core/emparejamientos/nohay").status_code == 404


def test_sin_nombre_no_se_genera(client):
    """Sin nombre, una lista de emparejamientos es una lista de ids."""
    r = client.post("/api/core/emparejamientos", json={"nombre": "   "})

    assert r.status_code == 400
    assert "nombre" in r.json()["detail"]


def test_la_clave_se_guarda_fuera_de_la_base(client, data_dir):
    """
    Mismo criterio que `secret.key` del núcleo: un backup del `.db` no se lleva
    con qué descifrar. Y `data/` queda fuera de `fs_root`, así que un flujo con
    el port `fs` tampoco lo alcanza.
    """
    generado = emparejamiento.generar(data_dir, "Impresión 2")

    archivo = pathlib.Path(data_dir) / emparejamiento.ARCHIVO
    assert archivo.is_file()
    assert generado["codigo"].split(".")[1] in archivo.read_text(encoding="utf-8")


def test_el_sobre_lleva_la_version_afuera_del_cifrado(client, data_dir):
    """Si fuera adentro habría que descifrar para saber cómo parsear."""
    emparejamiento.generar(data_dir, "x")
    fila = emparejamiento._leer(data_dir)[0]

    sobre = emparejamiento.sellar(fila, {"hola": "mundo"})

    assert sobre["v"] == emparejamiento.VERSION_SOBRE
    assert sobre["emparejamiento"] == fila["id"]
    assert "mundo" not in json.dumps(sobre)


def test_lo_que_se_sella_se_abre(client, data_dir):
    emparejamiento.generar(data_dir, "x")
    fila = emparejamiento._leer(data_dir)[0]

    _, contenido = emparejamiento.abrir(data_dir, emparejamiento.sellar(fila, {"hola": "mundo"}))

    assert contenido == {"hola": "mundo"}


# ── Emparejar se hace sentado en la máquina ─────────────────────────────


@pytest.fixture
def desde_la_red(client):
    """Otra PC de la LAN, contra el mismo Bot."""
    return _cliente("192.168.1.77")


def test_no_se_puede_pedir_un_codigo_por_la_red(desde_la_red):
    """
    El agujero que hacía falso todo lo demás: si esto contesta por la red,
    cualquiera pide un código y queda emparejado, y el sobre deja de autenticar
    a nadie — protege el secreto de quien escucha, no de quien lo pide.
    """
    r = desde_la_red.post("/api/core/emparejamientos", json={"nombre": "x"})

    assert r.status_code == 403
    assert "desde el propio Bot" in r.json()["detail"]


def test_tampoco_listar_por_la_red(desde_la_red):
    """La lista es la topología de la flota, y publica los ids."""
    assert desde_la_red.get("/api/core/emparejamientos").status_code == 403


def test_tampoco_importar_ni_olvidar_por_la_red(desde_la_red):
    """Si `olvidar` contesta por la red, cualquiera desemparejea a cualquiera."""
    assert desde_la_red.post("/api/core/emparejamientos/importar",
                             json={"codigo": "a.b", "url": "http://x"}).status_code == 403
    assert desde_la_red.delete("/api/core/emparejamientos/loquesea").status_code == 403


def test_recibir_un_sobre_si_contesta_por_la_red(desde_la_red, data_dir):
    """Ahí la credencial es la clave, así que tiene que seguir abierto."""
    emparejamiento.generar(data_dir, "x")
    fila = emparejamiento._leer(data_dir)[0]
    sobre = emparejamiento.sellar(fila, {"que": "flujos", "items": []})

    r = desde_la_red.post("/api/core/migrar/recibir", json=sobre)

    assert r.status_code == 200, r.text


def test_importar_avisa_si_pisa_uno_que_ya_estaba(client, data_dir, tmp_path):
    """
    Pisar es legítimo —así se cambia la IP del otro Bot— pero en silencio no: el
    que se pierde hay que rehacerlo a mano en las dos máquinas.
    """
    otro = Instance(tmp_path / "alla", local_plugins={})
    generado = emparejamiento.generar(otro.boot.data_dir, "Impresión 2")
    primera = client.post("/api/core/emparejamientos/importar",
                          json={"codigo": generado["codigo"], "url": "http://uno",
                                "nombre": "uno"}).json()
    segunda = client.post("/api/core/emparejamientos/importar",
                          json={"codigo": generado["codigo"], "url": "http://dos",
                                "nombre": "dos"}).json()

    assert primera["reemplazo"] is None
    assert segunda["reemplazo"]["nombre"] == "uno"
    otro.close()

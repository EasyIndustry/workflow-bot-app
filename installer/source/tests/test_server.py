"""
El servidor del instalador: rutas, errores y que no sirva de más.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from installer.source.server import Handler


@pytest.fixture
def servidor():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def pedir(puerto, metodo, ruta, cuerpo=None):
    conexion = HTTPConnection("127.0.0.1", puerto, timeout=10)
    crudo = json.dumps(cuerpo).encode() if cuerpo is not None else None
    conexion.request(metodo, ruta, body=crudo, headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    datos = respuesta.read()
    conexion.close()
    return respuesta.status, datos


def json_de(datos):
    return json.loads(datos.decode("utf-8"))


def test_sirve_el_wizard(servidor):
    estado, cuerpo = pedir(servidor, "GET", "/")
    assert estado == 200
    assert b"<title>Instalar Bot</title>" in cuerpo


def test_sirve_los_estaticos(servidor):
    for archivo in ("/wizard.css", "/wizard.js"):
        estado, cuerpo = pedir(servidor, "GET", archivo)
        assert estado == 200, archivo
        assert cuerpo


def test_no_sale_de_su_carpeta(servidor):
    """Servir archivos por nombre obliga a acotarse a la propia carpeta."""
    for intento in ("/../../etc/passwd", "/../pasos.py", "/../server.py"):
        estado, _ = pedir(servidor, "GET", intento)
        assert estado == 404, intento


def test_un_estatico_que_no_existe_es_404(servidor):
    assert pedir(servidor, "GET", "/nada.js")[0] == 404


def test_sugerencia(servidor):
    estado, cuerpo = pedir(servidor, "GET", "/api/sugerencia")
    assert estado == 200
    assert json_de(cuerpo)["ruta"]


def test_revisar(servidor, tmp_path):
    estado, cuerpo = pedir(servidor, "POST", "/api/revisar", {"ruta": str(tmp_path / "Bot")})
    assert estado == 200
    assert json_de(cuerpo)["valida"]


def test_maquina(servidor, tmp_path):
    estado, cuerpo = pedir(servidor, "POST", "/api/maquina", {"ruta": str(tmp_path)})
    assert estado == 200
    assert len(json_de(cuerpo)["chequeos"]) == 3


def test_plan(servidor, tmp_path):
    estado, cuerpo = pedir(servidor, "POST", "/api/plan", {"ruta": str(tmp_path / "Bot")})
    assert estado == 200
    assert json_de(cuerpo)["caja"].endswith("workspace")


def test_instalar_y_no_instalar_dos_veces(servidor, tmp_path):
    destino = {"ruta": str(tmp_path / "Bot")}

    estado, cuerpo = pedir(servidor, "POST", "/api/instalar", destino)
    assert estado == 200
    assert json_de(cuerpo)["llave_existe"]

    estado, cuerpo = pedir(servidor, "POST", "/api/instalar", destino)
    assert estado == 400
    assert "Ya hay una instalación" in json_de(cuerpo)["error"]


def test_un_cuerpo_ilegible_vuelve_como_error(servidor):
    """
    Un instalador que muere en silencio deja media instalación y ninguna
    explicación. Cualquier fallo vuelve como texto.
    """
    conexion = HTTPConnection("127.0.0.1", servidor, timeout=10)
    conexion.request("POST", "/api/revisar", body=b"no-json")
    respuesta = conexion.getresponse()
    cuerpo = respuesta.read()
    conexion.close()

    assert respuesta.status == 400
    assert "cuerpo inválido" in json_de(cuerpo)["error"]


def test_una_ruta_de_api_inexistente_es_404(servidor):
    for metodo, ruta in (("GET", "/api/nada"), ("POST", "/api/tampoco")):
        estado, cuerpo = pedir(servidor, metodo, ruta, {} if metodo == "POST" else None)
        assert estado == 404
        assert json_de(cuerpo)["error"] == "no existe"


def test_abrir_sin_instalacion_es_400(servidor, tmp_path):
    estado, cuerpo = pedir(servidor, "POST", "/api/abrir", {"ruta": str(tmp_path / "nada")})
    assert estado == 400
    assert "no hay una instalación" in json_de(cuerpo)["error"]

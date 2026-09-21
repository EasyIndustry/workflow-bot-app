"""
Los programas que un flujo puede correr, editables desde la pantalla.

`process_allowlist` tiene tres estados y el del medio es el que muerde: la
clave ausente es "cualquiera", presente y vacía es "ninguno", con nombres es
"sólo ésos". Una instalación nace en "ninguno" —el wizard lo escribe así a
propósito— así que quien opera ve `PortError: 'tasklist' no está en la lista
de comandos permitidos. Permitidos: ninguno` adentro de un run, que parece un
problema del flujo, y hasta acá la única salida era editar `boot.env` a mano
en cada máquina.

Lo que se prueba es que el modo viaje explícito: deducirlo de la lista haría
que borrar el último nombre bloqueara todo en silencio.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core import boot  # noqa: E402
from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402


def _cliente(tmp_path, allowlist):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path)
    core_api._instance.boot = dataclasses.replace(
        core_api._instance.boot, process_allowlist=allowlist)
    core_api.ROOT = tmp_path
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _guardar(client, modo, ejecutables=()):
    return client.put("/api/core/limites/programas",
                      json={"modo": modo, "ejecutables": list(ejecutables)})


def _releer(tmp_path):
    return boot.load(tmp_path, {}).process_allowlist


def test_los_tres_estados_se_leen_distinto(tmp_path):
    for allowlist, modo in [(None, "cualquiera"), ((), "ninguno"), (("tasklist",), "lista")]:
        client = _cliente(tmp_path, allowlist)
        assert client.get("/api/core/limites").json()["programas"]["modo"] == modo


def test_guardar_una_lista_la_deja_en_boot_env(tmp_path):
    client = _cliente(tmp_path, ())

    r = _guardar(client, "lista", ["tasklist", "Toothform.exe"])

    assert r.status_code == 200, r.text
    assert r.json()["restart_required"] is True
    assert _releer(tmp_path) == ("tasklist", "Toothform.exe")


def test_cualquiera_saca_la_clave_y_ninguno_la_deja_vacia(tmp_path):
    """La diferencia entera: una permite todo y la otra nada, y se ven igual de vacías."""
    client = _cliente(tmp_path, ("tasklist",))
    assert _guardar(client, "cualquiera").status_code == 200
    assert _releer(tmp_path) is None

    client = _cliente(tmp_path, ("tasklist",))
    assert _guardar(client, "ninguno").status_code == 200
    assert _releer(tmp_path) == ()


def test_una_lista_vacia_no_se_toma_por_ninguno(tmp_path):
    """Borrar el último nombre no puede bloquear todo sin decirlo."""
    client = _cliente(tmp_path, ("tasklist",))
    assert _guardar(client, "lista", ["tasklist"]).status_code == 200

    r = _guardar(client, "lista", [])

    assert r.status_code == 400
    assert "al menos uno" in r.json()["detail"]["errors"][0]
    assert _releer(tmp_path) == ("tasklist",), "lo que ya estaba escrito no se tocó"


def test_un_nombre_con_coma_se_rechaza(tmp_path):
    """La coma separa en el archivo: se releería como dos programas inexistentes."""
    client = _cliente(tmp_path, ())

    r = _guardar(client, "lista", ["tasklist,Toothform.exe"])

    assert r.status_code == 400
    assert "coma" in r.json()["detail"]["errors"][0]


def test_dos_nombres_del_mismo_programa_se_dicen(tmp_path):
    """El núcleo compara por stem en minúscula: son el mismo y uno se perdería."""
    client = _cliente(tmp_path, ())

    r = _guardar(client, "lista", ["Toothform.exe", "toothform"])

    assert r.status_code == 400
    assert "el mismo programa" in r.json()["detail"]["errors"][0]


def test_un_programa_que_no_esta_en_la_maquina_se_guarda_y_se_avisa(tmp_path):
    """Se puede configurar antes de instalar el programa; el núcleo lo trata igual."""
    client = _cliente(tmp_path, ())

    r = _guardar(client, "lista", ["programa_que_no_existe_pgqjy"])

    assert r.status_code == 200
    assert _releer(tmp_path) == ("programa_que_no_existe_pgqjy",)
    assert any("no se encontró" in a for a in r.json()["avisos"])


def test_lo_que_rige_y_lo_que_va_a_regir_se_distinguen(tmp_path):
    """
    Entre guardar y reiniciar son dos cosas distintas. Sin separarlas, la
    pantalla se redibuja con el valor viejo y guardar parece no haber hecho
    nada.
    """
    client = _cliente(tmp_path, ())

    _guardar(client, "lista", ["tasklist"])
    p = client.get("/api/core/limites").json()["programas"]

    assert p["modo"] == "ninguno", "el proceso sigue corriendo con lo de antes"
    assert p["escrito"]["modo"] == "lista"
    assert [e["nombre"] for e in p["escrito"]["ejecutables"]] == ["tasklist"]
    assert p["pendiente"] is True


def test_guardar_programas_no_pierde_las_raices(tmp_path):
    """El archivo se regenera entero: las dos mitades de la pantalla conviven."""
    (tmp_path / "caja").mkdir()
    core_api._instance = Instance(tmp_path)
    core_api._instance.boot = dataclasses.replace(
        core_api._instance.boot, fs_root=str(tmp_path / "caja"), process_allowlist=())
    core_api.ROOT = tmp_path
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    client = TestClient(app)

    assert _guardar(client, "lista", ["tasklist"]).status_code == 200

    releido = boot.load(tmp_path, {})
    assert releido.process_allowlist == ("tasklist",)
    assert str(releido.fs_root) == str(tmp_path / "caja")

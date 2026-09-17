"""
Los límites de la instalación en `GET /overview` y el diagnóstico completo en
`GET /doctor`.

Los dos salen del mismo problema de producción: `fs_root` apuntaba a una
carpeta que no existía, la instalación arrancó igual y el error apareció
mucho después adentro de un run, como `PortError: ruta fuera del árbol
permitido` — un mensaje que parece del flujo. Nada en la app mostraba el
valor, y el chequeo que sí lo detecta no se estaba corriendo desde acá.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.instance import Instance  # noqa: E402
from webapp.routes import core_api  # noqa: E402


def _cliente(tmp_path, **kwargs):
    core_api._instance.close()
    core_api._instance = Instance(tmp_path, **kwargs)
    app = FastAPI()
    app.include_router(core_api.router, prefix="/api/core")
    return TestClient(app)


def _con_fs(**campos):
    """`BootConfig` es frozen: se reemplaza entero, como al releer boot.env."""
    core_api._instance.boot = dataclasses.replace(core_api._instance.boot, **campos)


def _checks(client) -> dict[str, dict]:
    return {c["name"]: c for c in client.get("/api/core/doctor").json()["checks"]}


def test_overview_publica_la_raiz_de_archivos(tmp_path):
    caja = tmp_path / "workspace"
    caja.mkdir()
    client = _cliente(tmp_path)
    _con_fs(fs_root=str(caja))

    datos = client.get("/api/core/overview").json()

    # Una sola raíz viaja igual que varias, con el alias vacío: la pantalla no
    # tiene que saber si la instalación usa `fs_root` o `fs_roots`.
    assert datos["fs_roots"] == {"": str(caja)}


def test_overview_publica_todas_las_raices_con_su_alias(tmp_path):
    """
    core#23: un workspace local y un share de red a la vez. Mostrar sólo la
    primera sería media verdad, y es la mitad que no explica por qué un flujo
    llega a la otra.
    """
    casa, origen = tmp_path / "workspace", tmp_path / "share"
    casa.mkdir()
    origen.mkdir()
    client = _cliente(tmp_path)
    _con_fs(fs_roots={"casa": str(casa), "origen": str(origen)})

    assert client.get("/api/core/overview").json()["fs_roots"] == {
        "casa": str(casa), "origen": str(origen),
    }


def test_sin_raiz_declarada_overview_lo_dice_con_none(tmp_path):
    """`None` es "todo el disco", y la pantalla tiene que poder decir eso."""
    client = _cliente(tmp_path)
    _con_fs(fs_root=None, fs_roots=None)

    assert client.get("/api/core/overview").json()["fs_roots"] is None


def test_el_diagnostico_corre_los_chequeos_de_arranque(tmp_path):
    """
    El que faltaba: sin `boot`, `run_checks` saltea `check_boot`, que es el
    único que dice que `fs_root` apunta a una carpeta inexistente. Desde la
    web ese aviso no aparecía nunca.
    """
    client = _cliente(tmp_path)
    _con_fs(fs_root=str(tmp_path / "no-existe"))

    arranque = _checks(client)["Arranque"]

    assert arranque["level"] == "warn"
    assert any("no existe" in d for d in arranque["detail"])


def test_el_diagnostico_ve_los_flujos_guardados(tmp_path):
    """
    Sin `workflows`, "Flujos" avisaba "no hay ninguno guardado" en una
    instalación que tenía once. Un diagnóstico que miente en lo que se
    comprueba de un vistazo no se lee más.
    """
    client = _cliente(tmp_path)
    core_api._instance.workflows.save_mmd("demo", "flowchart TD\n    SN(inicio)\n")

    flujos = _checks(client)["Flujos"]

    assert flujos["level"] == "ok"
    assert "1 flujos" in flujos["message"]

"""Tests de `webapp/ubicacion.py`: quién decide contra qué instalación arranca la webapp."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import ubicacion  # noqa: E402


@pytest.fixture
def entorno(tmp_path):
    return {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "LOCALAPPDATA": str(tmp_path / "cfg")}


def test_registrar_y_leer(tmp_path, entorno):
    raiz = tmp_path / "Bot"
    raiz.mkdir()
    archivo = ubicacion.registrar(raiz, entorno)
    assert archivo.is_file()
    assert ubicacion.ultima(entorno) == raiz.resolve()


def test_una_anotacion_a_una_carpeta_borrada_no_vale(tmp_path, entorno):
    raiz = tmp_path / "Bot"
    raiz.mkdir()
    ubicacion.registrar(raiz, entorno)
    raiz.rmdir()
    assert ubicacion.ultima(entorno) is None


def test_un_archivo_roto_no_revienta(tmp_path, entorno):
    carpeta = ubicacion.carpeta_config(entorno)
    carpeta.mkdir(parents=True)
    (carpeta / ubicacion.ARCHIVO).write_text("{no es json", encoding="utf-8")
    assert ubicacion.ultima(entorno) is None


def test_prioridad_explicito_programa_anotada_programa(tmp_path, entorno):
    programa = tmp_path / "programa"
    programa.mkdir()
    anotada = tmp_path / "Bot"
    anotada.mkdir()
    explicita = tmp_path / "Otra"
    explicita.mkdir()

    # 4. nada: el programa pelado
    assert ubicacion.resolver_root(programa, None, entorno) == programa
    # 3. la anotada
    ubicacion.registrar(anotada, entorno)
    assert ubicacion.resolver_root(programa, None, entorno) == anotada.resolve()
    # 2. el programa si él mismo es una instalación (el repo de desarrollo)
    (programa / "data").mkdir()
    assert ubicacion.resolver_root(programa, None, entorno) == programa
    # 1. lo explícito, por argumento o por BOT_ROOT
    assert ubicacion.resolver_root(programa, str(explicita), entorno) == explicita.resolve()
    assert ubicacion.resolver_root(programa, None, {**entorno, "BOT_ROOT": str(explicita)}) == explicita.resolve()


# ── Un data/ suelto en la carpeta del programa ─────────────────────────


def test_un_programa_instalado_con_data_suelto_no_secuestra_la_raiz(tmp_path):
    """
    Si un arranque no encuentra la instalación anotada, cae en la carpeta del
    programa y ahí se crea `data/`. Sin esto, desde ese momento esa carpeta
    "es" una instalación y gana sobre la anotada: el cliente abre el Bot, ve
    una instalación vacía y la suya queda intacta al lado. Pasó de verdad.
    """
    programa = tmp_path / "Programs" / "Bot"
    (programa / "runtime").mkdir(parents=True)     # lo que trae el .exe
    (programa / "data").mkdir()                    # el accidente
    instalacion = tmp_path / "User" / "Bot"
    (instalacion / "data").mkdir(parents=True)
    (instalacion / "boot.env").write_text("root=.", encoding="utf-8")

    assert ubicacion.es_instalacion(programa) is False
    entorno = {"LOCALAPPDATA": str(tmp_path / "cfg")}
    ubicacion.registrar(instalacion, entorno)
    assert ubicacion.resolver_root(programa, entorno=entorno) == instalacion


def test_un_programa_instalado_con_boot_env_si_es_instalacion(tmp_path):
    """Portable de verdad: el wizard escribió boot.env ahí. Eso no es un accidente."""
    programa = tmp_path / "Bot"
    (programa / "runtime").mkdir(parents=True)
    (programa / "boot.env").write_text("root=.", encoding="utf-8")

    assert ubicacion.es_instalacion(programa) is True


def test_el_repo_sigue_alcanzando_con_data(tmp_path):
    """La regla 2 existe para esto: en un checkout, data/ vive al lado del código."""
    repo = tmp_path / "workflow-bot-app"
    (repo / "data").mkdir(parents=True)

    assert ubicacion.es_instalacion(repo) is True
    assert ubicacion.resolver_root(repo, entorno={"LOCALAPPDATA": str(tmp_path / "cfg")}) == repo

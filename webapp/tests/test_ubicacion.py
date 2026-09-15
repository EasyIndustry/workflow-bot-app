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

"""Tests de `webapp/vueltas.py`: la vuelta del navegador a una Action (#12)."""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import vueltas  # noqa: E402


class _Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


def test_un_state_se_usa_una_sola_vez_y_devuelve_su_item():
    v = vueltas.Vueltas()
    estado = v.emitir("firma", "autorizar", "google")
    assert v.consumir(estado, "firma", "autorizar") == "google"
    with pytest.raises(vueltas.VueltaError, match="ya se usó"):
        v.consumir(estado, "firma", "autorizar")


def test_sin_state_se_rechaza():
    with pytest.raises(vueltas.VueltaError, match="no trae el state"):
        vueltas.Vueltas().consumir(None, "firma", "autorizar")


def test_un_state_de_otra_accion_no_sirve_y_se_quema():
    v = vueltas.Vueltas()
    estado = v.emitir("firma", "autorizar", None)
    with pytest.raises(vueltas.VueltaError, match="otra acción"):
        v.consumir(estado, "firma", "otra")
    with pytest.raises(vueltas.VueltaError):
        v.consumir(estado, "firma", "autorizar")


def test_un_state_vence():
    reloj = _Reloj()
    v = vueltas.Vueltas(reloj=reloj)
    estado = v.emitir("firma", "autorizar", None)
    reloj.ahora += vueltas.VIGENCIA + 1
    with pytest.raises(vueltas.VueltaError, match="venció"):
        v.consumir(estado, "firma", "autorizar")


def test_el_resultado_se_lee_una_vez():
    v = vueltas.Vueltas()
    clave = v.guardar_resultado({"result": {"status": "ok"}})
    assert v.tomar_resultado(clave) == {"result": {"status": "ok"}}
    assert v.tomar_resultado(clave) is None


def test_url_estable_por_accion():
    assert vueltas.url_de_vuelta("http://127.0.0.1:8000/", "mi plugin", "autorizar") == \
        "http://127.0.0.1:8000/api/core/vuelta/mi%20plugin/autorizar"


def test_la_query_de_una_vuelta_no_queda_en_el_log():
    """Uvicorn loguea la ruta con la query: ahí viaja el código de autorización."""
    registro = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/core/vuelta/firma/autorizar?code=SECRETO&state=abc", "1.1", 303), None,
    )
    vueltas.TaparQueryDeVueltas().filter(registro)
    texto = registro.getMessage()
    assert "SECRETO" not in texto and "state=abc" not in texto
    assert "/api/core/vuelta/firma/autorizar?…" in texto


def test_otras_rutas_quedan_como_estaban():
    registro = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s", ("/api/core/runs?limit=5",), None)
    vueltas.TaparQueryDeVueltas().filter(registro)
    assert registro.getMessage() == "/api/core/runs?limit=5"

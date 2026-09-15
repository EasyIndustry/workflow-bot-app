"""El ícono de la bandeja, sin bandeja: el menú como datos y la dirección que se copia."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import bandeja  # noqa: E402


def _estado(tmp_path, en_red=False):
    return bandeja.Estado(url="http://127.0.0.1:8000", puerto=8000, raiz=tmp_path, en_red=en_red, version="0.3.0")


def _acciones(registro):
    return bandeja.Acciones(
        reiniciar=lambda: registro.append("reiniciar"),
        cerrar=lambda: registro.append("cerrar"),
        habilitar_red=lambda: registro.append("red"),
        abrir=lambda url: registro.append(f"abrir {url}"),
    )


def _textos(entradas):
    return [e[0] if e is not None else "—" for e in entradas]


def test_sin_red_ofrece_habilitarla_y_lo_basico_para_operar_sin_consola(tmp_path):
    registro = []
    entradas = bandeja.opciones(_estado(tmp_path), _acciones(registro))

    assert _textos(entradas) == [
        "Abrir Bot",
        "Habilitar acceso desde otras PCs (reinicia)",
        "—",
        "Ver registro (webapp.log)",
        "Ver llamadas en una consola",
        "—",
        "Reiniciar Bot",
        "Cerrar Bot",
    ]
    entradas[0][1]()
    entradas[1][1]()
    entradas[-2][1]()
    entradas[-1][1]()
    assert registro == ["abrir http://127.0.0.1:8000", "red", "reiniciar", "cerrar"]


def test_en_red_ofrece_copiar_la_direccion_que_otra_pc_puede_usar(tmp_path, monkeypatch):
    monkeypatch.setattr(bandeja, "direccion_red", lambda: "192.168.1.20")
    copiado = []
    monkeypatch.setattr(bandeja, "copiar_al_portapapeles", lambda t: copiado.append(t) or True)

    entradas = bandeja.opciones(_estado(tmp_path, en_red=True), _acciones([]))

    assert entradas[1][0] == "Copiar dirección para otras PCs (http://192.168.1.20:8000)"
    entradas[1][1]()
    assert copiado == ["http://192.168.1.20:8000"]
    assert "Habilitar acceso" not in " ".join(_textos(entradas))


def test_en_red_pero_sin_ip_lo_dice_en_vez_de_copiar_localhost(tmp_path, monkeypatch):
    monkeypatch.setattr(bandeja, "direccion_red", lambda: None)
    entradas = bandeja.opciones(_estado(tmp_path, en_red=True), _acciones([]))
    assert entradas[1][0].startswith("Sin red")


def test_url_red_arma_la_direccion_con_el_puerto():
    assert bandeja.url_red(8010, "10.0.0.5") == "http://10.0.0.5:8010"
    assert bandeja.url_red(8010, None) in (None,) or bandeja.url_red(8010, None).startswith("http://")


def test_direccion_red_nunca_devuelve_loopback():
    ip = bandeja.direccion_red()
    assert ip is None or not ip.startswith("127.")

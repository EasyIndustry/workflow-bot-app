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


# ── Copiar dice qué pasó, y la IP aparece aunque no haya ruta hacia afuera ──


def test_copiar_avisa_que_copio(monkeypatch):
    monkeypatch.setattr(bandeja, "copiar_al_portapapeles", lambda t: True)
    avisos = []
    assert bandeja.copiar_y_avisar("http://192.168.3.26:8000", avisos.append) is True
    assert avisos == ["Copiado: http://192.168.3.26:8000"]


def test_si_no_puede_copiar_lo_dice_y_muestra_la_direccion(monkeypatch):
    """
    Antes fallaba en silencio: el portapapeles quedaba con lo que tuviera de
    antes —un 127.0.0.1 copiado de la barra del navegador— y se leía como que
    Bot había copiado mal. Un clic en la bandeja no tiene otra pantalla.
    """
    monkeypatch.setattr(bandeja, "copiar_al_portapapeles", lambda t: False)
    avisos = []
    assert bandeja.copiar_y_avisar("http://192.168.3.26:8000", avisos.append) is False
    assert len(avisos) == 1 and "No se pudo copiar" in avisos[0] and "http://192.168.3.26:8000" in avisos[0]


def test_el_menu_copia_con_aviso_por_el_canal_de_acciones(tmp_path, monkeypatch):
    monkeypatch.setattr(bandeja, "direccion_red", lambda: "192.168.1.20")
    monkeypatch.setattr(bandeja, "copiar_al_portapapeles", lambda t: False)
    avisos = []
    acciones = _acciones([])
    acciones.notificar = avisos.append
    entradas = bandeja.opciones(_estado(tmp_path, en_red=True), acciones)
    entradas[1][1]()
    assert avisos and "http://192.168.1.20:8000" in avisos[0]


def test_sin_ruta_hacia_afuera_usa_la_ip_del_adaptador_de_oficina(monkeypatch):
    """
    Una PC de planta sin internet no tiene puerta de enlace: ninguna ruta
    hacia 10.x ni hacia 8.8.8.8. Antes eso era "Sin red" en una máquina que
    estaba en la red. La virtual (172.21, WSL) y la de autoconfiguración
    (169.254) no sirven para otra PC.
    """
    monkeypatch.setattr(bandeja, "_ip_de_salida_hacia", lambda destino: None)
    monkeypatch.setattr(bandeja, "_ips_de_los_adaptadores",
                        lambda: ["127.0.0.1", "172.21.192.1", "169.254.7.7", "192.168.3.26"])
    assert bandeja.direccion_red() == "192.168.3.26"


def test_con_ruta_manda_la_tabla_de_rutas_y_no_los_adaptadores(monkeypatch):
    monkeypatch.setattr(bandeja, "_ip_de_salida_hacia", lambda destino: "10.0.5.14" if destino.startswith("10.") else None)
    monkeypatch.setattr(bandeja, "_ips_de_los_adaptadores", lambda: ["192.168.99.1"])
    assert bandeja.direccion_red() == "10.0.5.14"


def test_sin_ninguna_ip_util_no_inventa_una(monkeypatch):
    monkeypatch.setattr(bandeja, "_ip_de_salida_hacia", lambda destino: None)
    monkeypatch.setattr(bandeja, "_ips_de_los_adaptadores", lambda: ["127.0.0.1", "169.254.1.1"])
    assert bandeja.direccion_red() is None

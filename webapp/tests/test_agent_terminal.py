"""
Tests de `TerminalSession` contra comandos reales chicos (`sh -c`), no contra
un CLI de un vendor — eso no está instalado en ningún entorno de test. Lo que
se prueba es el mecanismo: se lee lo que el proceso escribe, se le puede
escribir por stdin, y termina prolijo.
"""

from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp.agent_terminal import TIENE_PTY, TerminalSession  # noqa: E402

pytestmark = pytest.mark.skipif(not TIENE_PTY, reason="pty no disponible en esta plataforma")


def _leer_hasta(sesion: TerminalSession, esperado: bytes, timeout: float = 3.0) -> bytes:
    limite = time.time() + timeout
    acumulado = b""
    while time.time() < limite:
        acumulado += sesion.leer(4096)
        if esperado in acumulado:
            return acumulado
    raise AssertionError(f"no apareció {esperado!r} en la salida: {acumulado!r}")


def test_lee_lo_que_el_proceso_escribe():
    sesion = TerminalSession(["sh", "-c", "echo hola-terminal"])
    sesion.iniciar()
    try:
        salida = _leer_hasta(sesion, b"hola-terminal")
        assert b"hola-terminal" in salida
    finally:
        sesion.terminar()


def test_escribe_por_stdin_y_el_proceso_lo_recibe():
    sesion = TerminalSession(["sh", "-c", "read linea; echo recibido:$linea"])
    sesion.iniciar()
    try:
        # Sincroniza con que el `read` ya esté esperando, si no la escritura
        # puede llegar antes de que el shell abra stdin.
        time.sleep(0.2)
        sesion.escribir(b"marco\n")
        salida = _leer_hasta(sesion, b"recibido:marco")
        assert b"recibido:marco" in salida
    finally:
        sesion.terminar()


def test_vivo_pasa_a_false_cuando_el_proceso_termina():
    sesion = TerminalSession(["sh", "-c", "exit 0"])
    sesion.iniciar()
    try:
        limite = time.time() + 2.0
        while sesion.vivo and time.time() < limite:
            time.sleep(0.05)
        assert not sesion.vivo
        assert sesion.exit_code == 0
    finally:
        sesion.terminar()


def test_terminar_no_explota_si_ya_termino_solo():
    sesion = TerminalSession(["sh", "-c", "exit 0"])
    sesion.iniciar()
    time.sleep(0.2)
    sesion.terminar()  # no debería levantar nada


def test_resize_no_explota_sin_proceso_corriendo():
    sesion = TerminalSession(["sh", "-c", "exit 0"])
    sesion.iniciar()
    time.sleep(0.2)
    sesion.resize(24, 80)  # el proceso ya terminó; no debe levantar
    sesion.terminar()


# ── usar_pty=False: el modo sesión de Claude Code ────────────────────────


def test_sin_pty_tambien_lee_lo_que_el_proceso_escribe():
    sesion = TerminalSession(["sh", "-c", "echo linea-sin-pty"], usar_pty=False)
    sesion.iniciar()
    try:
        salida = _leer_hasta(sesion, b"linea-sin-pty")
        assert b"linea-sin-pty" in salida
    finally:
        sesion.terminar()


def test_sin_pty_escribe_por_stdin_sin_eco():
    """
    Sin pty no hay eco: lo único que vuelve es lo que el proceso imprime a
    propósito, nunca una copia de lo que se escribió — justo lo que hace
    falta para no ensuciar un parser de JSON por línea con lo que mandamos.
    """
    sesion = TerminalSession(["sh", "-c", "read linea; echo recibido:$linea"], usar_pty=False)
    sesion.iniciar()
    try:
        time.sleep(0.2)
        sesion.escribir(b"marco\n")
        salida = _leer_hasta(sesion, b"recibido:marco")
        assert salida.count(b"marco") == 1  # una sola vez: la del echo, no un eco de la entrada
    finally:
        sesion.terminar()
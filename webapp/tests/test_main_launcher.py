"""El lanzador `python -m webapp` bajo pythonw: sin consola, la salida va a webapp.log."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import __main__ as lanzador  # noqa: E402


def test_sin_consola_la_salida_va_a_un_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(lanzador, "_salida_actual", None)

    lanzador._asegurar_salida(tmp_path)
    print("hola desde pythonw", flush=True)
    assert "hola desde pythonw" in (tmp_path / "webapp.log").read_text(encoding="utf-8")

    # Cuando se conoce la raíz, el registro se mueve ahí.
    raiz = tmp_path / "instalacion"
    raiz.mkdir()
    lanzador._asegurar_salida(raiz)
    print("ya con raíz", flush=True)
    assert "ya con raíz" in (raiz / "webapp.log").read_text(encoding="utf-8")
    sys.stdout.close()


def test_con_consola_no_toca_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(lanzador, "_salida_actual", None)
    antes = sys.stdout
    lanzador._asegurar_salida(tmp_path)
    assert sys.stdout is antes
    assert not (tmp_path / "webapp.log").exists()


# ── Reiniciar tras actualizar: la raíz con espacios tiene que llegar entera ──

COMANDO = [sys.executable, "-m", "webapp", "--root", r"C:\Users\x\Desktop\Bot instalación QA", "--port", "8000", "--no-abrir"]


def test_en_windows_relanza_con_popen_y_la_lista_intacta(monkeypatch):
    """
    `os.execv` en Windows pega los argumentos sin comillas: una raíz con
    espacios llegaba partida y el hijo moría con "unrecognized arguments".
    Visto en el QA: la app no volvía después de Config → Actualizaciones.
    """
    import subprocess

    lanzados = []
    monkeypatch.setattr(lanzador.os, "name", "nt")
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: lanzados.append(cmd))
    monkeypatch.setattr(lanzador.os, "execv", lambda *a: pytest.fail("en Windows no se usa execv"))

    lanzador._relanzar(COMANDO)

    assert lanzados == [COMANDO]
    assert r"C:\Users\x\Desktop\Bot instalación QA" in lanzados[0]


def test_el_comando_de_reinicio_conserva_red_y_bandeja():
    """Un reinicio pedido desde la bandeja tiene que volver igual que se arrancó: en red sigue en red."""
    raiz = pathlib.Path(r"C:\Bot")
    assert lanzador.comando_relanzar(raiz, 8000, red=False) == [
        sys.executable, "-m", "webapp", "--root", r"C:\Bot", "--port", "8000", "--no-abrir",
    ]
    con_red = lanzador.comando_relanzar(raiz, 8010, red=True, sin_bandeja=True)
    assert con_red[-2:] == ["--red", "--sin-bandeja"]


def test_fuera_de_windows_reemplaza_el_proceso_con_execv(monkeypatch):
    llamadas = []
    monkeypatch.setattr(lanzador.os, "name", "posix")
    monkeypatch.setattr(lanzador.os, "execv", lambda exe, argv: llamadas.append((exe, argv)))

    lanzador._relanzar(COMANDO)

    assert llamadas == [(sys.executable, COMANDO)]

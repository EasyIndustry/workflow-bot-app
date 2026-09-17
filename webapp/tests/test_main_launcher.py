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


def test_el_comando_de_reinicio_conserva_red_y_bandeja(tmp_path, monkeypatch):
    """Un reinicio pedido desde la bandeja tiene que volver igual que se arrancó: en red sigue en red."""
    # Contra una copia y no contra el intérprete de verdad: `comando_relanzar`
    # usa `ejecutable_propio`, que deja un Bot.exe al lado del que corre, y no
    # hay por qué ensuciar el venv del repo por un test.
    interprete = tmp_path / "python.exe"
    interprete.write_bytes(b"x")
    monkeypatch.setattr(lanzador.sys, "executable", str(interprete))

    raiz = pathlib.Path(r"C:\Bot")
    assert lanzador.comando_relanzar(raiz, 8000, red=False) == [
        lanzador.ejecutable_propio(), "-m", "webapp", "--root", r"C:\Bot", "--port", "8000", "--no-abrir",
    ]
    con_red = lanzador.comando_relanzar(raiz, 8010, red=True, sin_bandeja=True)
    assert con_red[-2:] == ["--red", "--sin-bandeja"]


def test_fuera_de_windows_reemplaza_el_proceso_con_execv(monkeypatch):
    llamadas = []
    monkeypatch.setattr(lanzador.os, "name", "posix")
    monkeypatch.setattr(lanzador.os, "execv", lambda exe, argv: llamadas.append((exe, argv)))

    lanzador._relanzar(COMANDO)

    assert llamadas == [(sys.executable, COMANDO)]


# ── El puerto ocupado, y los procesos que quedaban vivos ────────────────


def test_un_servidor_escuchando_hace_que_el_puerto_no_este_libre():
    """
    El chequeo estaba hecho con un bind y SO_REUSEADDR, y en Windows eso no
    quiere decir "reusar lo que quedó en TIME_WAIT" sino "quedarse con la
    dirección aunque esté en uso": decía "libre" con un servidor escuchando.
    De ahí salían dos Bots en el mismo puerto, uno de ellos sin atender a
    nadie y sin forma de darse cuenta.
    """
    import socket

    with socket.socket() as servidor:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        puerto = servidor.getsockname()[1]

        assert lanzador._puerto_libre(puerto) is False


def test_un_puerto_sin_nadie_esta_libre():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    # Cerrado: puede quedar en TIME_WAIT, y eso NO es "ocupado" — era el falso
    # positivo que el SO_REUSEADDR venía a tapar.
    assert lanzador._puerto_libre(puerto) is True


def test_el_guardia_de_salida_es_daemon_y_no_demora_la_salida_limpia():
    """
    El hilo del ícono de la bandeja no es daemon: si `stop()` falla, el proceso
    queda vivo para siempre y sólo se cierra desde el administrador de tareas.
    El guardia lo baja igual; siendo daemon, cuando todo sale bien no retrasa
    nada.
    """
    guardia = lanzador._matar_el_proceso_si_no_sale(segundos=30)
    try:
        assert guardia.daemon is True
        assert guardia.is_alive()
    finally:
        guardia.cancel()


# ── Nombre propio en el administrador de tareas ────────────────────────


def test_el_relanzado_usa_un_ejecutable_con_nombre_buscable(tmp_path, monkeypatch):
    """
    En el administrador de tareas un proceso figura con el nombre de su
    ejecutable. Corriendo con el intérprete del runtime, el Bot aparecía como
    un `python.exe` más entre todos los de la máquina: cuando hay que cerrar
    uno a mano —que es de lo que se trata todo esto— no había con qué
    encontrarlo.
    """
    if __import__("os").name != "nt":
        pytest.skip("el nombre del ejecutable sólo cambia algo en Windows")

    falso = tmp_path / "pythonw.exe"
    falso.write_bytes(b"no soy un exe de verdad, pero se copia igual")
    monkeypatch.setattr(lanzador.sys, "executable", str(falso))

    comando = lanzador.comando_relanzar(tmp_path, 8000, red=False)

    assert comando[0].endswith(lanzador.NOMBRE_SIN_CONSOLA)
    assert (tmp_path / lanzador.NOMBRE_SIN_CONSOLA).is_file()


def test_con_consola_conserva_la_consola(tmp_path, monkeypatch):
    """Copiar el de ventana sobre el de consola abriría una ventana negra al reiniciar."""
    if __import__("os").name != "nt":
        pytest.skip("el nombre del ejecutable sólo cambia algo en Windows")

    falso = tmp_path / "python.exe"
    falso.write_bytes(b"consola")
    monkeypatch.setattr(lanzador.sys, "executable", str(falso))

    assert lanzador.ejecutable_propio().endswith(lanzador.NOMBRE_CON_CONSOLA)


def test_si_no_se_puede_copiar_se_sigue_con_el_de_siempre(tmp_path, monkeypatch):
    """Esto es comodidad para diagnosticar: no puede ser por qué el Bot no arranca."""
    if __import__("os").name != "nt":
        pytest.skip("el nombre del ejecutable sólo cambia algo en Windows")

    falso = tmp_path / "pythonw.exe"
    falso.write_bytes(b"x")
    monkeypatch.setattr(lanzador.sys, "executable", str(falso))
    import shutil

    def _explota(*_a, **_k):
        raise OSError("disco lleno")

    monkeypatch.setattr(shutil, "copy2", _explota)

    assert lanzador.ejecutable_propio() == str(falso)


def test_un_ejecutable_que_ya_se_llama_bot_no_se_vuelve_a_copiar(tmp_path, monkeypatch):
    if __import__("os").name != "nt":
        pytest.skip("el nombre del ejecutable sólo cambia algo en Windows")

    propio = tmp_path / lanzador.NOMBRE_SIN_CONSOLA
    propio.write_bytes(b"x")
    monkeypatch.setattr(lanzador.sys, "executable", str(propio))

    assert lanzador.ejecutable_propio() == str(propio)

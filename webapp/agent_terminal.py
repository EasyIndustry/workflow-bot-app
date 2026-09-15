"""
Un proceso interactivo servido por websocket — la terminal embebida del
wizard de la pestaña Agente.

Hace falta un pseudo-terminal de verdad —no un pipe simple— para que un CLI
que dibuja un prompt, colores, una barra de progreso, o que directamente es
una TUI (measura el ancho, pinta con secuencias ANSI, espera `isatty()`) se
comporte como en una terminal real. En POSIX eso sale de la stdlib (`pty`).
En Windows no hay nada en la stdlib —cae a pipes simples, que alcanzan para
un CLI que sólo imprime texto plano (instalar por npm, o el login clásico de
Claude Code)— así que ahí se usa `pywinpty`, que envuelve ConPTY.

Sin pty de ningún tipo, un CLI que es una TUI de verdad simplemente **no
imprime nada**: se queda esperando un terminal que nunca llega, en silencio,
indefinidamente — encontrado así, en vivo, con Antigravity CLI (`agy`): sobre
pipes simples en Windows no escribía un solo byte por varios segundos
(confirmado leyendo directo con `winpty` al lado: la misma corrida ahí sí
imprime las secuencias de setup de terminal de inmediato). Es la razón por la
que Codex y Antigravity "no abrían la terminal" pero Claude Code sí: el login
de Claude Code no es una TUI —imprime una URL y espera texto plano—, así que
toleraba pipes; los otros dos, sí son TUI.

Ningún argv llega desde el cliente del websocket: siempre sale de
`agent_providers.PROVEEDORES`, una tabla fija de este repo. Lo único que el
cliente elige es *cuál* de esos comandos ya declarados correr — no puede
inyectar uno propio.

`usar_pty=False` es para el modo sesión de Claude Code (`--output-format
stream-json`): ahí la salida es JSON por línea, y un pty la ensuciaría —
traduce fin de línea, puede eco-ar lo que se escribe, y algunas terminales
insertan retornos de carro que rompen un parser de JSON línea por línea. Un
pipe simple entrega los bytes tal cual salieron. Ese modo hoy sólo lo pide
Claude Code, y sigue cayendo a pipes en las tres plataformas.
"""

from __future__ import annotations

import os
import struct
import subprocess
from typing import Sequence

try:
    import fcntl
    import pty
    import termios

    TIENE_PTY_POSIX = True
except ImportError:  # Windows: sin pty en la stdlib.
    TIENE_PTY_POSIX = False

try:
    import winpty

    TIENE_PTY_WINDOWS = True
except ImportError:  # No instalado, o no estamos en Windows.
    TIENE_PTY_WINDOWS = False

# Nombre viejo, todavía importado desde otros módulos/tests: "hay pty POSIX
# de verdad", que es lo único que significaba antes de que existiera el
# backend de Windows.
TIENE_PTY = TIENE_PTY_POSIX


class TerminalSession:
    """Un proceso, de a un lector/escritor por vez. No es reentrante."""

    def __init__(
        self, argv: Sequence[str], *, cwd: str | None = None, env: dict[str, str] | None = None,
        usar_pty: bool = True,
    ) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        # Tres backends posibles, en este orden de preferencia. Sin ninguno
        # disponible (pty no pedido, o ninguna de las dos libs está), cae a
        # pipes simples — no es un error, es la única opción que queda.
        if usar_pty and TIENE_PTY_POSIX:
            self._backend = "posix"
        elif usar_pty and TIENE_PTY_WINDOWS:
            self._backend = "winpty"
        else:
            self._backend = "pipes"
        self._proc: subprocess.Popen | None = None
        self._master_fd: int | None = None  # sólo con backend "posix"
        self._winpty: "winpty.PtyProcess | None" = None  # sólo con backend "winpty"

    def iniciar(self) -> None:
        entorno = {**os.environ, **(self.env or {})}
        if self._backend == "posix":
            master, esclavo = pty.openpty()
            try:
                self._proc = subprocess.Popen(
                    self.argv, cwd=self.cwd, env=entorno,
                    stdin=esclavo, stdout=esclavo, stderr=esclavo,
                    start_new_session=True,
                )
            finally:
                # El extremo esclavo es del proceso hijo; este lado no lo
                # necesita, y dejarlo abierto acá le impediría a `os.read`
                # enterarse de un EOF cuando el hijo termina.
                os.close(esclavo)
            self._master_fd = master
        elif self._backend == "winpty":
            # `winpty.PtyProcess.spawn` resuelve el shim `.CMD`/`.BAT` de un
            # CLI de Node por su cuenta (usa CreateProcess con ConPTY detrás,
            # no cmd.exe) — a diferencia del branch de pipes de más abajo, acá
            # no hace falta `shell=True` ni el rodeo de `taskkill /T` en
            # `terminar()`: el proceso que arranca es el real, sin un cmd.exe
            # intermedio que dejar huérfano.
            self._winpty = winpty.PtyProcess.spawn(self.argv, cwd=self.cwd, env=entorno)
        else:
            self._proc = subprocess.Popen(
                self.argv, cwd=self.cwd, env=entorno,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # En Windows, `npm install -g` deja un shim `.CMD`/`.BAT`, no un
                # .exe — CreateProcess sólo sabe correr un .exe directo, así que
                # sin shell=True esto explota con WinError 2 apenas el binario es
                # `claude`, `npm` o cualquier otro CLI de Node. cmd.exe sí sabe
                # resolver la extensión via PATHEXT. En POSIX este branch sólo se
                # usa para `usar_pty=False` (el modo sesión); ahí no hace falta
                # shell y mejor evitarlo, así el argv llega tal cual sin pasar
                # por un parser de shell.
                shell=(os.name == "nt"),
            )

    def leer(self, n: int = 4096) -> bytes:
        """Bloquea hasta que haya datos, EOF (`b""`), o el fd se cierre."""
        if self._backend == "posix":
            try:
                return os.read(self._master_fd, n)
            except OSError:
                return b""
        if self._backend == "winpty":
            assert self._winpty is not None
            try:
                # `PtyProcess.read` devuelve `str` (decodifica UTF-8 del lado
                # de la lib, reintentando si corta un carácter multibyte a la
                # mitad) — se re-codifica acá para que el resto de esta clase,
                # y quien la usa (`core_api.py` manda `websocket.send_bytes`),
                # siga viendo siempre bytes sin importar el backend.
                return self._winpty.read(n).encode("utf-8", errors="replace")
            except EOFError:
                return b""
        assert self._proc is not None and self._proc.stdout is not None
        return self._proc.stdout.read1(n)

    def escribir(self, datos: bytes) -> None:
        if not datos:
            return
        if self._backend == "posix":
            try:
                os.write(self._master_fd, datos)
            except OSError:
                pass
            return
        if self._backend == "winpty":
            if self._winpty is None:
                return
            try:
                self._winpty.write(datos.decode("utf-8", errors="replace"))
            except EOFError:
                pass
            return
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(datos)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def resize(self, filas: int, columnas: int) -> None:
        """Sin esto, un proceso que mide el ancho de la terminal dibuja mal."""
        if self._backend == "posix" and self._master_fd is not None:
            tamano = struct.pack("HHHH", filas, columnas, 0, 0)
            try:
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, tamano)
            except OSError:
                pass
        elif self._backend == "winpty" and self._winpty is not None:
            try:
                self._winpty.setwinsize(filas, columnas)
            except (OSError, ValueError):
                pass

    @property
    def vivo(self) -> bool:
        if self._backend == "winpty":
            return self._winpty is not None and self._winpty.isalive()
        return self._proc is not None and self._proc.poll() is None

    @property
    def exit_code(self) -> int | None:
        if self._backend == "winpty":
            if self._winpty is None or self._winpty.isalive():
                return None
            return self._winpty.exitstatus
        return None if self._proc is None else self._proc.poll()

    def terminar(self) -> None:
        if self._backend == "winpty":
            if self._winpty is not None and self._winpty.isalive():
                self._winpty.terminate(force=True)
            return
        if self._proc is not None and self._proc.poll() is None:
            if os.name == "nt" and self._backend == "pipes":
                # En Windows, `iniciar()` corrió esto con `shell=True` —hace
                # falta para resolver el shim `.CMD` de un CLI de Node, ver
                # ahí—, así que el hijo directo de este proceso es `cmd.exe`,
                # no `claude`/`node`. `Popen.terminate()` sólo mata ese padre
                # inmediato: el nieto queda huérfano y sigue vivo para
                # siempre. Encontrado así, en vivo: después de usar el chat un
                # rato, docenas de `claude.exe` zombies corriendo, cada uno
                # todavía conectado a la API — hasta que se agotaron y las
                # sesiones nuevas dejaron de recibir respuesta.
                # `taskkill /T` mata el árbol entero por PID, no sólo el que
                # Python conoce.
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except OSError:
                    pass
            else:
                try:
                    self._proc.terminate()
                except ProcessLookupError:
                    pass
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None


__all__ = ["TIENE_PTY", "TIENE_PTY_POSIX", "TIENE_PTY_WINDOWS", "TerminalSession"]

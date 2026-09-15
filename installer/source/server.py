"""
El servidor del instalador: `http.server` de la stdlib y nada más.

Por qué un navegador y no una ventana nativa
--------------------------------------------

Es lo único que corre igual en Linux y en Windows sin agregar una dependencia.
Tkinter no siempre viene con el Python del sistema en Linux, y Qt pesa más que
toda la app junta. Además el front del wizard usa los mismos tokens de diseño
que `webapp/`, así que lo que se escribe acá no se tira después.

Escucha sólo en 127.0.0.1: es un instalador local, no un servicio.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# El instalador corre desde el repo, así que el paquete `backend` tiene que
# estar en el path. Tres niveles: source/ -> installer/ -> la raíz.
RAIZ_REPO = Path(__file__).resolve().parents[2]
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from . import pasos  # noqa: E402

ESTATICOS = Path(__file__).resolve().parent / "static"

PUERTO_PREFERIDO = 8777

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    """Estáticos y seis endpoints JSON. Nada más."""

    server_version = "BotInstaller"

    def do_GET(self) -> None:
        ruta = self.path.split("?")[0]

        if ruta == "/api/sugerencia":
            return self._json(pasos.sugerencia())
        if ruta.startswith("/api/"):
            return self._json({"error": "no existe"}, 404)

        return self._estatico("index.html" if ruta == "/" else ruta.lstrip("/"))

    def do_POST(self) -> None:
        ruta = self.path.split("?")[0]
        try:
            cuerpo = self._cuerpo()
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

        destino = str(cuerpo.get("ruta", ""))

        if ruta == "/api/revisar":
            return self._json(pasos.revisar_destino(destino))
        if ruta == "/api/maquina":
            return self._json({"chequeos": pasos.revisar_maquina(destino)})
        if ruta == "/api/plan":
            return self._json(pasos.plan(destino))
        if ruta == "/api/instalar":
            try:
                return self._json(pasos.instalar(destino))
            except pasos.InstalacionError as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                # Un instalador que muere en silencio deja media instalación y
                # ninguna explicación. Cualquier fallo vuelve como texto.
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        if ruta == "/api/abrir":
            # La app en su propio puerto, distinto del instalador. Se elige acá
            # y se le pasa a la app: es la única forma de saber a qué URL mandar
            # al navegador antes de que levante.
            try:
                puerto = _puerto_libre(8000)
                return self._json(pasos.abrir_webapp(destino, puerto))
            except pasos.InstalacionError as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        if ruta == "/api/salir":
            threading.Timer(0.5, self.server.shutdown).start()
            return self._json({"ok": True})

        return self._json({"error": "no existe"}, 404)

    # ── Plomería ────────────────────────────────────────────────────────

    def _cuerpo(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        crudo = self.rfile.read(largo).decode("utf-8")
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise ValueError(f"cuerpo inválido: {exc}") from exc
        if not isinstance(datos, dict):
            raise ValueError("el cuerpo tiene que ser un objeto")
        return datos

    def _json(self, datos: dict, codigo: int = 200) -> None:
        crudo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def _estatico(self, nombre: str) -> None:
        destino = (ESTATICOS / nombre).resolve()
        # Un instalador que sirve archivos por nombre tiene que acotarse a su
        # propia carpeta: `../` no puede salir de `static/`.
        if not destino.is_file() or ESTATICOS not in destino.parents:
            self.send_error(404)
            return
        crudo = destino.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(destino.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(crudo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(crudo)

    def log_message(self, formato: str, *args) -> None:
        """Silencio. La consola del instalador es para el cliente, no para el log."""


def _puerto_libre(preferido: int = PUERTO_PREFERIDO) -> int:
    """El preferido si está libre; si no, cualquiera que el sistema dé."""
    for candidato in (preferido, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", candidato))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no hay ningún puerto libre en 127.0.0.1")


def main(abrir: bool = True) -> int:
    puerto = _puerto_libre()
    url = f"http://127.0.0.1:{puerto}/"
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)

    # `flush`: con la salida redirigida (un .bat, un doble clic) el buffer se
    # queda con el mensaje, y el cliente ve una consola vacía.
    print(f"Instalador de Bot en {url}", flush=True)
    print("Cerrá esta ventana cuando termines.\n", flush=True)
    if abrir:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCancelado.")
    finally:
        servidor.server_close()
    return 0


__all__ = ["Handler", "main"]

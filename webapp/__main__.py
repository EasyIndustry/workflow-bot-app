"""
Arrancar la webapp.

    python -m webapp                       la última instalación que anotó el wizard
    python -m webapp --root /ruta/Bot      una instalación puntual
    python -m webapp --port 8010 --no-abrir

Es lo que lanza el acceso directo "Abrir Bot" y lo que el wizard ejecuta al
terminar. La raíz se resuelve en `webapp/ubicacion.py`; acá sólo se la pasa al
servidor por el entorno, que es el único canal que existe antes de importar el
módulo (la instancia se construye al importar `routes.core_api`).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import webbrowser
from pathlib import Path
from threading import Timer

PROGRAMA = Path(__file__).resolve().parent.parent
if str(PROGRAMA) not in sys.path:
    sys.path.insert(0, str(PROGRAMA))

from webapp import ubicacion  # noqa: E402

PUERTO_POR_DEFECTO = 8000


def _puerto_libre(puerto: int) -> bool:
    with socket.socket() as s:
        # SO_REUSEADDR, igual que uvicorn: un socket en TIME_WAIT del proceso
        # que acaba de terminar no cuenta como "en uso".
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


def _esperar_puerto_libre(puerto: int, segundos: float = 8.0) -> bool:
    """
    Al reiniciar, este proceso arranca mientras el anterior todavía está
    soltando el socket: un chequeo instantáneo decía "puerto en uso" y la app
    no volvía. Se le da un rato antes de rendirse.
    """
    limite = time.monotonic() + segundos
    while True:
        if _puerto_libre(puerto):
            return True
        if time.monotonic() >= limite:
            return False
        time.sleep(0.25)


_salida_actual: Path | None = None


def _asegurar_salida(carpeta: Path) -> None:
    """
    Si no hay consola, stdout y stderr van a `<carpeta>/webapp.log`. Con
    consola no hace nada: lo que se ve en pantalla sigue en pantalla.
    """
    global _salida_actual
    sin_consola = sys.stdout is None or sys.stderr is None or _salida_actual is not None
    if not sin_consola:
        return
    destino = carpeta / "webapp.log"
    if destino == _salida_actual:
        return
    try:
        archivo = open(destino, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — vive lo que el proceso
    except OSError:
        return
    sys.stdout = archivo
    sys.stderr = archivo
    _salida_actual = destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp", description="Arranca la webapp de Bot.")
    # Con pythonw.exe (el acceso directo "Abrir Bot" en Windows) no hay consola:
    # sys.stdout y sys.stderr son None y el primer print revienta. Todo lo que
    # se imprima va a un archivo al lado de la instalación, que además es lo
    # que hay que mirar si la app no levanta.
    _asegurar_salida(PROGRAMA)

    parser.add_argument("--root", help="La carpeta de la instalación (boot.env, data/, workspace/).")
    parser.add_argument("--port", type=int, default=PUERTO_POR_DEFECTO)
    parser.add_argument("--no-abrir", action="store_true", help="No abrir el navegador.")
    parser.add_argument(
        "--red", action="store_true",
        help="Escuchar en todas las interfaces, para operar Bot desde otra PC de la red local. "
        "Sin esto, sólo desde esta máquina (127.0.0.1).",
    )
    parser.add_argument("--sin-bandeja", action="store_true", help="No poner el ícono en la bandeja del sistema.")
    parser.add_argument(
        "--revertir-nucleo", action="store_true",
        help="Vuelve al backend/ anterior a la última actualización y sale. Para cuando la app no levanta.",
    )
    parser.add_argument(
        "--revertir-webapp", action="store_true",
        help="Vuelve al webapp/ anterior a la última actualización y sale. Si ni esto arranca, "
        "renombrar a mano webapp/ ↔ webapp.anterior/ en la carpeta del programa.",
    )
    args = parser.parse_args(argv)

    if args.revertir_nucleo or args.revertir_webapp:
        from webapp import updates

        comp = updates.WEBAPP if args.revertir_webapp else updates.CORE
        try:
            estado = updates.revertir(PROGRAMA, comp)
        except updates.UpdateError as exc:
            print(str(exc), file=sys.stderr)
            return 4
        print(f"{comp.label.capitalize()} revertido. Ahora corre: {estado['tag'] or 'el anterior al actualizador'}.")
        return 0

    raiz = ubicacion.resolver_root(PROGRAMA, args.root)
    if not raiz.is_dir():
        print(f"No existe la carpeta de instalación {raiz}.", file=sys.stderr)
        return 2
    if not _esperar_puerto_libre(args.port):
        print(
            f"El puerto {args.port} ya está en uso. ¿Bot ya está abierto? "
            f"Si no, probar con --port otro.", file=sys.stderr,
        )
        return 3

    os.environ["BOT_ROOT"] = str(raiz)
    os.environ["BOT_PORT"] = str(args.port)
    # Ahora que se sabe la raíz, el registro va ahí (el mismo webapp.log que
    # escribe el wizard al lanzar la app), no en la carpeta del programa.
    _asegurar_salida(raiz)

    import uvicorn

    # `core_router` y no `webapp.routes.core_api`: server.py importa las rutas
    # como `routes.core_api` (con webapp/ en sys.path), así que importarlas
    # acá por el otro nombre daría un segundo módulo, con otra instancia, y el
    # reinicio quedaría colgado en la copia que nadie usa.
    from webapp.server import app, core_router

    url = f"http://127.0.0.1:{args.port}"
    host = "0.0.0.0" if args.red else "127.0.0.1"  # noqa: S104 — --red es pedir justamente eso
    print(f"Bot en {url} · instalación: {raiz}" + (" · accesible desde la red local" if args.red else ""), flush=True)
    if not args.no_abrir:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    # Sin --reload: el launcher supervisa el proceso, y el reloader deja
    # huérfano al hijo cuando se lo mata desde afuera. `Server` en vez de
    # `uvicorn.run` para tener el objeto: reiniciar es pedirle que termine y
    # volver a ejecutar este mismo comando —el núcleo nuevo se importa de cero.
    servidor = uvicorn.Server(uvicorn.Config(app, host=host, port=args.port, log_level="info"))
    pedido_reinicio = {"si": False, "red": args.red}

    # Al pedir salir, uvicorn espera a que cada conexión abierta termine; una
    # vez —justo después de aplicar una actualización de la web app— se quedó
    # en "Shutting down" para siempre, con la app caída y sin relanzarse. Acá
    # no hay nada que valga esa espera: reiniciar y cerrar pasan por el gate
    # exclusivo, así que ningún run está a mitad de camino, y una request
    # cortada se reintenta desde el navegador. Se le dan unos segundos al
    # cierre prolijo y después `force_exit`. No directamente `force_exit`
    # porque ése saltea el lifespan y starlette deja un traceback de
    # CancelledError en el registro en cada reinicio normal.
    def _forzar_si_no_salio() -> None:
        servidor.force_exit = True

    def _pedir_salida() -> None:
        servidor.should_exit = True
        guardia = Timer(8.0, _forzar_si_no_salio)
        guardia.daemon = True
        guardia.start()

    def reiniciar() -> None:
        pedido_reinicio["si"] = True
        _pedir_salida()

    def cerrar() -> None:
        _pedir_salida()

    def habilitar_red() -> None:
        pedido_reinicio["red"] = True
        reiniciar()

    core_router._reiniciar = reiniciar

    # El ícono de la bandeja: abrir, copiar la dirección, ver el registro,
    # reiniciar y cerrar sin una consola. Ver webapp/bandeja.py. Si no hay con
    # qué (sin pystray, sin escritorio), el servidor corre igual.
    icono = None
    if not args.sin_bandeja:
        from webapp import bandeja

        icono = bandeja.iniciar(
            bandeja.Estado(url=url, puerto=args.port, raiz=raiz, en_red=args.red, version=_version()),
            bandeja.Acciones(reiniciar=reiniciar, cerrar=cerrar, habilitar_red=None if args.red else habilitar_red),
        )
        if icono is None:
            print("Sin ícono en la bandeja (falta pystray/Pillow o no hay escritorio).", flush=True)

    try:
        servidor.run()
    finally:
        if icono is not None:
            try:
                icono.stop()
            except Exception:  # noqa: BLE001 — cerrar el ícono no puede impedir salir
                pass

    if pedido_reinicio["si"]:
        print("Reiniciando…", flush=True)
        _relanzar(comando_relanzar(raiz, args.port, red=pedido_reinicio["red"], sin_bandeja=args.sin_bandeja))
    return 0


def comando_relanzar(raiz: Path, puerto: int, *, red: bool, sin_bandeja: bool = False) -> list[str]:
    """El mismo comando con el que se arrancó, sin abrir otra pestaña. Separado para probarlo."""
    comando = [sys.executable, "-m", "webapp", "--root", str(raiz), "--port", str(puerto), "--no-abrir"]
    if red:
        comando.append("--red")
    if sin_bandeja:
        comando.append("--sin-bandeja")
    return comando


def _version() -> str:
    """
    La versión del programa para el título del ícono: la de la web app
    (`webapp-release.json`, que deja el instalador o una actualización) y, si
    no la hay, el tag del núcleo.
    """
    import json

    for marca in ("webapp-release.json", "core-release.json"):
        try:
            tag = json.loads((PROGRAMA / marca).read_text(encoding="utf-8")).get("tag")
        except (OSError, ValueError):
            continue
        if tag:
            return str(tag)
    return ""


def _relanzar(comando: list[str]) -> None:
    """
    Vuelve a ejecutar este mismo comando con el núcleo nuevo ya en disco.

    En Linux, `execv` reemplaza el proceso: mismo pid, y quien lo lanzó no nota
    nada. En Windows `execv` no existe de verdad: CPython arranca un proceso
    nuevo pegando los argumentos con espacios y **sin comillas**, así que una
    raíz con espacios (`C:\\Users\\...\\Bot instalación QA`) llega partida y el
    hijo muere con "unrecognized arguments" antes de escuchar. Se vio en el QA
    de Windows: la app no volvía tras actualizar, y el único rastro quedaba en
    el webapp.log de la carpeta del programa. `Popen` con la lista arma la
    línea de comando con las comillas que hacen falta.
    """
    if os.name == "nt":
        import subprocess

        subprocess.Popen(comando, close_fds=True)
        return
    os.execv(sys.executable, comando)


if __name__ == "__main__":
    sys.exit(main())

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
    """
    ¿Hay algo escuchando en este puerto?

    Se pregunta con un `connect` y no con un `bind`. El bind con SO_REUSEADDR
    —que es como estaba— **miente en Windows**: ahí SO_REUSEADDR no quiere
    decir "reusar la dirección que quedó en TIME_WAIT" como en POSIX, quiere
    decir "quedarse con ella aunque esté en uso". Comprobado en la máquina de
    QA: con un servidor escuchando en `127.0.0.1:8099`, el bind seguía
    diciendo que el puerto estaba libre.

    Lo que salía de ahí son dos Bots en el mismo puerto: el segundo arrancaba
    creyendo que estaba solo, Windows le entregaba las conexiones a uno de los
    dos, y el otro quedaba vivo sin atender a nadie y sin forma de darse
    cuenta. Se encontraron dos así, de un día para el otro, en la instalación
    de QA.

    Un `connect` no tiene esa ambigüedad: si algo acepta la conexión, hay un
    servidor. Y de paso resuelve lo que el SO_REUSEADDR venía a tapar, porque
    un socket en TIME_WAIT no acepta conexiones: no es un falso positivo.
    """
    with socket.socket() as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex(("127.0.0.1", puerto)) != 0
        except OSError:
            return True


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


# Los nombres con los que el Bot tiene que figurar en el administrador de
# tareas. Son copias del intérprete del runtime: `Bot.exe` la que corre sin
# consola (la de la bandeja y el acceso directo) y `BotConsola.exe` la otra.
NOMBRE_SIN_CONSOLA = "Bot.exe"
NOMBRE_CON_CONSOLA = "BotConsola.exe"


def ejecutable_propio() -> str:
    """
    El intérprete con el que relanzarse, con un nombre que se pueda buscar.

    En el administrador de tareas un proceso figura con el nombre de su
    archivo ejecutable, y como el Bot corre con el intérprete del runtime,
    figuraba como `python.exe` / `pythonw.exe` — entre todos los demás
    `python.exe` de la máquina, sin forma de saber cuál es. Cuando algo falla
    y hay que cerrar uno a mano, eso es lo primero que se necesita y lo único
    que no había.

    La copia se hace acá y no sólo en el build porque una instalación que ya
    existe se actualiza cambiando `webapp/`, no el runtime: si dependiera del
    instalador, las máquinas de hoy nunca lo tendrían. Windows toma el nombre
    del archivo, así que una copia alcanza; el intérprete encuentra su casa
    por la carpeta, que es la misma.

    Ante cualquier problema (permisos, disco, otro sistema operativo) se
    devuelve `sys.executable`: esto es comodidad para diagnosticar, y no puede
    ser la razón por la que el Bot no arranque.
    """
    actual = Path(sys.executable)
    if os.name != "nt" or actual.stem.startswith("Bot"):
        return sys.executable

    # `pythonw.exe` no abre consola; `python.exe` sí. Se conserva cuál es,
    # porque de eso depende que no aparezca una ventana negra al reiniciar.
    nombre = NOMBRE_CON_CONSOLA if actual.name.lower() == "python.exe" else NOMBRE_SIN_CONSOLA
    destino = actual.with_name(nombre)
    try:
        if not destino.is_file() or destino.stat().st_mtime < actual.stat().st_mtime:
            import shutil

            shutil.copy2(actual, destino)
        return str(destino)
    except OSError as exc:
        print(f"No se pudo dejar el ejecutable como {nombre}: {exc}", file=sys.stderr, flush=True)
        return sys.executable


def _raiz_del_bot_en(url: str) -> Path | None:
    """
    ¿Lo que está escuchando ahí es un Bot, y de qué instalación?

    Cambia qué hacer: si es el Bot de **esta** instalación, abrir la pantalla
    es exactamente lo que quien hizo doble clic esperaba; si es otro Bot u
    otro programa, hay que arrancar en otro puerto. Se pregunta por una ruta
    de la API y no por la página, que la podría estar sirviendo cualquier
    cosa. `None` si no es un Bot o no contesta.
    """
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/api/core/overview", timeout=2.5) as r:
            raiz = json.load(r).get("root")
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return Path(raiz) if isinstance(raiz, str) and raiz else None


def _misma_instalacion(a: Path, b: Path) -> bool:
    """Las dos rutas son la misma carpeta, aunque difieran en mayúsculas o en `..`."""
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


# Hasta dónde se busca un puerto libre a partir del que estaba ocupado. Cincuenta
# alcanza para cualquier cantidad razonable de Bots y programas en una PC, y
# preguntar por cada uno cuesta un connect rechazado al instante.
PUERTOS_A_PROBAR = 50


def _siguiente_puerto_libre(desde: int, cuantos: int = PUERTOS_A_PROBAR) -> int | None:
    """El primer puerto libre desde `desde` inclusive, o `None` si no hay en el rango."""
    for puerto in range(desde, min(desde + cuantos, 65536)):
        if _puerto_libre(puerto):
            return puerto
    return None


def _decidir_puerto(pedido: int | None, raiz: Path) -> tuple[str, int, str]:
    """
    En qué puerto arrancar, o qué hacer si no se puede.

    Devuelve `(accion, puerto, mensaje)`, con `accion` una de:
      - "arrancar": levantar el servidor en `puerto`.
      - "abrir": el Bot de esta instalación ya está en `puerto`; abrir la
        pantalla y salir. Es el caso normal del doble clic repetido en el
        acceso directo, no un error.
      - "fallar": no hay dónde; `mensaje` es lo que hay que mostrar.

    Sin `--port`, el puerto ocupado no frena: se busca el siguiente libre.
    Antes, con otro programa en el 8000, salía un cartel pidiendo cerrarlo o
    elegir puerto a mano; y con **otro Bot** ahí —otra instalación de la misma
    PC, el repo de desarrollo— se abría la pantalla de ese otro, que es peor:
    parece que abrió el que uno quería y es el de al lado, con sus datos, y
    después no se sabe cuál cerrar. Por eso la raíz se compara: sólo el Bot de
    esta misma carpeta cuenta como "ya abierto".

    Con `--port` explícito se respeta: quien lo escribió eligió ese puerto (el
    wizard, que ya buscó uno libre; el reinicio, que tiene que volver donde
    está el navegador; alguien desde una consola). Ahí un puerto ocupado por
    otra cosa sigue siendo un error que se avisa.
    """
    puerto = pedido if pedido is not None else PUERTO_POR_DEFECTO
    if _esperar_puerto_libre(puerto):
        return "arrancar", puerto, ""

    url = f"http://127.0.0.1:{puerto}"
    raiz_ahi = _raiz_del_bot_en(url)
    if raiz_ahi is not None and _misma_instalacion(raiz_ahi, raiz):
        return "abrir", puerto, f"Bot ya está abierto en {url}; se abre la pantalla."

    ocupante = f"otro Bot ({raiz_ahi})" if raiz_ahi is not None else "otro programa"
    if pedido is not None:
        return "fallar", puerto, (
            f"El puerto {puerto} está ocupado por {ocupante}, así que Bot no puede abrir ahí.\n\n"
            f"Cerrá ese programa, o abrí Bot en otro puerto con --port."
        )

    libre = _siguiente_puerto_libre(puerto + 1)
    if libre is None:
        return "fallar", puerto, (
            f"El puerto {puerto} está ocupado por {ocupante} y no se encontró ninguno libre "
            f"hasta el {puerto + PUERTOS_A_PROBAR}."
        )
    return "arrancar", libre, f"El puerto {puerto} está ocupado por {ocupante}; Bot abre en el {libre}."


def _avisar(mensaje: str) -> None:
    """
    Un error que quien abrió el programa tiene que ver.

    Con consola alcanza con imprimirlo. Sin consola —el acceso directo y el
    wizard lanzan con `pythonw`— no hay dónde: el texto termina en un archivo
    de registro que nadie mira, y desde afuera se ve como que Bot "no abre" y
    no dice nada. En Windows eso es un cartel del sistema, sin dependencias.
    """
    print(mensaje, file=sys.stderr, flush=True)
    if os.name != "nt" or sys.stderr is not None and sys.stderr.isatty():
        return
    try:
        import ctypes

        # MB_ICONWARNING | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, mensaje, "Bot", 0x30 | 0x10000)
    except Exception:  # noqa: BLE001 — sin cartel se sigue: el registro ya lo tiene
        pass


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
    parser.add_argument(
        "--port", type=int, default=None,
        help=f"Puerto fijo. Sin esto, el {PUERTO_POR_DEFECTO} y, si está ocupado, el siguiente libre.",
    )
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
        "renombrar a mano webapp/ y webapp.anterior/ (una por otra) en la carpeta del programa.",
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
    # Ver `_decidir_puerto`. "Ya abierto" no es un error: alguien hizo doble
    # clic en el acceso directo y lo que quiere es la pantalla. Antes salía con
    # código 3 y, como el acceso directo usa `pythonw` —sin consola—, no
    # aparecía nada: el mensaje terminaba en el webapp.log de la carpeta del
    # programa, que nadie mira. En la QA se juntaron cinco intentos así, todos
    # en silencio, con el usuario clickeando el acceso directo sin respuesta.
    accion, puerto, mensaje = _decidir_puerto(args.port, raiz)
    if accion == "abrir":
        print(mensaje, flush=True)
        if not args.no_abrir:
            webbrowser.open(f"http://127.0.0.1:{puerto}")
        return 0
    if accion == "fallar":
        _avisar(mensaje)
        return 3
    if mensaje:
        print(mensaje, flush=True)

    os.environ["BOT_ROOT"] = str(raiz)
    os.environ["BOT_PORT"] = str(puerto)
    # Ahora que se sabe la raíz, el registro va ahí (el mismo webapp.log que
    # escribe el wizard al lanzar la app), no en la carpeta del programa.
    _asegurar_salida(raiz)

    import uvicorn

    # `core_router` y no `webapp.routes.core_api`: server.py importa las rutas
    # como `routes.core_api` (con webapp/ en sys.path), así que importarlas
    # acá por el otro nombre daría un segundo módulo, con otra instancia, y el
    # reinicio quedaría colgado en la copia que nadie usa.
    from webapp.server import app, core_router

    url = f"http://127.0.0.1:{puerto}"
    host = "0.0.0.0" if args.red else "127.0.0.1"  # noqa: S104 — --red es pedir justamente eso
    print(f"Bot en {url} · instalación: {raiz}" + (" · accesible desde la red local" if args.red else ""), flush=True)
    if not args.no_abrir:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    # Sin --reload: el launcher supervisa el proceso, y el reloader deja
    # huérfano al hijo cuando se lo mata desde afuera. `Server` en vez de
    # `uvicorn.run` para tener el objeto: reiniciar es pedirle que termine y
    # volver a ejecutar este mismo comando —el núcleo nuevo se importa de cero.
    servidor = uvicorn.Server(uvicorn.Config(app, host=host, port=puerto, log_level="info"))
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
            bandeja.Estado(url=url, puerto=puerto, raiz=raiz, en_red=args.red, version=_version()),
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
            # El hilo que pystray levanta con `run_detached` **no es daemon**:
            # mientras siga vivo, el proceso no sale aunque `main` haya
            # terminado. Y el `except` de arriba se traga cualquier error de
            # `stop()`, así que una falla ahí dejaba un Bot sin servidor,
            # invisible, imposible de cerrar desde la bandeja —porque el menú
            # que lo cerraría es el de ese mismo ícono— y que sólo se iba con
            # el administrador de tareas. Es de donde salen los Bots que no se
            # pueden cerrar.
            _matar_el_proceso_si_no_sale()

    if pedido_reinicio["si"]:
        print("Reiniciando…", flush=True)
        _relanzar(comando_relanzar(raiz, puerto, red=pedido_reinicio["red"], sin_bandeja=args.sin_bandeja))
    return 0


# Cuánto se espera a que los hilos que quedan terminen solos antes de bajar el
# proceso por la fuerza. Generoso: lo normal es salir mucho antes.
GRACIA_AL_SALIR = 6.0


def _matar_el_proceso_si_no_sale(segundos: float = GRACIA_AL_SALIR) -> Timer:
    """
    La garantía de que "Cerrar" cierra.

    Un temporizador daemon que baja el proceso si sigue vivo pasado ese rato.
    Si todo salió bien, el proceso ya terminó y esto no llega a correr nunca:
    es daemon, así que no retrasa la salida limpia ni un milisegundo.

    `os._exit` y no `sys.exit`: lo que hay que cortar es justamente un hilo que
    no se muere, y `sys.exit` en un temporizador sólo termina ese hilo. Para
    cuando esto corre ya se cerró el servidor y se soltó la base; lo que queda
    es un hilo de interfaz colgado.
    """
    def _bajar() -> None:
        print("Los hilos de la interfaz no terminaron; se cierra igual.", file=sys.stderr, flush=True)
        os._exit(0)

    guardia = Timer(segundos, _bajar)
    guardia.daemon = True
    guardia.start()
    return guardia


def comando_relanzar(raiz: Path, puerto: int, *, red: bool, sin_bandeja: bool = False) -> list[str]:
    """El mismo comando con el que se arrancó, sin abrir otra pestaña. Separado para probarlo."""
    comando = [ejecutable_propio(), "-m", "webapp", "--root", str(raiz), "--port", str(puerto), "--no-abrir"]
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

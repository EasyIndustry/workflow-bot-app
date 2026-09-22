"""
El ícono de Bot en la bandeja del sistema (al lado del reloj).

"Abrir Bot" levanta el servidor con `pythonw`, sin consola: no hay nada que
ver ni dónde cerrarlo salvo el Administrador de tareas. Con el ícono, quien
opera tiene lo que necesita sin una terminal: abrir la app en el navegador,
copiar la dirección para entrar desde otra PC de la red, ver el registro,
reiniciar y cerrar. Todo con click derecho.

Es opcional a propósito: `pystray` y `Pillow` viajan en el runtime del
instalador, pero si no están —un venv de desarrollo pelado, un Linux sin
bandeja— el servidor arranca igual y lo dice en el registro. Nada del
servidor depende de esto.

La lógica que se puede probar sin una bandeja de verdad (qué opciones hay,
qué dirección se copia) está separada de `pystray`, que sólo aparece en
`iniciar`.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Estado:
    url: str                      # http://127.0.0.1:8000
    puerto: int
    raiz: Path                    # la instalación (ahí vive webapp.log)
    en_red: bool                  # ¿escucha en todas las interfaces?
    version: str = ""


@dataclass
class Acciones:
    reiniciar: Callable[[], None]
    cerrar: Callable[[], None]
    habilitar_red: Callable[[], None] | None = None
    abrir: Callable[[str], None] = field(default=lambda url: webbrowser.open(url))
    # Cómo decirle algo a quien hizo clic. Con bandeja es un globo al lado del
    # reloj (`iniciar` lo enchufa); sin bandeja, el registro. Existe porque
    # "copiar la dirección" no tiene otra forma de mostrarse: si fallaba, no
    # pasaba nada visible y el portapapeles quedaba con lo que tuviera antes
    # —una dirección vieja, un 127.0.0.1— y eso se leía como que copió mal.
    notificar: Callable[[str], None] = field(default=lambda mensaje: print(mensaje, file=sys.stderr, flush=True))


SEPARADOR = None


def disponible() -> bool:
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


# ── Dirección en la red ─────────────────────────────────────────────────


def _es_util(ip: str) -> bool:
    """Una IP que otra PC podría usar: ni loopback ni la que Windows se inventa sin DHCP (169.254.x)."""
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.") and ip != "0.0.0.0"  # noqa: S104


def _ip_de_salida_hacia(destino: str) -> str | None:
    """
    El truco del UDP sin enviar: `connect` sobre un socket UDP no manda nada,
    sólo hace que el sistema elija la interfaz de salida hacia `destino`, y
    esa es la IP que otra PC de la misma red puede usar.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((destino, 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return ip if _es_util(ip) else None


def _ips_de_los_adaptadores() -> list[str]:
    """Todas las IPv4 que el sistema le asigna a este nombre de máquina, sin repetir."""
    try:
        entradas = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    vistas: list[str] = []
    for entrada in entradas:
        ip = entrada[4][0]
        if ip not in vistas:
            vistas.append(ip)
    return vistas


def _prefiere_lan(ip: str) -> tuple[int, str]:
    """Primero las redes de una oficina, y adentro de cada rango el orden que dio el sistema."""
    if ip.startswith("192.168."):
        rango = 0
    elif ip.startswith("10."):
        rango = 1
    elif ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31:
        rango = 2
    else:
        rango = 3
    return rango, ""


def direccion_red() -> str | None:
    """
    La IP de esta máquina en la red local, o None si no hay red.

    Primero se le pregunta a la tabla de rutas por dónde saldría un paquete
    hacia afuera: ésa es la interfaz de verdad, y descarta solas las virtuales
    (VirtualBox, WSL, Hyper-V) que `gethostbyname(gethostname())` mezcla con
    la real. Se prueba con un destino de cada rango privado y no con uno
    solo, porque una red sin puerta de enlace —una PC de planta sin internet,
    que es el caso normal de Bot— no tiene por dónde salir hacia `10.x` si su
    red es `192.168.x`, y con un solo destino esto decía "sin red" en una
    máquina que estaba en la red.

    Si aun así no hay ruta, se cae a las direcciones de los adaptadores,
    prefiriendo las de una red de oficina. Peor que la tabla de rutas —puede
    elegir una virtual—, pero mucho mejor que no ofrecer nada: hasta acá, la
    única dirección que quedaba a la vista era el 127.0.0.1 de "Abrir Bot", y
    era la que terminaba copiada.
    """
    for destino in ("10.255.255.255", "192.168.255.255", "172.31.255.255", "8.8.8.8"):
        ip = _ip_de_salida_hacia(destino)
        if ip:
            return ip
    utiles = sorted((ip for ip in _ips_de_los_adaptadores() if _es_util(ip)), key=_prefiere_lan)
    return utiles[0] if utiles else None


def url_red(puerto: int, ip: str | None = None) -> str | None:
    ip = ip or direccion_red()
    return f"http://{ip}:{puerto}" if ip else None


def _copiar_win32(texto: str) -> bool:
    """
    El portapapeles de Windows por su API, sin ningún proceso en el medio.

    `clip.exe` funciona, pero desde `Bot.exe` —que no tiene consola— abre una
    ventana negra un instante cada vez, y depende de encontrar `clip` en el
    PATH. La API no depende de nada y no muestra nada.
    """
    import ctypes
    from ctypes import wintypes

    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    datos = texto.encode("utf-16-le") + bytes(2)
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        bloque = k32.GlobalAlloc(0x0002, len(datos))  # GMEM_MOVEABLE
        if not bloque:
            return False
        puntero = k32.GlobalLock(bloque)
        ctypes.memmove(puntero, datos, len(datos))
        k32.GlobalUnlock(bloque)
        if not u32.SetClipboardData(13, bloque):  # CF_UNICODETEXT
            k32.GlobalFree(bloque)
            return False
        return True
    finally:
        u32.CloseClipboard()


def copiar_al_portapapeles(texto: str) -> bool:
    """Sin tkinter (el runtime lo recorta): la API de Windows, o `clip`; en Linux, wl-copy/xclip/xsel."""
    if os.name == "nt":
        try:
            if _copiar_win32(texto):
                return True
        except (OSError, AttributeError, ValueError):
            pass
    comandos = [["clip"]] if os.name == "nt" else [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for comando in comandos:
        if shutil.which(comando[0]) is None:
            continue
        try:
            # `clip` lee la consola en UTF-16 sólo si el stdin es una consola; por
            # una tubería toma la página de códigos ANSI. Una URL es ASCII: da igual.
            # Las tres salidas redirigidas y sin ventana: desde un proceso sin
            # consola, dejarlas heredar es lo que falla o parpadea.
            subprocess.run(
                comando, input=texto.encode("utf-8"), check=True, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def copiar_y_avisar(texto: str, notificar: Callable[[str], None]) -> bool:
    """Copia y dice qué pasó: un clic en la bandeja no tiene otra forma de mostrar su resultado."""
    if copiar_al_portapapeles(texto):
        notificar(f"Copiado: {texto}")
        return True
    notificar(f"No se pudo copiar al portapapeles. La dirección es {texto}")
    return False


# ── El menú, como datos ─────────────────────────────────────────────────


def opciones(estado: Estado, acciones: Acciones) -> list[tuple[str, Callable[[], None]] | None]:
    """
    Las entradas del click derecho, en orden. `None` es un separador. Separado
    de pystray para poder afirmarlo en un test.
    """
    salida: list = [("Abrir Bot", lambda: acciones.abrir(estado.url))]

    if estado.en_red:
        publica = url_red(estado.puerto)
        if publica:
            salida.append((f"Copiar dirección para otras PCs ({publica})",
                           lambda: copiar_y_avisar(publica, acciones.notificar)))
        else:
            salida.append(("Sin red: no hay dirección para otras PCs", lambda: None))
    elif acciones.habilitar_red is not None:
        salida.append(("Habilitar acceso desde otras PCs (reinicia)", acciones.habilitar_red))

    registro = estado.raiz / "webapp.log"
    salida += [
        SEPARADOR,
        ("Ver registro (webapp.log)", lambda: abrir_archivo(registro)),
        ("Ver llamadas en una consola", lambda: seguir_registro(registro)),
        SEPARADOR,
        ("Reiniciar Bot", acciones.reiniciar),
        ("Cerrar Bot", acciones.cerrar),
    ]
    return salida


def abrir_archivo(ruta: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(ruta))  # noqa: S606 — abre con el programa asociado
        else:
            subprocess.Popen(["xdg-open", str(ruta)])
    except OSError:
        pass


def seguir_registro(ruta: Path) -> None:
    """Una consola que muestra las últimas líneas del registro y las que van llegando: las llamadas, en vivo."""
    try:
        if os.name == "nt":
            orden = f"Get-Content -Wait -Tail 60 -LiteralPath '{ruta}'"
            subprocess.Popen(
                ["cmd", "/c", "start", "Bot - registro", "powershell", "-NoLogo", "-NoExit", "-Command", orden],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        else:
            for terminal in ("x-terminal-emulator", "gnome-terminal", "xterm"):
                if shutil.which(terminal):
                    subprocess.Popen([terminal, "-e", f"tail -n 60 -f '{ruta}'"])
                    break
    except OSError:
        pass


# ── pystray ─────────────────────────────────────────────────────────────


def _imagen():
    """Un ícono dibujado acá: sin archivo que empaquetar ni que se pierda."""
    from PIL import Image, ImageDraw

    lado = 64
    imagen = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rounded_rectangle((4, 4, lado - 4, lado - 4), radius=14, fill=(37, 99, 235, 255))
    # La "B" a mano, con trazos gruesos: a 16 px una fuente no se lee.
    dibujo.rectangle((20, 14, 28, 50), fill="white")
    dibujo.pieslice((20, 14, 46, 33), start=270, end=90, fill="white")
    dibujo.pieslice((20, 31, 48, 50), start=270, end=90, fill="white")
    dibujo.rectangle((26, 20, 32, 27), fill=(37, 99, 235, 255))
    dibujo.rectangle((26, 37, 34, 44), fill=(37, 99, 235, 255))
    return imagen


def iniciar(estado: Estado, acciones: Acciones):
    """
    Muestra el ícono en un hilo propio y devuelve el objeto, para pararlo al
    salir (`icono.stop()`). None si no hay con qué (sin pystray o sin bandeja):
    el servidor sigue igual.
    """
    if not disponible():
        return None
    import pystray

    def item(entrada):
        if entrada is SEPARADOR:
            return pystray.Menu.SEPARATOR
        texto, accion = entrada
        return pystray.MenuItem(texto, lambda _icono, _item: accion(), default=texto == "Abrir Bot")

    # El menú se arma en cada apertura: la IP de la red puede cambiar.
    menu = pystray.Menu(lambda: (item(e) for e in opciones(estado, acciones)))
    titulo = f"Bot {estado.version}".strip() + f" · {estado.url}"
    icono = pystray.Icon("bot", _imagen(), titulo, menu)
    try:
        icono.run_detached()
    except Exception as exc:  # noqa: BLE001 — sin bandeja (sesión sin escritorio) se sigue sin ícono
        print(f"Sin ícono en la bandeja: {exc}", file=sys.stderr, flush=True)
        return None
    if getattr(icono, "HAS_NOTIFICATION", False):
        # El globo al lado del reloj: es lo único que quien hizo clic derecho
        # va a ver. Además del registro, que sigue recibiendo el texto.
        registrar = acciones.notificar

        def notificar(mensaje: str) -> None:
            registrar(mensaje)
            try:
                icono.notify(mensaje, "Bot")
            except Exception:  # noqa: BLE001 — sin globo, quedó en el registro
                pass

        acciones.notificar = notificar
    return icono


__all__ = [
    "Acciones", "Estado", "SEPARADOR", "abrir_archivo", "copiar_al_portapapeles", "copiar_y_avisar",
    "direccion_red", "disponible", "iniciar", "opciones", "seguir_registro", "url_red",
]

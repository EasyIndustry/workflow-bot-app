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


SEPARADOR = None


def disponible() -> bool:
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


# ── Dirección en la red ─────────────────────────────────────────────────


def direccion_red() -> str | None:
    """
    La IP de esta máquina en la red local, o None si no hay red.

    El truco del UDP sin enviar: `connect` sobre un socket UDP no manda nada,
    sólo hace que el sistema elija la interfaz de salida, y esa es la IP que
    otra PC de la misma red puede usar. `gethostbyname(gethostname())` suele
    devolver 127.0.0.1 o la IP de una interfaz virtual (VirtualBox, WSL).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def url_red(puerto: int, ip: str | None = None) -> str | None:
    ip = ip or direccion_red()
    return f"http://{ip}:{puerto}" if ip else None


def copiar_al_portapapeles(texto: str) -> bool:
    """Sin tkinter (el runtime lo recorta): el `clip` de Windows, o xclip/wl-copy si están."""
    comandos = [["clip"]] if os.name == "nt" else [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for comando in comandos:
        if shutil.which(comando[0]) is None:
            continue
        try:
            # `clip` lee la consola en UTF-16 sólo si el stdin es una consola; por
            # una tubería toma la página de códigos ANSI. Una URL es ASCII: da igual.
            subprocess.run(comando, input=texto.encode("utf-8"), check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
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
            salida.append((f"Copiar dirección para otras PCs ({publica})", lambda: copiar_al_portapapeles(publica)))
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
    return icono


__all__ = [
    "Acciones", "Estado", "SEPARADOR", "abrir_archivo", "copiar_al_portapapeles", "direccion_red",
    "disponible", "iniciar", "opciones", "seguir_registro", "url_red",
]

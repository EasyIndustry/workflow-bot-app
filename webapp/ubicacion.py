"""
Dónde está la instalación que esta webapp tiene que abrir.

El programa y los datos viven en dos lugares distintos a propósito (ver
`installer/source/pasos.py`): el programa en `%LOCALAPPDATA%\\Programs\\Bot`
o en el repo, la instalación —boot.env, data/, workspace/, plugins/— en la
carpeta que el cliente eligió en el wizard. Alguien tiene que recordar cuál.

El wizard la anota acá, en un archivo por usuario, y `python -m webapp` la
lee cuando nadie le dice otra cosa. La prioridad, de más a menos explícita:

    1. `--root` en la línea de comandos / la variable BOT_ROOT
    2. la carpeta del programa, si ella misma es una instalación (el repo de
       desarrollo, que tiene su data/ al lado del código)
    3. la última instalación que el wizard anotó
    4. la carpeta del programa, pelada (arranca con defaults, como siempre)

El archivo es JSON y no el registro de Windows para que sea el mismo
mecanismo en los dos sistemas y se pueda leer con cualquier editor.
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

ARCHIVO = "instalacion.json"
# Lo que marca que una carpeta es una instalación. Igual que `MARCAS` en el
# instalador: boot.env o data/.
MARCAS = ("boot.env", "data")


def carpeta_config(entorno: dict | None = None) -> Path:
    """La carpeta de configuración por usuario de este programa."""
    entorno = os.environ if entorno is None else entorno
    if platform.system() == "Windows":
        base = entorno.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Bot"
    base = entorno.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "bot"


def registrar(raiz: Path | str, entorno: dict | None = None) -> Path:
    """Anota `raiz` como la última instalación. Devuelve el archivo escrito."""
    carpeta = carpeta_config(entorno)
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / ARCHIVO
    archivo.write_text(
        json.dumps({"raiz": str(Path(raiz).resolve())}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return archivo


def ultima(entorno: dict | None = None) -> Path | None:
    """La última instalación anotada, si el archivo existe, se lee y la carpeta sigue ahí."""
    archivo = carpeta_config(entorno) / ARCHIVO
    if not archivo.is_file():
        return None
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        raiz = Path(str(datos["raiz"]))
    except (ValueError, KeyError, TypeError, OSError):
        return None
    return raiz if raiz.is_dir() else None


def es_instalacion(carpeta: Path) -> bool:
    """
    ¿Esta carpeta es una instalación?

    En el repo alcanza con `data/` al lado del código: es el caso que la regla
    2 existe para servir. En un programa instalado, no: ahí `data/` sólo puede
    haber aparecido por un arranque que no encontró la instalación anotada y
    cayó en la carpeta del programa. Y como después esa carpeta "es" una
    instalación, gana sobre la anotada y el error se vuelve permanente: el
    cliente abre el Bot y ve una instalación vacía, con la suya intacta al
    lado. Pasó en una máquina de desarrollo.

    Se distinguen por `runtime/`, el CPython que trae el `.exe` y que un
    checkout nunca tiene. Ahí se exige `boot.env`, que es lo que el wizard
    escribe y ningún arranque accidental crea.
    """
    marcas = ("boot.env",) if (carpeta / "runtime").is_dir() else MARCAS
    return any((carpeta / marca).exists() for marca in marcas)


def resolver_root(programa: Path, explicito: str | None = None, entorno: dict | None = None) -> Path:
    """Con qué raíz arrancar. Ver el orden en el docstring del módulo."""
    entorno = os.environ if entorno is None else entorno
    pedido = explicito or entorno.get("BOT_ROOT")
    if pedido:
        return Path(pedido).expanduser().resolve()
    if es_instalacion(programa):
        return programa
    anotada = ultima(entorno)
    if anotada is not None:
        return anotada
    return programa

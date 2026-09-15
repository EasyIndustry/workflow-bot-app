"""
Instalar un plugin: la puerta única, sea el origen un bucket curado o un
agente que acaba de terminar de escribirlo vía MCP.

    validar(carpeta, root=...)                       -> ¿el núcleo lo acepta?
    instalar(carpeta, plugins_dir, fuente, root=...)  -> validado y copiado,
                                                          con procedencia

`validar` corre en un subproceso — `python -m backend.core plugins --json` —
por la misma razón exacta que ya documenta `backend/mcp/operations.py`: el
registry importa por nombre de módulo (`importlib.import_module`), que cachea
en `sys.modules`. Instalar una versión nueva de un plugin con el mismo nombre
en el mismo proceso devolvería el módulo viejo. Un proceso nuevo por intento
lo evita, y de paso acota el daño de un plugin que se cuelgue al importarse.

`root` es la instalación contra la que se valida: sus adapters, sus límites
(`fs_root`, `process_allowlist`). Sin uno, se valida contra el `backend/` del
propio repo — suficiente para un chequeo de contrato genérico, antes de saber
a qué instalación en particular va a ir.

Que el resultado sea el mismo para los dos orígenes es la idea completa: un
plugin curado del bucket y uno que acaba de escribir un agente terminan en la
misma carpeta, con el mismo archivo de procedencia, sin que ninguno tenga un
camino más corto ni menos vigilado que el otro.

No importa nada de `installer/source/pasos.py`: instalar un plugin no depende
de estar en medio del wizard, puede pasar mucho después, contra una
instalación que ya existe.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Un plugin recién escrito por un agente puede colgarse al importarse. Sin
# tope, la instalación se queda esperando para siempre.
TIMEOUT = 120.0

# Empieza con punto a propósito: `Instance._plugins_de_la_carpeta` ya salta
# los nombres que arrancan con "." o "_" al escanear `plugins_dir`, así que
# este archivo nunca se confunde con un plugin más.
ARCHIVO_PROCEDENCIA = ".procedencia.json"


class PluginInvalido(Exception):
    """La carpeta no pasa la validación del núcleo. No se instala nada."""


@dataclass(frozen=True)
class Validacion:
    ok: bool
    nombre: str = ""
    version: str = ""
    ports: tuple[str, ...] = ()
    errores: tuple[str, ...] = ()


def validar(carpeta: str | Path, *, root: str | Path | None = None) -> Validacion:
    """
    ¿El núcleo acepta este plugin? Mismo criterio que `load_plugin` del MCP de
    autoría: ports declarados que existen, contrato soportado, ids sin
    duplicar, acciones declaradas en el manifest. Si algo falla, el registry
    lo reporta sin registrar ni uno de sus tools — no hay instalación a medias
    posible porque acá todavía no se instaló nada.
    """
    carpeta = Path(carpeta).resolve()
    if not carpeta.is_dir():
        return Validacion(ok=False, errores=(f"no existe la carpeta: {carpeta}",))
    if not (carpeta / "__init__.py").is_file():
        return Validacion(ok=False, errores=(
            "la carpeta tiene que ser un paquete: necesita un __init__.py que "
            "exporte PLUGIN",
        ))

    nombre = carpeta.name
    # `--plugin` y `--root` son globales: van antes del subcomando, o argparse
    # los rechaza como "unrecognized arguments" en vez de aplicarlos.
    comando = [sys.executable, "-m", "backend.core"]
    if root is not None:
        comando += ["--root", str(root)]
    comando += ["--plugin", f"{nombre}={carpeta}", "plugins", "--json"]

    try:
        completado = subprocess.run(
            comando, cwd=str(RAIZ), capture_output=True, text=True,
            timeout=TIMEOUT, shell=False,
        )
    except subprocess.TimeoutExpired:
        return Validacion(ok=False, nombre=nombre, errores=(
            f"no terminó de cargar en {TIMEOUT:g}s — revisá que no haga trabajo "
            "pesado al importarse",
        ))
    except OSError as exc:
        return Validacion(ok=False, nombre=nombre, errores=(f"no se pudo validar: {exc}",))

    salida = completado.stdout.strip()
    try:
        catalogo = json.loads(salida)
    except json.JSONDecodeError:
        detalle = salida[:400] or completado.stderr.strip()[:400] or "sin salida"
        return Validacion(ok=False, nombre=nombre, errores=(f"la validación no devolvió JSON: {detalle}",))

    # El código de salida no se trata como error: es 1 apenas *algún* plugin
    # de la instalación falló cargar, y eso puede no tener nada que ver con
    # el candidato — se filtra por nombre, no por código de salida.
    error = next((e for e in catalogo.get("errors", []) if e["name"] == nombre), None)
    if error is not None:
        return Validacion(ok=False, nombre=nombre, errores=(error["error"],))

    cargado = next((p for p in catalogo.get("plugins", []) if p["name"] == nombre), None)
    if cargado is None:
        return Validacion(ok=False, nombre=nombre, errores=("el plugin no se registró",))

    return Validacion(
        ok=True, nombre=nombre, version=cargado["version"], ports=tuple(cargado["ports"]),
    )


def instalar(
    carpeta: str | Path, plugins_dir: str | Path, *, fuente: str, root: str | Path | None = None,
) -> dict:
    """
    Valida y copia a `plugins_dir/<nombre>/`, con un archivo de procedencia al
    lado: de dónde salió (`fuente`: "bucket", "agent", lo que declare quien
    llama) y con qué versión quedó.

    `fuente` es sólo metadata — de qué lado vino esta carpeta, no un permiso
    distinto: la validación de arriba es la misma para cualquier valor.

    Arma la copia en una carpeta temporal al lado y recién al final la
    renombra sobre el destino, que en el mismo filesystem es atómico: una
    instalación que se corta a mitad de copiar deja la versión vieja intacta,
    nunca una carpeta a medio escribir con la que el núcleo intenta cargar en
    el próximo arranque.
    """
    resultado = validar(carpeta, root=root)
    if not resultado.ok:
        raise PluginInvalido(
            "; ".join(resultado.errores) or f"'{carpeta}' no pasa la validación"
        )

    destino_base = Path(plugins_dir).resolve()
    destino_base.mkdir(parents=True, exist_ok=True)
    destino = destino_base / resultado.nombre
    temporal = destino_base / f"{resultado.nombre}.instalando"

    if temporal.exists():
        shutil.rmtree(temporal)
    shutil.copytree(Path(carpeta).resolve(), temporal)

    (temporal / ARCHIVO_PROCEDENCIA).write_text(
        json.dumps(
            {
                "name": resultado.nombre,
                "version": resultado.version,
                "source": fuente,
                "installed_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if destino.exists():
        shutil.rmtree(destino)
    temporal.rename(destino)

    return {
        "name": resultado.nombre,
        "version": resultado.version,
        "ports": list(resultado.ports),
        "path": str(destino),
        "source": fuente,
    }


def procedencia(plugins_dir: str | Path, nombre: str) -> dict | None:
    """La procedencia de un plugin ya instalado, o None si no la tiene."""
    archivo = Path(plugins_dir) / nombre / ARCHIVO_PROCEDENCIA
    if not archivo.is_file():
        return None
    return json.loads(archivo.read_text(encoding="utf-8"))


__all__ = ["ARCHIVO_PROCEDENCIA", "PluginInvalido", "Validacion", "instalar", "procedencia", "validar"]

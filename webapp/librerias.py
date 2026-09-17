"""
Librerías Python de los plugins: qué piden, qué hay en el runtime, y cómo se
instala lo que falta.

Un plugin del núcleo no importa librerías para hacer **I/O** —eso es un port,
que el núcleo acota por actor y por `boot.env`—, pero sí puede necesitar una
para **cómputo** (numpy, trimesh, un parser). Antes no había forma de que esa
librería existiera en la máquina del cliente: el `.exe` trae su propio
CPython en `%LOCALAPPDATA%\\Programs\\Bot\\runtime` con lo que la app usa, y
nada más. Decidido el 16/09/2026 (workflow-bot-core#20, workflow-bot-plugins#1):

- El plugin trae `requirements.txt` junto a su `__init__.py`, una línea por
  librería con `==versión` y `--hash=sha256:...`. **Sin las dos cosas la línea
  no se acepta**: lo que se instala es exactamente lo que el curador probó,
  y el hash lo generó él bajando la wheel de PyPI, no quien mandó el plugin.
- La app lo instala **en el runtime que la corre** (`sys.executable`; en la
  máquina del cliente es ese CPython, en desarrollo el venv), con pip y sólo
  desde wheels: `--only-binary :all: --require-hashes`. Un sdist ejecuta
  código al instalarse; una wheel sólo se descomprime.
- Sin internet: la carpeta `wheels/` del plugin o la carpeta `wheels/` de la
  instalación entran por `--find-links`; con `sin_red` no se toca PyPI.
- El runtime está **versionado**: el `.exe` deja `runtime-release.json`
  (versión exacta de Python y de cada librería base) y el catálogo cura
  contra esa versión. Acá se lee ese archivo, o se arma en vivo si no está
  (desarrollo).

El runtime es uno por PC y lo comparten las instalaciones de esa PC: instalar
una librería para un plugin la deja para todos. Con versiones fijas en el
catálogo, un choque entre dos plugins se ve al curar y no acá; si igual pasa,
pip lo dice y la instalación del plugin falla antes de copiar nada.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REQUISITOS = "requirements.txt"
WHEELS = "wheels"
MARCA_RUNTIME = "runtime-release.json"
# pip contra PyPI con wheels grandes (numpy ~15 MB) en una conexión lenta.
TIMEOUT = 600

# `nombre==1.2.3 --hash=sha256:...` con más hashes y espacios opcionales.
# Un nombre de distribución según PEP 508: letras, números, `.`, `_`, `-`.
_LINEA = re.compile(
    r"^(?P<nombre>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[^\]]*\])?\s*==\s*(?P<version>[A-Za-z0-9.+!*-]+)"
    r"(?P<resto>(?:\s+--hash=sha256:[0-9a-fA-F]{64})+)\s*$"
)


class LibreriasError(Exception):
    """El requirements no cumple la convención, o pip no pudo instalarlo."""

    def __init__(self, mensaje: str, detalle: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.detalle = detalle or []


# ── Qué pide un plugin ────────────────────────────────────────────────────


def requisitos_de(ruta_plugin: Path) -> Path | None:
    """El `requirements.txt` de un plugin, si es una carpeta y lo trae. Un `.py` suelto no declara nada."""
    ruta_plugin = Path(ruta_plugin)
    if not ruta_plugin.is_dir():
        return None
    archivo = ruta_plugin / REQUISITOS
    return archivo if archivo.is_file() else None


def leer_requisitos(archivo: Path) -> list[dict]:
    """
    Las líneas del requirements, validadas contra la convención: cada una con
    versión fija y al menos un hash. Devuelve `[{"name", "version", "hashes", "line"}]`.

    Se rechaza acá y no en pip porque el mensaje de pip para "falta un hash"
    habla de `--require-hashes` y de modos, y lo que hay que decirle a quien
    instala es qué línea del archivo está mal y por qué.
    """
    errores, salida = [], []
    for numero, cruda in enumerate(Path(archivo).read_text(encoding="utf-8").splitlines(), start=1):
        # Continuaciones con `\` se juntan a la línea anterior, como hace pip.
        linea = cruda.split("#", 1)[0].strip()
        if not linea:
            continue
        if salida and salida[-1].get("_continua"):
            salida[-1]["line"] += " " + linea
            salida[-1]["_continua"] = linea.endswith("\\")
            salida[-1]["line"] = salida[-1]["line"].rstrip("\\").rstrip()
            continue
        if linea.startswith("-"):
            errores.append(f"línea {numero}: opciones de pip ({linea.split()[0]}) no se aceptan; sólo `nombre==versión --hash=...`")
            continue
        salida.append({"line": linea.rstrip("\\").rstrip(), "_continua": linea.endswith("\\"), "_numero": numero})

    for entrada in salida:
        m = _LINEA.match(entrada["line"])
        if m is None:
            if "==" not in entrada["line"]:
                motivo = "sin versión fija (`==`)"
            elif "--hash=" not in entrada["line"]:
                motivo = "sin `--hash=sha256:...`; el hash lo genera el curador con `pip hash` sobre la wheel bajada de PyPI"
            else:
                motivo = "no tiene la forma `nombre==versión --hash=sha256:...`"
            errores.append(f"línea {entrada['_numero']}: {motivo}")
            continue
        entrada["name"] = m.group("nombre")
        entrada["version"] = m.group("version")
        entrada["hashes"] = re.findall(r"--hash=sha256:([0-9a-fA-F]{64})", m.group("resto"))
        entrada.pop("_continua", None)
        entrada.pop("_numero", None)

    if errores:
        raise LibreriasError(f"{Path(archivo).name} no cumple la convención de librerías", errores)
    return salida


def _normalizar(nombre: str) -> str:
    return re.sub(r"[-_.]+", "-", nombre).lower()


def version_instalada(nombre: str) -> str | None:
    try:
        return metadata.version(nombre)
    except metadata.PackageNotFoundError:
        return None


def estado_de(requisitos: list[dict]) -> list[dict]:
    """Cada requisito con lo que hay en este intérprete: `installed` y `ok` (misma versión)."""
    salida = []
    for r in requisitos:
        instalada = version_instalada(r["name"])
        salida.append({
            "name": r["name"], "required": r["version"], "installed": instalada,
            "ok": instalada is not None and _normalizar(instalada) == _normalizar(r["version"]),
        })
    return salida


# ── El runtime ────────────────────────────────────────────────────────────


def runtime(programa: Path) -> dict:
    """
    La versión del runtime: la que dejó el `.exe` en `runtime-release.json`, o
    la de este intérprete en vivo si no hay marca (desarrollo, o un programa
    anterior a la marca). `source` dice cuál de las dos es.
    """
    marca = Path(programa) / MARCA_RUNTIME
    if marca.is_file():
        try:
            datos = json.loads(marca.read_text(encoding="utf-8"))
            return {**datos, "source": "instalador", "executable": sys.executable}
        except (ValueError, OSError):
            pass
    return {
        "tag": None,
        "python": sys.version.split()[0],
        "packages": paquetes_presentes(),
        "source": "en vivo",
        "executable": sys.executable,
    }


def paquetes_presentes() -> dict[str, str]:
    """Lo instalado en este intérprete, `{nombre: versión}`."""
    salida = {}
    for d in metadata.distributions():
        nombre = d.metadata["Name"] if d.metadata else None
        if nombre:
            salida[_normalizar(nombre)] = d.version
    return dict(sorted(salida.items()))


# ── Instalar ──────────────────────────────────────────────────────────────


def carpetas_de_wheels(ruta_plugin: Path | None, root: Path | None) -> list[Path]:
    """Las carpetas con wheels que existen: la del plugin y la de la instalación."""
    candidatas = []
    if ruta_plugin is not None:
        candidatas.append(Path(ruta_plugin) / WHEELS)
    if root is not None:
        candidatas.append(Path(root) / WHEELS)
    return [c for c in candidatas if c.is_dir() and any(c.glob("*.whl"))]


def comando_pip(archivo: Path, *, wheels: list[Path], sin_red: bool, python: str | None = None) -> list[str]:
    """
    El argv de pip, completo y sin sorpresas: sólo wheels, con hash
    obligatorio, sin preguntar, y sin la comprobación de versión de pip que
    sale a la red por su cuenta.
    """
    comando = [
        python or sys.executable, "-m", "pip", "install",
        "--only-binary", ":all:", "--require-hashes",
        "--disable-pip-version-check", "--no-input", "--no-color",
        "-r", str(archivo),
    ]
    for carpeta in wheels:
        comando += ["--find-links", str(carpeta)]
    if sin_red:
        comando.append("--no-index")
    return comando


def instalar_requisitos(
    archivo: Path, *, ruta_plugin: Path | None = None, root: Path | None = None,
    sin_red: bool = False, python: str | None = None, correr=None,
) -> dict:
    """
    Instala lo que pide el requirements en el intérprete que corre la app.
    Devuelve `{"installed": [...], "command": [...], "output": "..."}`; levanta
    `LibreriasError` con la salida de pip si algo falla.

    Antes de llamar a pip se valida la convención (`leer_requisitos`), y si
    todo ya está en la versión pedida no se corre nada: instalar un plugin por
    segunda vez no tiene por qué salir a la red.
    """
    requisitos = leer_requisitos(archivo)
    estado = estado_de(requisitos)
    if all(e["ok"] for e in estado):
        return {"installed": estado, "command": None, "output": "ya estaban en la versión pedida"}

    wheels = carpetas_de_wheels(ruta_plugin, root)
    if sin_red and not wheels:
        raise LibreriasError(
            "Sin internet no hay de dónde instalar: no hay wheels en la carpeta del plugin ni en "
            f"`{WHEELS}/` de la instalación.",
            [f"Copiá las wheels ({', '.join(r['name'] for r in requisitos)}) a {Path(root) / WHEELS if root else WHEELS} y volvé a intentar."],
        )
    comando = comando_pip(archivo, wheels=wheels, sin_red=sin_red, python=python)
    correr = correr or subprocess.run
    try:
        completado = correr(comando, capture_output=True, text=True, timeout=TIMEOUT, shell=False)
    except subprocess.TimeoutExpired:
        raise LibreriasError(f"pip no terminó en {TIMEOUT} s", [" ".join(comando)]) from None
    salida = ((completado.stdout or "") + "\n" + (completado.stderr or "")).strip()
    if completado.returncode != 0:
        lineas = [l for l in salida.splitlines() if l.strip()]
        raise LibreriasError(
            "pip no pudo instalar las librerías del plugin",
            _explicar(lineas, python=python) + lineas[-12:],
        )
    # Lo que quedó, releído: `importlib.metadata` cachea por proceso, así que
    # el estado se toma del intérprete que instaló, no de este.
    return {"installed": _estado_en_subproceso(requisitos, python), "command": comando, "output": salida[-2000:]}


def _explicar(lineas: list[str], python: str | None = None) -> list[str]:
    """Una línea en castellano para los fallos de pip que se pueden anticipar."""
    texto = "\n".join(lineas)
    if "THESE PACKAGES DO NOT MATCH THE HASHES" in texto:
        return ["El hash de una wheel no coincide con el del requirements: no es la que curó el catálogo. No se instaló nada."]
    if "No matching distribution" in texto or "Could not find a version" in texto:
        # Con la versión de Python puesta, no "esta versión": el catálogo cura
        # contra el runtime del programa (3.12), y desde el servidor del repo
        # (3.11) este error hacía pensar que el plugin estaba roto, cuando lo
        # que pasa es que se le está pidiendo a otro intérprete.
        version = _version_de(python) if python else sys.version.split()[0]
        return [
            f"No hay una wheel de esa versión exacta para Python {version} en Windows, o no hay conexión a PyPI. "
            f"Si esto es el servidor de desarrollo, las librerías se instalan desde el programa instalado, "
            f"que es el runtime contra el que el catálogo cura el plugin. Sin internet: wheels en la carpeta `wheels/`."
        ]
    if "Access is denied" in texto or "Permission denied" in texto or "WinError 5" in texto:
        return ["No se pudo escribir en el runtime. Si el servidor está corriendo con esa librería cargada, cerrarlo y volver a intentar."]
    return []


def _version_de(python: str) -> str:
    """La versión de otro intérprete, o la de éste si no se pudo preguntar."""
    try:
        r = subprocess.run([python, "-c", "import sys; print(sys.version.split()[0])"],
                           capture_output=True, text=True, timeout=15, shell=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return sys.version.split()[0]


def _estado_en_subproceso(requisitos: list[dict], python: str | None) -> list[dict]:
    """El estado de los requisitos según un intérprete recién lanzado, que ve lo que pip acaba de dejar."""
    codigo = (
        "import json,sys\nfrom importlib import metadata\n"
        "salida=[]\n"
        "for n in json.loads(sys.argv[1]):\n"
        "    try: salida.append(metadata.version(n))\n"
        "    except metadata.PackageNotFoundError: salida.append(None)\n"
        "print(json.dumps(salida))"
    )
    try:
        completado = subprocess.run(
            [python or sys.executable, "-c", codigo, json.dumps([r["name"] for r in requisitos])],
            capture_output=True, text=True, timeout=60, shell=False,
        )
        versiones = json.loads(completado.stdout)
    except (subprocess.SubprocessError, ValueError, OSError):
        return estado_de(requisitos)
    return [
        {"name": r["name"], "required": r["version"], "installed": v,
         "ok": v is not None and _normalizar(v) == _normalizar(r["version"])}
        for r, v in zip(requisitos, versiones)
    ]


__all__ = [
    "LibreriasError", "MARCA_RUNTIME", "REQUISITOS", "WHEELS",
    "carpetas_de_wheels", "comando_pip", "estado_de", "instalar_requisitos",
    "leer_requisitos", "paquetes_presentes", "requisitos_de", "runtime", "version_instalada",
]

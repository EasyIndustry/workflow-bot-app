"""
Instalar y desinstalar plugins en la carpeta `plugins_dir` de la instalación.

El núcleo carga lo que haya en `plugins_dir` al arrancar (ver
`Instance._plugins_de_la_carpeta`): un `.py` suelto o una carpeta con
`__init__.py`, ambos exponiendo `PLUGIN`. "Instalar" es, entonces, dejar el
archivo ahí. Lo que este módulo agrega es lo que hace que dejarlo ahí no sea
un salto al vacío:

1. **Se valida antes de activar, en otro proceso.** El registry valida al
   importar, y un import ejecuta código. Se corre `python -m backend.core
   --plugin nombre=ruta plugins --json` contra una raíz vacía y temporal: si el
   plugin pide un port que no existe, tiene ids duplicados, un contrato viejo,
   o directamente revienta al importar, lo dice el JSON y el servidor sigue
   entero. Nada se copia a `plugins_dir` hasta que ese chequeo pasa.

2. **Se copia, no se enlaza.** El origen puede ser una ruta de esta máquina (lo
   que usa un agente que acaba de escribirlo) o un archivo subido desde el
   navegador; en los dos casos lo que queda en `plugins_dir` es una copia
   propia, y borrar el original no rompe la instalación.

3. **Sin pisar por accidente.** Instalar un nombre que ya existe falla salvo
   que se pida `reemplazar`, y aun así el anterior se guarda a un costado hasta
   que el nuevo se valida — si el nuevo no carga, vuelve el viejo.

Lo que no hace, a propósito: no instala paquetes de pip ni resuelve
dependencias. Un plugin del núcleo no importa librerías externas (pide ports),
así que un archivo o una carpeta es todo lo que hay que instalar.

Después de instalar hay que **recargar la instancia**: el registry se arma una
vez al construirla. Eso es de quien orquesta (la API), no de acá.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TIMEOUT = 60
_NOMBRE_VALIDO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Lo que `plugins --json` puede pesar con muchos plugins: sobra.
_MAX_ZIP_BYTES = 20 * 1024 * 1024


class InstallError(Exception):
    """El origen no sirve, el nombre choca o la validación no pasó."""

    def __init__(self, mensaje: str, errores: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.errores = errores or []


# ── Qué hay ─────────────────────────────────────────────────────────────


def instalados(plugins_dir: Path | None) -> list[dict]:
    """Los plugins que viven en la carpeta, con la misma regla que usa el núcleo para verlos."""
    if plugins_dir is None or not plugins_dir.is_dir():
        return []
    salida = []
    for entrada in sorted(plugins_dir.iterdir()):
        if entrada.name.startswith((".", "_")):
            continue
        if entrada.is_file() and entrada.suffix == ".py":
            salida.append({"name": entrada.stem, "path": str(entrada), "kind": "file"})
        elif entrada.is_dir() and (entrada / "__init__.py").is_file():
            salida.append({"name": entrada.name, "path": str(entrada), "kind": "package"})
    return salida


def ruta_de(plugins_dir: Path, nombre: str) -> Path | None:
    """Dónde está instalado `nombre`, o None."""
    for p in instalados(plugins_dir):
        if p["name"] == nombre:
            return Path(p["path"])
    return None


# ── Validar ─────────────────────────────────────────────────────────────


def validar(nombre: str, ruta: Path) -> dict:
    """
    Carga el plugin en un proceso aparte y devuelve qué dijo el núcleo.

    Raíz vacía y temporal, y sin variables `BOOTSTRAP_*`: se valida el plugin
    solo, no contra lo que ya está instalado — los choques con lo instalado se
    ven al recargar, y quien orquesta los trata ahí. Devuelve
    `{"ok", "errors", "plugin"}`.
    """
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("BOOTSTRAP_")}
    with tempfile.TemporaryDirectory(prefix="bot-validar-") as raiz_tmp:
        comando = [
            sys.executable, "-m", "backend.core", "--root", raiz_tmp,
            "--plugin", f"{nombre}={ruta}", "plugins", "--json",
        ]
        try:
            completado = subprocess.run(
                comando, cwd=str(RAIZ), capture_output=True, text=True,
                timeout=TIMEOUT, shell=False, env=entorno,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "errors": [f"la validación no terminó en {TIMEOUT} s"], "plugin": None}

    try:
        catalogo = json.loads(completado.stdout)
    except ValueError:
        detalle = (completado.stderr or completado.stdout or "").strip().splitlines()
        return {
            "ok": False,
            "errors": ["la validación no devolvió un catálogo"] + detalle[-8:],
            "plugin": None,
        }

    errores = [e["error"] for e in catalogo.get("errors", []) if e.get("name") == nombre]
    cargado = next((p for p in catalogo.get("plugins", []) if p["name"] == nombre), None)
    if errores or cargado is None:
        return {"ok": False, "errors": errores or ["el plugin no se registró"], "plugin": None}
    return {"ok": True, "errors": [], "plugin": cargado}


# ── Instalar ────────────────────────────────────────────────────────────


def instalar(plugins_dir: Path | None, origen: Path, *, nombre: str | None = None, reemplazar: bool = False) -> dict:
    """
    Copia `origen` (un `.py`, una carpeta con `__init__.py`, o un `.zip` con
    cualquiera de las dos) a `plugins_dir`, validándolo antes.

    Devuelve `{"name", "path", "plugin"}`, con `plugin` como lo describe el
    catálogo del núcleo. Levanta `InstallError` con los motivos si no pasa.
    """
    if plugins_dir is None:
        raise InstallError(
            "Esta instalación no declara plugins_dir en boot.env: no hay dónde instalar. "
            "Se agrega la clave apuntando a una carpeta fuera de fs_root y se reinicia."
        )
    origen = Path(origen).expanduser()
    if not origen.exists():
        raise InstallError(f"No existe {origen}")

    with tempfile.TemporaryDirectory(prefix="bot-instalar-") as tmp:
        candidato = _preparar(origen, Path(tmp))
        nombre_final = _validar_nombre(nombre or (candidato.stem if candidato.is_file() else candidato.name))
        # Renombrado en el staging, para que el módulo se importe con el nombre
        # con el que va a quedar instalado y la validación pruebe eso mismo.
        destino_tmp = Path(tmp) / (f"{nombre_final}.py" if candidato.is_file() else nombre_final)
        if candidato != destino_tmp:
            candidato.rename(destino_tmp)

        veredicto = validar(nombre_final, destino_tmp)
        if not veredicto["ok"]:
            raise InstallError(f'El plugin "{nombre_final}" no carga', veredicto["errors"])

        plugins_dir.mkdir(parents=True, exist_ok=True)
        existente = ruta_de(plugins_dir, nombre_final)
        if existente is not None and not reemplazar:
            raise InstallError(
                f'Ya hay un plugin "{nombre_final}" instalado en {existente}. '
                "Para pisarlo, pedir reemplazar."
            )

        respaldo = None
        if existente is not None:
            respaldo = _apartar(existente)
        destino = plugins_dir / destino_tmp.name
        try:
            if destino_tmp.is_dir():
                shutil.copytree(destino_tmp, destino, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(destino_tmp, destino)
        except Exception:
            if respaldo is not None:
                _restaurar(respaldo, existente)
            raise
        if respaldo is not None:
            _borrar(respaldo)

    return {"name": nombre_final, "path": str(destino), "plugin": veredicto["plugin"]}


def desinstalar(plugins_dir: Path | None, nombre: str) -> Path:
    """Saca el plugin de la carpeta. Sólo lo que vive ahí: nada fuera de `plugins_dir`."""
    if plugins_dir is None:
        raise InstallError("Esta instalación no declara plugins_dir: no hay nada instalado ahí.")
    ruta = ruta_de(plugins_dir, _validar_nombre(nombre))
    if ruta is None:
        raise InstallError(f'No hay ningún plugin "{nombre}" en {plugins_dir}')
    _borrar(ruta)
    return ruta


# ── Internos ────────────────────────────────────────────────────────────


def _preparar(origen: Path, tmp: Path) -> Path:
    """Deja en `tmp` el `.py` o la carpeta que se va a instalar, venga como venga."""
    if origen.is_dir():
        if not (origen / "__init__.py").is_file():
            raise InstallError(f"{origen} es una carpeta sin __init__.py: el núcleo no la cargaría")
        destino = tmp / origen.name
        shutil.copytree(origen, destino, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return destino

    if origen.suffix == ".py":
        destino = tmp / origen.name
        shutil.copy2(origen, destino)
        return destino

    if origen.suffix == ".zip":
        return _desempaquetar(origen, tmp)

    raise InstallError(f"{origen.name}: se espera un .py, una carpeta con __init__.py o un .zip")


def _desempaquetar(zip_path: Path, tmp: Path) -> Path:
    if zip_path.stat().st_size > _MAX_ZIP_BYTES:
        raise InstallError("El .zip pesa más de 20 MB: un plugin del núcleo no necesita eso")
    extraido = tmp / "zip"
    extraido.mkdir()
    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                # Sin rutas absolutas ni `..`: lo que hay adentro no decide dónde escribe.
                partes = Path(info.filename).parts
                if not partes or info.filename.startswith(("/", "\\")) or ".." in partes:
                    raise InstallError(f"El .zip trae una ruta inválida: {info.filename}")
            z.extractall(extraido)
    except zipfile.BadZipFile:
        raise InstallError(f"{zip_path.name} no es un .zip válido") from None

    visibles = [p for p in extraido.iterdir() if not p.name.startswith((".", "_")) or p.name == "__init__.py"]
    if (extraido / "__init__.py").is_file():
        # Un paquete "plano": los archivos del plugin en la raíz del zip. Toma
        # el nombre del zip.
        destino = tmp / _validar_nombre(zip_path.stem)
        extraido.rename(destino)
        return destino
    if len(visibles) == 1 and visibles[0].is_dir() and (visibles[0] / "__init__.py").is_file():
        return visibles[0]
    if len(visibles) == 1 and visibles[0].is_file() and visibles[0].suffix == ".py":
        return visibles[0]
    raise InstallError(
        "El .zip tiene que traer un único plugin: un .py, una carpeta con __init__.py, "
        "o los archivos del paquete con su __init__.py en la raíz"
    )


def _validar_nombre(nombre: str) -> str:
    nombre = (nombre or "").strip()
    if not _NOMBRE_VALIDO.match(nombre):
        raise InstallError(
            f"Nombre de plugin inválido: {nombre!r}. Tiene que poder importarse como módulo de "
            "Python: letras, números y guión bajo, sin empezar con un número."
        )
    return nombre


def _apartar(ruta: Path) -> Path:
    respaldo = ruta.with_name(f"_{ruta.name}.anterior")
    _borrar(respaldo)
    ruta.rename(respaldo)
    return respaldo


def _restaurar(respaldo: Path, original: Path) -> None:
    _borrar(original)
    respaldo.rename(original)


def _borrar(ruta: Path) -> None:
    if ruta.is_dir():
        shutil.rmtree(ruta, ignore_errors=True)
    elif ruta.exists():
        ruta.unlink()

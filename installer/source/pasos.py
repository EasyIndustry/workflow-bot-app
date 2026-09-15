"""
La lógica del instalador, sin HTTP.

Está separada del servidor a propósito: cada paso del wizard es una función que
recibe datos y devuelve datos, así que se puede probar sin levantar nada y se
podría reusar desde una CLI el día que haga falta.

Qué instala
-----------

Una instalación acotada: una sola carpeta, y adentro tres zonas que no se
mezclan.

    <raiz>/
    ├── boot.env        config de arranque
    ├── data/           bot.db + secret.key    ·  FUERA de la caja
    ├── plugins/        plugins_dir            ·  FUERA de la caja
    └── workspace/      fs_root                ·  la caja

`data/` queda fuera de `fs_root` a propósito. El núcleo ya impide que un plugin
pida los ports `storage` y `crypto`, pero si la base y la llave vivieran dentro
del árbol permitido, un plugin con el port `fs` las alcanzaría por la puerta del
filesystem y la separación se caería por abajo.

`plugins/` queda fuera por la misma razón, en la otra dirección: es código que
el núcleo carga al arrancar. Si un flujo pudiera escribir ahí, un flujo
comprometido dejaría un plugin listo para correr en el próximo arranque.

Al terminar, la instalación se anota en un archivo por usuario
(`webapp/ubicacion.py`): es lo que permite que "Abrir Bot" sepa qué abrir sin
preguntar de nuevo.

La carpeta también la usa `installer/source/plugins.py`, el primitivo que valida
y copia un plugin con su procedencia; la app llega a lo mismo por
`webapp/plugin_install.py`.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.core import boot
from webapp import ubicacion

# Lo que el instalador considera una instalación ya existente.
MARCAS = (boot.ARCHIVO, "data")

# Subcarpeta que queda como `fs_root`. Es lo único que los flujos pueden tocar.
CAJA = "workspace"

# Subcarpeta de plugins: fuera de la caja, igual que data/.
PLUGINS = "plugins"

# Timeout por defecto de los requests. Explícito y no `None`: un valor que el
# cliente puede ver y cambiar vale más que uno escondido en un default.
TIMEOUT = 30.0

PYTHON_MINIMO = (3, 11)


# ── Paso 1: dónde ───────────────────────────────────────────────────────


def escritorio() -> Path:
    """
    El escritorio del usuario, o su carpeta personal si no se puede saber.

    Ninguno de los dos sistemas garantiza que se llame "Desktop":

    - En Windows la carpeta puede estar **redirigida** —a OneDrive, o a un perfil
      de red, que en una planta es lo habitual— y la redirección queda anotada en
      el registro. Adivinar `USERPROFILE\\Desktop` acierta en la máquina de
      desarrollo y falla justo en las que tienen perfil administrado.
    - En Linux el nombre depende del idioma (`Desktop`, `Escritorio`, …) y quien
      sabe es XDG.

    Si nada contesta, la carpeta personal: es mejor una sugerencia rara que un
    campo vacío.
    """
    casa = Path.home()

    if platform.system() == "Windows":
        if (desde_registro := _escritorio_windows()) is not None:
            return desde_registro
        for candidata in (casa / "Desktop", casa / "OneDrive" / "Desktop", casa / "Escritorio"):
            if candidata.is_dir():
                return candidata
        return casa

    xdg = shutil.which("xdg-user-dir")
    if xdg:
        try:
            salida = subprocess.run(
                [xdg, "DESKTOP"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if salida and Path(salida).is_dir() and Path(salida) != casa:
                return Path(salida)
        except (OSError, subprocess.SubprocessError):
            pass

    for nombre in ("Escritorio", "Desktop"):
        if (casa / nombre).is_dir():
            return casa / nombre
    return casa


def _escritorio_windows() -> Path | None:
    """
    La carpeta de escritorio según el registro, que es quien sabe de verdad.

    `Shell Folders` trae la ruta ya expandida; `User Shell Folders` puede traer
    algo como `%USERPROFILE%\\Desktop` sin expandir, así que se pasa por
    `expandvars`. Se leen las dos porque la primera no siempre existe en un
    perfil recién creado.

    Devuelve `None` ante cualquier problema: en una planta con perfiles
    administrados esto puede fallar de maneras raras, y el instalador tiene que
    seguir andando con la sugerencia de siempre.
    """
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:  # no es Windows
        return None

    clave = r"Software\Microsoft\Windows\CurrentVersion\Explorer"
    for sub, nombre in ((f"{clave}\\Shell Folders", "Desktop"),
                        (f"{clave}\\User Shell Folders", "Desktop")):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                crudo, _ = winreg.QueryValueEx(k, nombre)
        except OSError:
            continue
        ruta = Path(os.path.expandvars(str(crudo)))
        if ruta.is_dir():
            return ruta
    return None


def sugerencia() -> dict:
    """La carpeta que el wizard propone, ya resuelta a absoluta."""
    destino = escritorio() / "Bot"
    return {"ruta": str(destino), "escritorio": str(escritorio()), "casa": str(Path.home())}


def revisar_destino(ruta: str) -> dict:
    """
    Si se puede instalar ahí, y qué hay hoy.

    No crea nada: es la pantalla previa. Un destino con una instalación adentro
    se reporta como tal en vez de pisarse, que es la única decisión que no
    podemos tomar por el cliente.
    """
    texto = (ruta or "").strip()
    if not texto:
        return _destino_invalido(texto, "Escribí una carpeta.")

    try:
        destino = Path(texto).expanduser()
    except (OSError, RuntimeError) as exc:
        return _destino_invalido(texto, f"No se entiende la ruta: {exc}")

    if not destino.is_absolute():
        return _destino_invalido(
            str(destino),
            "La ruta tiene que ser absoluta. Una relativa depende de desde dónde "
            "se arranque el bot, y la instalación quedaría en un lugar distinto "
            "cada vez.",
        )

    destino = Path(os.path.normpath(destino))

    # Todo lo que sigue toca el disco, y tocar el disco puede fallar por
    # permisos: `/root/algo` levanta PermissionError en el mismísimo `exists()`.
    # Un instalador no puede romperse mientras alguien escribe una ruta.
    try:
        if destino.exists() and not destino.is_dir():
            return _destino_invalido(str(destino), "Ahí ya hay un archivo con ese nombre.")

        es_carpeta = destino.is_dir()
        previa = [m for m in MARCAS if (destino / m).exists()]
        existente = _primer_padre_existente(destino)
        escribible = os.access(existente, os.W_OK)
        vacia = es_carpeta and not any(destino.iterdir())
    except PermissionError:
        return _destino_invalido(
            str(destino), f"No hay permiso para acceder a {destino}."
        )
    except OSError as exc:
        return _destino_invalido(str(destino), f"No se puede usar esa carpeta: {exc}")

    problemas = []
    if not escribible:
        problemas.append(f"No hay permiso para escribir en {existente}.")

    return {
        "ruta": str(destino),
        "valida": escribible,
        "existe": es_carpeta,
        "vacia": vacia,
        "crea_carpetas": not es_carpeta,
        "instalacion_previa": previa,
        "escribible_en": str(existente),
        "problemas": problemas,
    }


def _destino_invalido(ruta: str, motivo: str) -> dict:
    return {
        "ruta": ruta,
        "valida": False,
        "existe": False,
        "vacia": False,
        "crea_carpetas": False,
        "instalacion_previa": [],
        "escribible_en": "",
        "problemas": [motivo],
    }


def _primer_padre_existente(destino: Path) -> Path:
    actual = destino
    while not actual.exists() and actual.parent != actual:
        actual = actual.parent
    return actual


# ── Paso 2: la máquina ──────────────────────────────────────────────────


@dataclass
class Chequeo:
    """
    Mismo contrato que `doctor.Check`, para que una sola pantalla los muestre.

    No se usa `doctor.run_checks()` directamente porque necesita un `Registry`,
    y acá todavía no hay instalación: estos son los chequeos que se pueden hacer
    *antes* de que exista nada.
    """

    nombre: str
    nivel: str  # ok | warn | error
    mensaje: str
    detalle: tuple[str, ...] = ()
    arreglo: str = ""

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "nivel": self.nivel,
            "mensaje": self.mensaje,
            "detalle": list(self.detalle),
            "arreglo": self.arreglo,
        }


def revisar_maquina(destino: str = "") -> list[dict]:
    """Los chequeos que no necesitan una instalación para correr."""
    return [c.to_dict() for c in (
        _chequear_python(),
        _chequear_cifrado(),
        _chequear_escritura(destino),
    )]


def _chequear_python() -> Chequeo:
    actual = sys.version_info[:3]
    texto = ".".join(map(str, actual))
    if actual < PYTHON_MINIMO:
        return Chequeo(
            "Python", "error", f"{texto} — hace falta {'.'.join(map(str, PYTHON_MINIMO))} o mayor",
            (sys.executable,), "Instalar una versión más nueva de Python.",
        )
    return Chequeo("Python", "ok", texto, (sys.executable,))


def _chequear_cifrado() -> Chequeo:
    """
    Que se pueda cifrar de verdad, no que el paquete esté en el disco.

    `import cryptography` encuentra la carpeta y no prueba nada: la primera
    versión de este chequeo daba verde en una instalación a la que le faltaba
    `_cffi_backend`, y recién reventaba al generar la llave. Un chequeo que
    aprueba una instalación rota es peor que no tenerlo, porque el error
    aparece después y lejos de la causa.

    Así que se hace el viaje completo: generar llave, cifrar y descifrar.
    """
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:  # noqa: BLE001 - ImportError, y lo que traiga abajo
        return Chequeo(
            "Cifrado", "error", "no se puede usar `cryptography`",
            (f"{type(exc).__name__}: {exc}",
             "Sin él no se pueden guardar contraseñas ni claves de API."),
            "pip install cryptography",
        )

    try:
        secreto = Fernet(Fernet.generate_key())
        if secreto.decrypt(secreto.encrypt(b"prueba")) != b"prueba":
            raise ValueError("el texto no sobrevivió el viaje")
    except Exception as exc:  # noqa: BLE001
        return Chequeo(
            "Cifrado", "error", "`cryptography` está pero no funciona",
            (f"{type(exc).__name__}: {exc}",
             "Suele ser una dependencia binaria que falta o no es de esta plataforma."),
            "Reinstalar cryptography y sus dependencias.",
        )

    import cryptography

    return Chequeo(
        "Cifrado", "ok", f"cryptography {getattr(cryptography, '__version__', '?')}",
        ("Probado cifrando y descifrando, no sólo importando.",),
    )


def _chequear_escritura(destino: str) -> Chequeo:
    """
    Que se pueda escribir de verdad, no que los permisos digan que sí.

    `os.access` miente sobre discos de red, montajes de sólo lectura y algunas
    ACL de Windows. La única forma honesta es escribir un archivo y borrarlo.
    """
    if not destino:
        return Chequeo("Escritura", "warn", "todavía no se eligió carpeta")

    carpeta = _primer_padre_existente(Path(destino))
    try:
        with tempfile.NamedTemporaryFile(dir=carpeta, prefix=".bot-prueba-"):
            pass
    except OSError as exc:
        return Chequeo(
            "Escritura", "error", f"no se pudo escribir en {carpeta}",
            (str(exc),), "Elegir otra carpeta, o dar permiso de escritura sobre ésta.",
        )
    return Chequeo("Escritura", "ok", f"{carpeta} acepta escritura")


# ── Paso 3: la caja ─────────────────────────────────────────────────────


def plan(ruta: str) -> dict:
    """
    Qué va a quedar instalado y con qué límites, sin crear nada.

    Es la pantalla que el cliente tiene que poder leer sin saber qué es un
    `fs_root`: "los flujos sólo tocan esta carpeta".
    """
    raiz = Path(os.path.normpath(Path(ruta).expanduser()))
    caja = raiz / CAJA
    datos = raiz / "data"
    plugins = raiz / PLUGINS

    return {
        "raiz": str(raiz),
        "caja": str(caja),
        "datos": str(datos),
        "plugins": str(plugins),
        "base": str(datos / "bot.db"),
        "llave": str(datos / "secret.key"),
        "boot_env": str(raiz / boot.ARCHIVO),
        "limites": [
            {
                "que": "Archivos",
                "estado": "acotado",
                "detalle": f"Los flujos sólo pueden leer y escribir dentro de {caja}.",
            },
            {
                "que": "Base y llave",
                "estado": "acotado",
                "detalle": (
                    f"Viven en {datos}, fuera de la caja. Ningún plugin las alcanza, "
                    "ni siquiera con permiso de archivos."
                ),
            },
            {
                "que": "Plugins",
                "estado": "acotado",
                "detalle": (
                    f"Viven en {plugins}, fuera de la caja. Se instalan desde la app, "
                    "y ningún flujo puede dejar código ahí."
                ),
            },
            {
                "que": "Red",
                "estado": "abierto",
                "detalle": f"Un flujo puede llamar a cualquier dirección. Timeout de {TIMEOUT:.0f}s.",
            },
            {
                "que": "Programas",
                "estado": "acotado",
                "detalle": (
                    "Ningún flujo puede ejecutar programas de la máquina. "
                    "Para habilitar alguno hay que nombrarlo en boot.env, uno por uno."
                ),
            },
            {
                "que": "Plugins",
                "estado": "acotado",
                "detalle": (
                    f"Se instalan en {plugins}, fuera de la caja: ningún flujo puede "
                    "escribir ahí ni con permiso de archivos."
                ),
            },
        ],
    }


def _config_de_arranque(raiz: Path) -> boot.BootConfig:
    """
    La config que se va a escribir.

    Dos valores llevan la instalación a lo más acotado que el núcleo permite
    expresar, y ninguno de los dos es el default:

    - `fs_root` absoluto. Relativo se resolvería contra la raíz de la
      instalación —desde el arreglo de #4—, pero escribirlo absoluto deja el
      archivo legible sin tener que saber esa regla.
    - `process_allowlist=()`. La tupla **vacía** es "ningún ejecutable"; la
      clave ausente sería "cualquiera". La diferencia existe desde #3, y es
      justamente lo que una instalación sandbox necesita decir.

    `plugins_dir` también absoluto y también deliberado: antes quedaba en
    `None` ("todavía no hay plugins"); ahora toda instalación nace con su
    carpeta de plugins, fuera de la caja, lista para `installer/source/plugins.py`.
    """
    return boot.BootConfig(
        root=raiz,
        storage="",                       # el default: <raiz>/data/bot.db
        plugins_dir=raiz / PLUGINS,       # vacía al instalar; la llena la app
        fs_root=str(raiz / CAJA),
        process_allowlist=(),             # ninguno, no "cualquiera"
        http_timeout=TIMEOUT,
        default_actor="local",
    )


# ── Paso 4: crear ───────────────────────────────────────────────────────


def instalar(ruta: str) -> dict:
    """
    Crea la instalación. Es el único paso que escribe.

    Devuelve el resumen para la última pantalla: qué se creó, qué actores
    quedaron, y dónde está la llave —que es lo único que el cliente tiene que
    recordar de todo el proceso.
    """
    from backend.core import users
    from backend.core.instance import Instance

    revision = revisar_destino(ruta)
    if not revision["valida"]:
        raise InstalacionError(" ".join(revision["problemas"]))
    if revision["instalacion_previa"]:
        marcas = ", ".join(revision["instalacion_previa"])
        raise InstalacionError(
            f"Ya hay una instalación en {revision['ruta']} ({marcas}). "
            "Elegí otra carpeta, o movéla a un lado antes de instalar."
        )

    raiz = Path(revision["ruta"])
    creado = plan(str(raiz))

    arranque = _config_de_arranque(raiz)

    try:
        raiz.mkdir(parents=True, exist_ok=True)
        (raiz / CAJA).mkdir(exist_ok=True)
        (raiz / PLUGINS).mkdir(exist_ok=True)

        # Las carpetas primero, la validación después: `validar` comprueba que
        # `fs_root` exista, y antes del mkdir todavía no existe. Y antes de
        # escribir el archivo, no después: un boot.env con un valor que no hace
        # lo que dice es peor que no tenerlo, porque parece configuración.
        if dudosos := boot.validar(arranque):
            raise InstalacionError(
                "La configuración de arranque no quedó usable:\n  " + "\n  ".join(dudosos)
            )

        # `utf-8-sig`, igual que `python -m backend.core init`: sin BOM, Notepad
        # y PowerShell 5.1 leen el archivo como cp1252 y muestran los acentos
        # rotos —se vio en la prueba en Windows—, y al guardarlo devuelven el
        # destrozo adentro. El mismo archivo no puede tener dos codificaciones
        # según quién lo haya creado.
        (raiz / boot.ARCHIVO).write_text(boot.render(arranque), encoding="utf-8-sig")
    except OSError as exc:
        raise InstalacionError(f"No se pudo crear la instalación: {exc}") from exc

    # Recién acá se abre la base. `Instance` corre las migraciones, siembra
    # `local`/`system` y deja la instalación lista.
    instancia = Instance(raiz)
    try:
        # La llave se genera perezosamente, en el primer secreto que alguien
        # guarde. Se fuerza acá para poder mostrarla ahora: que aparezca sola
        # tres semanas después, sin que nadie sepa que existe ni que hay que
        # respaldarla, es peor.
        instancia.crypto.encrypt("")
        # `agente-mcp` —el actor que usa el servidor MCP por defecto para
        # correr un flujo de verdad— no se autocrea del lado del núcleo a
        # propósito (workflow-bot-core#1): hay que darlo de alta una vez por
        # instalación. Wizard nuevo, un solo lugar donde hacerlo, para no
        # depender de que quien instala corra el comando de la CLI a mano.
        # Nace con los defaults de `kind=agent` —sin tools `dangerous`, sin
        # port `process`—; ampliarlo sigue siendo un `users allow` explícito.
        instancia.users.create("agente-mcp", kind=users.AGENT)
        actores = [u.to_dict() for u in instancia.users.list()]
        arranque = instancia.boot.to_dict()
    finally:
        instancia.close()

    # Que "Abrir Bot" sepa qué abrir sin preguntar. Si no se puede anotar (una
    # carpeta de usuario de sólo lectura) la instalación igual queda hecha: se
    # informa, no se aborta.
    anotada = None
    try:
        anotada = str(ubicacion.registrar(raiz))
    except OSError:
        pass

    return {
        "raiz": str(raiz),
        "creado": creado,
        "actores": actores,
        "arranque": arranque,
        "llave_existe": Path(creado["llave"]).is_file(),
        "sobrantes": boot.desconocidas(raiz),
        "anotada_en": anotada,
    }


# ── Después de instalar: abrir la app ───────────────────────────────────


def comando_webapp(raiz: Path, puerto: int) -> list[str]:
    """
    Cómo se arranca la webapp contra esta instalación. Separado para poder probarlo.

    `--red`: escucha en todas las interfaces, para operarla desde otra PC de la
    misma red local (el ícono de la bandeja copia la dirección). Es lo que se
    pidió para la planta; quien quiera sólo localhost la arranca a mano sin él.
    """
    return [sys.executable, "-m", "webapp", "--root", str(raiz), "--port", str(puerto), "--no-abrir", "--red"]


def abrir_webapp(ruta: str, puerto: int, espera: float = 25.0) -> dict:
    """
    Lanza la webapp contra la instalación y espera a que responda.

    Proceso aparte y suelto del instalador: el wizard se cierra después y la
    app tiene que seguir. La salida va a `<raiz>/webapp.log`, que es lo que hay
    que mirar si no levanta — y lo que se devuelve en el error.
    """
    import time
    import urllib.error
    import urllib.request

    raiz = Path(os.path.normpath(Path(ruta).expanduser()))
    if not (raiz / boot.ARCHIVO).is_file():
        raise InstalacionError(f"En {raiz} no hay una instalación (falta {boot.ARCHIVO}).")

    registro = raiz / "webapp.log"
    programa = Path(__file__).resolve().parents[2]
    extra: dict = {}
    if platform.system() == "Windows":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: sin consola propia y sin
        # morir con la del instalador.
        extra["creationflags"] = 0x00000008 | 0x00000200
    else:
        extra["start_new_session"] = True

    with registro.open("ab") as log:
        proceso = subprocess.Popen(  # noqa: S603 — comando armado acá, sin entrada del usuario
            comando_webapp(raiz, puerto), cwd=str(programa),
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extra,
        )

    url = f"http://127.0.0.1:{puerto}/"
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=1) as r:  # noqa: S310 — 127.0.0.1
                if r.status == 200:
                    return {"url": url, "pid": proceso.pid, "log": str(registro)}
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)

    try:
        cola = registro.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]
    except OSError:
        cola = []
    motivo = "terminó antes de responder" if proceso.poll() is not None else f"no respondió en {espera:.0f} s"
    raise InstalacionError(
        f"La app {motivo}. Registro en {registro}." + ("\n" + "\n".join(cola) if cola else "")
    )


class InstalacionError(Exception):
    """Algo que impide instalar, con un mensaje para mostrarle al cliente."""


__all__ = [
    "CAJA",
    "Chequeo",
    "InstalacionError",
    "escritorio",
    "instalar",
    "plan",
    "revisar_destino",
    "revisar_maquina",
    "sugerencia",
]

"""
Los límites de archivos de la instalación, editables desde la app.

Hasta ahora `fs_root`/`fs_roots` se cambiaba editando `boot.env` con un editor
de texto, y no había otra: no aparecía en ninguna pantalla. En una instalación
real eso quiere decir que sólo lo puede hacer alguien con acceso a la máquina
y ganas de leer un archivo de configuración — no quien opera el Bot, que es
justamente quien sabe en qué carpeta están los archivos de hoy.

Peor: desde el núcleo v0.3.1-beta.4 una raíz declarada que no existe **impide
arrancar** (core#22). Escribir el archivo a mano pasó de ser incómodo a ser
capaz de dejar la instalación sin levantar, con el error en una consola que
nadie mira. Por eso la validación de acá corre **antes** de escribir y no
después: si el conjunto nuevo no arranca, no se guarda.

Programas, además de archivos
-----------------------------

`process_allowlist` es el otro límite de la misma familia: no qué carpetas
alcanza un flujo, sino qué ejecutables puede correr por el port `process`.
Vive en el mismo archivo y lo hace cumplir el mismo núcleo, pero no estaba en
ninguna pantalla, así que autorizar `tasklist` en una máquina nueva era volver
al bloc de notas — y el error que ve quien opera es un `PortError` adentro de
un run, que parece un problema del flujo.

Tiene **tres** estados y el del medio es el que confunde: la clave ausente es
"cualquier ejecutable", la clave presente y vacía es "ninguno", y con nombres
es "sólo ésos". Una instalación nace en "ninguno" (el wizard lo escribe así a
propósito), así que la pantalla tiene que decir en cuál está y no dejar que
"vacío" signifique dos cosas.

Qué se puede tocar y qué no
---------------------------

Las raíces de archivos y los ejecutables permitidos. `storage`, `plugins_dir`
y `default_actor`
deciden dónde vive la base, de dónde se carga código y quién ejecuta: son de
la máquina, cambiarlos desde el navegador es otra conversación y ninguna de
las tres la pide esta pantalla. Se devuelven para mostrar, no para escribir.

Una raíz que contenga la instalación ya no se rechaza: desde core#26 el port
`fs` niega la carpeta de la instalación —la base, la llave, los plugins y el
propio `boot.env`— venga de donde venga la raíz. Antes había que prohibirla
acá, y eso obligaba a enumerar carpeta por carpeta para usar una unidad
entera.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from backend.core import boot

# El separador de alias en `boot.env`. Un alias con uno de estos caracteres
# rompe el parseo del archivo, así que se rechaza antes de escribirlo.
PROHIBIDOS_EN_ALIAS = (",", "=", ":")

# La copia que queda al lado antes de escribir, como hace `updates` con las
# carpetas: lo que se pisa es la configuración que hoy arranca.
RESPALDO = "boot.env.anterior"

# La raíz por defecto: `workspace/` de la instalación, la caja que creó el
# wizard (`installer/source/pasos.py`, CAJA). No se edita desde la pantalla.
CAJA = "workspace"
PRIMERA_POR_DEFECTO = "principal"


class LimitesError(Exception):
    """Lo que impide guardar, en castellano y con la raíz que lo causó."""

    def __init__(self, mensaje: str, detalle: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.detalle = detalle or []


def por_defecto(instance, root: Path) -> str | None:
    """
    La raíz que hoy resuelve las rutas relativas, y que esta pantalla no deja
    cambiar.

    Se toma de lo que la instalación **tiene configurado**, no de una regla:
    asumir `<root>/workspace` dejaba la pantalla inservible cuando esa carpeta
    no existe —pasó con una raíz que resolvió a la carpeta del programa—,
    porque la única fila que no se puede editar era también la que impedía
    guardar. `workspace/` es sólo el default para una instalación que todavía
    no declaró ninguna.

    `None` = esta instalación no acota nada (un flujo llega a todo el disco).
    Es un estado legítimo, y entonces no hay raíz fija: la primera que se
    agregue pasa a serlo.
    """
    actuales = getattr(instance.boot, "fs_roots_efectivos", None) or {}
    if actuales:
        return next(iter(actuales.values()))
    caja = Path(root) / CAJA
    return str(caja) if caja.is_dir() else None


def leer(instance, root: Path) -> dict:
    """Las raíces que están en efecto, más el contexto para dibujar la pantalla."""
    cfg = instance.boot
    raices = [
        {"alias": alias, "ruta": ruta, "existe": Path(ruta).is_dir()}
        for alias, ruta in (cfg.fs_roots_efectivos or {}).items()
    ]
    return {
        "raices": raices,
        # Sin ninguna raíz declarada un flujo alcanza todo el disco. Es un
        # estado legítimo —una instalación de desarrollo— y la pantalla tiene
        # que poder decirlo en vez de mostrar una lista vacía.
        "sin_limite": not raices,
        "root": str(root),
        # La que la pantalla muestra fija en la primera fila. `None` cuando la
        # instalación no acota nada: ahí no hay ninguna fija todavía.
        "por_defecto": por_defecto(instance, root),
        "data_dir": str(instance.data_dir),
        "plugins_dir": str(cfg.plugins_dir) if cfg.plugins_dir else None,
        "archivo": str(root / boot.ARCHIVO),
        # `fs_roots` es de v0.3.1-beta.3 en adelante; contra un núcleo viejo
        # la pantalla ofrece una sola raíz y lo dice.
        "varias_raices": hasattr(cfg, "fs_roots_efectivos"),
        "programas": programas(instance, root),
    }


# Los tres estados de `process_allowlist`, nombrados. La pantalla elige uno:
# un campo de texto vacío no alcanza, porque vacío y ausente son lo contrario
# entre sí.
CUALQUIERA = "cualquiera"
NINGUNO = "ninguno"
LISTA = "lista"
MODOS = (CUALQUIERA, NINGUNO, LISTA)


def _estado_de(allowlist) -> dict:
    """Uno de los tres estados, con los nombres tal como se escribieron.

    El núcleo compara por `Path(x).stem.lower()` en las dos puntas, así que
    `Toothform.exe`, `toothform` y `TOOTHFORM` son el mismo programa; se
    devuelve lo escrito tal cual, que es lo que alguien reconoce al leerlo.
    """
    if allowlist is None:
        modo = CUALQUIERA
    elif not allowlist:
        modo = NINGUNO
    else:
        modo = LISTA
    return {
        "modo": modo,
        "ejecutables": [
            {"nombre": n, "existe": shutil.which(n) is not None} for n in (allowlist or ())
        ],
    }


def programas(instance, root: Path) -> dict:
    """
    Qué ejecutables puede correr un flujo: lo que rige y lo que va a regir.

    Son dos cosas distintas y confundirlas hace que guardar parezca no haber
    hecho nada. `instance.boot` es la configuración con la que **arrancó** este
    proceso; `boot.env` es lo que va a leer el próximo. Entre guardar y
    reiniciar difieren, y la pantalla tiene que poder decirlo en vez de
    redibujarse con el valor viejo como si el guardado se hubiera perdido.
    """
    vigente = _estado_de(instance.boot.process_allowlist)
    escrito = _estado_de(boot.load(root, {}).process_allowlist)
    return {
        **vigente,
        "escrito": escrito,
        # Hay algo guardado que todavía no rige: falta reiniciar.
        "pendiente": escrito != vigente,
    }


def guardar_programas(instance, root: Path, modo: str, ejecutables: list[str]) -> dict:
    """
    Escribe `process_allowlist`. El modo es explícito, no se deduce de la lista.

    Deducirlo sería repetir la trampa del archivo: alguien borra el último
    nombre esperando "ya no hace falta la lista" y lo que queda escrito es
    "ningún programa", que es lo más restrictivo. Acá el modo se elige y la
    lista sólo importa cuando es `lista`.

    Que un ejecutable no esté en esta máquina **no** impide guardar: se avisa.
    Una instalación se puede configurar antes de instalar el programa que va a
    correr, y el núcleo lo trata igual (`boot.validar` lo reporta sin ser
    fatal).
    """
    if modo not in MODOS:
        raise LimitesError("No se pudo guardar.", [f"'{modo}' no es un modo conocido."])

    nombres: tuple[str, ...] = ()
    if modo == LISTA:
        problemas = []
        vistos: dict[str, str] = {}
        limpios = []
        for crudo in ejecutables or []:
            nombre = (crudo or "").strip()
            if not nombre:
                continue
            # La coma separa los nombres en el archivo; uno con coma adentro
            # se releería como dos, y ninguno de los dos existiría.
            if "," in nombre:
                problemas.append(f'"{nombre}": un nombre de programa no puede llevar una coma.')
                continue
            clave = Path(nombre).stem.lower()
            if clave in vistos:
                problemas.append(f'"{nombre}" y "{vistos[clave]}" son el mismo programa para el núcleo.')
                continue
            vistos[clave] = nombre
            limpios.append(nombre)
        if problemas:
            raise LimitesError("Los programas no se pueden guardar así.", problemas)
        if not limpios:
            raise LimitesError("Los programas no se pueden guardar así.", [
                'Con "sólo estos programas" hace falta al menos uno. '
                'Para no permitir ninguno, elegí esa opción.'
            ])
        nombres = tuple(limpios)

    nuevo = dataclasses.replace(
        instance.boot, process_allowlist=None if modo == CUALQUIERA else nombres
    )
    if impiden := boot.fatal(nuevo):
        raise LimitesError("Con esos programas la instalación no arrancaría.", impiden)

    escrito = _escribir(root, nuevo)
    return {"programas": programas(instance, root), **escrito}


def normalizar(raices: list[dict]) -> list[tuple[str, str]]:
    """
    De lo que manda el navegador a pares `(alias, ruta)`, con los errores de
    forma resueltos antes de tocar el disco.

    La primera raíz es la de por defecto: la que resuelve una ruta relativa.
    Puede ir sin alias —así se expresa el `fs_root` de toda la vida—, pero las
    demás lo necesitan, porque sin nombre no hay forma de referirlas.
    """
    salida: list[tuple[str, str]] = []
    vistos: set[str] = set()
    problemas: list[str] = []

    for i, cruda in enumerate(raices):
        ruta = str((cruda or {}).get("ruta") or "").strip()
        alias = str((cruda or {}).get("alias") or "").strip()
        if not ruta:
            if alias:
                problemas.append(f'La raíz "{alias}" no tiene ruta.')
            continue

        if alias:
            if any(c in alias for c in PROHIBIDOS_EN_ALIAS):
                problemas.append(
                    f'El alias "{alias}" no puede tener , = ni : — son los separadores '
                    f"del archivo de arranque."
                )
                continue
            if alias in vistos:
                problemas.append(f'El alias "{alias}" está repetido.')
                continue
            vistos.add(alias)
        elif i > 0:
            problemas.append(
                f'La raíz "{ruta}" necesita un alias: sólo la primera puede no tenerlo, '
                f"porque es la que resuelve las rutas relativas."
            )
            continue

        salida.append((alias, ruta))

    if problemas:
        raise LimitesError("Las raíces no se pueden guardar así.", problemas)
    return salida


def revisar(pares: list[tuple[str, str]], *, root: Path) -> list[str]:
    """
    Lo que hay que mirar sobre el disco, antes de escribir nada.

    Devuelve los problemas; vacío es "se puede guardar".
    """
    # Ya no se rechaza una raíz por contener la instalación: desde core#26 el
    # port `fs` niega la carpeta de la instalación —la base, la llave, los
    # plugins y el propio `boot.env`— venga de donde venga la raíz. Así una
    # unidad entera es una raíz legítima sin entregar nada de eso, que es lo
    # que obligaba a enumerar carpeta por carpeta.
    problemas: list[str] = []

    for alias, ruta in pares:
        nombre = f'"{alias}"' if alias else "la raíz por defecto"
        p = Path(ruta)

        # Sólo rutas completas. Una relativa no es un valor: `D:` o `C:` (sin
        # la barra) son "el directorio actual de esa unidad", que depende de
        # desde dónde arrancó el proceso. En una instalación real `D:` pasó
        # la validación resolviendo a una carpeta inocua, y al reiniciar
        # resolvió a la raíz de la instalación —con `plugins/` adentro— y el
        # núcleo se negó a arrancar. Y un UNC sin share es una ruta bien
        # formada que nunca va a existir, que `pathlib` también trata como
        # relativa. Cada caso con su motivo, porque el arreglo es distinto.
        if not p.is_absolute():
            if ruta.startswith("\\\\"):
                problemas.append(
                    f"{nombre}: a {ruta} le falta el nombre del recurso compartido "
                    f"(\\\\servidor\\compartido), no alcanza con el nombre del servidor."
                )
            elif len(ruta) == 2 and ruta[1] == ":":
                problemas.append(
                    f"{nombre}: {ruta} es la unidad sin la barra, y eso significa \"la carpeta "
                    f"actual de esa unidad\", que cambia según desde dónde arranque el Bot. "
                    f"Escribila con la barra ({ruta}\\) o, mejor, una carpeta puntual ({ruta}\\Casos)."
                )
            else:
                problemas.append(f"{nombre}: {ruta} no es una ruta completa (tiene que empezar por una unidad o por \\\\).")
            continue

        if not p.exists():
            problemas.append(f"{nombre}: {ruta} no existe. Hay que crearla antes.")
            continue
        if not p.is_dir():
            problemas.append(f"{nombre}: {ruta} no es una carpeta.")
            continue

        try:
            resuelta = p.resolve()
        except OSError as exc:  # una unidad de red que se cayó, un permiso
            problemas.append(f"{nombre}: no se pudo leer {ruta} ({exc.strerror or exc}).")
            continue

    return problemas


def guardar(instance, root: Path, raices: list[dict]) -> dict:
    """
    Escribe las raíces en `boot.env`. No reinicia: eso lo decide quien llama.

    El archivo se regenera entero con `boot.render`, que es lo que hace
    `python -m backend.core config`: así el archivo escrito desde la app y el
    escrito desde la consola son el mismo archivo, con los mismos comentarios.
    Lo que había queda al lado en `boot.env.anterior`.
    """
    pares = normalizar(raices)
    cfg = instance.boot

    # La raíz por defecto no se edita: es la que resuelve toda ruta relativa de
    # todo flujo, así que cambiarla no rompe una carpeta, rompe en silencio
    # todo lo escrito hasta ahí. Poder pisarla desde la pantalla es cómo una
    # instalación quedó con `principal=D:` y sin arrancar. Lo que llegue en esa
    # fila —de sólo lectura— se ignora, y lo agregado va siempre después.
    actual = por_defecto(instance, root)
    if actual is not None:
        fija = (PRIMERA_POR_DEFECTO, actual)
        # Sin alias no se conserva nada: la única raíz que puede ir sin nombre
        # es la fija, y ésa la pone esta función.
        extras = [(a, r) for a, r in pares if a and r != actual]
        if any(a == PRIMERA_POR_DEFECTO for a, _ in extras):
            # Nunca lo manda la pantalla —esa fila es de sólo lectura—, así que
            # llegó de otro lado: se dice, no se reemplaza en silencio.
            raise LimitesError("Las raíces no se pueden guardar así.", [
                f'"{PRIMERA_POR_DEFECTO}" es la raíz por defecto ({actual}) y no se cambia. '
                f"Las otras carpetas van con otro nombre, debajo."
            ])
        pares = [fija, *extras]
    elif len(pares) > 1:
        # Sin raíz previa, la primera que se agregue pasa a ser la de por
        # defecto, y desde el guardado siguiente ya no se podrá cambiar.
        pares = [(pares[0][0] or PRIMERA_POR_DEFECTO, pares[0][1]), *pares[1:]]

    if problemas := revisar(pares, root=root):
        raise LimitesError("Las raíces no se pueden guardar así.", problemas)

    # Sólo la caja: se escribe como el `fs_root` de siempre, el archivo más
    # simple para el caso más común, y una instalación que nunca necesitó
    # alias no empieza a hablar de ellos. Con más raíces, `fs_roots` con la
    # primera **nombrada**: el alias vacío se escribe `fs_roots==ruta` y un
    # núcleo anterior a v0.3.1-beta.4 descarta ese par al releer —la
    # instalación arrancaba con una raíz de menos y la segunda pasaba a
    # resolver las rutas relativas, sin un solo error—. La app y el núcleo se
    # actualizan por separado, así que no se da por sentado cuál está abajo.
    if len(pares) == 1:
        nuevo = dataclasses.replace(cfg, fs_root=pares[0][1], fs_roots=None)
    else:
        nuevo = dataclasses.replace(cfg, fs_root=None, fs_roots={a: r for a, r in pares})

    # La última red: lo que el núcleo no dejaría arrancar no se guarda. Sin
    # esto, guardar desde el navegador puede dejar la instalación sin levantar
    # y sin nadie mirando una consola.
    if impiden := boot.fatal(nuevo):
        raise LimitesError("Con esas raíces la instalación no arrancaría.", impiden)

    return {"raices": [{"alias": a, "ruta": r} for a, r in pares], **_escribir(root, nuevo)}


def _escribir(root: Path, nuevo) -> dict:
    """
    Deja el `boot.env` nuevo y la copia de lo anterior al lado.

    Lo comparten las dos mitades de la pantalla: el archivo se regenera entero
    con `boot.render` —lo mismo que hace `python -m backend.core config`—, así
    que guardar los programas no puede perder las raíces ni al revés.
    """
    archivo = root / boot.ARCHIVO
    if archivo.is_file():
        shutil.copy2(archivo, root / RESPALDO)
    # `utf-8-sig` como todo el resto: sin BOM, Notepad y PowerShell 5.1 leen el
    # archivo como cp1252 y devuelven los acentos rotos adentro.
    archivo.write_text(boot.render(nuevo), encoding="utf-8-sig")

    return {
        "archivo": str(archivo),
        "respaldo": str(root / RESPALDO),
        # Se lee al construir la instancia: hasta que no reinicie, el Bot sigue
        # con lo de antes, y decirlo es la mitad de la pantalla.
        "restart_required": True,
        "avisos": boot.validar(nuevo),
    }

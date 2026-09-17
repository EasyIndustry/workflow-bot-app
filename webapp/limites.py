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

Qué se puede tocar y qué no
---------------------------

Sólo las raíces de archivos. `storage`, `plugins_dir` y `default_actor`
deciden dónde vive la base, de dónde se carga código y quién ejecuta: son de
la máquina, cambiarlos desde el navegador es otra conversación y ninguna de
las tres la pide esta pantalla. Se devuelven para mostrar, no para escribir.

Lo que esta capa garantiza, y el núcleo no puede garantizar solo, es que una
raíz nueva no se trague `data/` ni `plugins/`. El núcleo ya rechaza el
solapamiento con `plugins_dir`, pero `data/` —la base y la llave de cifrado—
no es un valor declarado en `boot.env` cuando se usa el default, así que el
chequeo tiene que estar acá.
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

# El nombre que se le pone a la raíz por defecto cuando hay varias y quien la
# cargó no le puso ninguno. Ver el comentario en `guardar`.
PRIMERA_POR_DEFECTO = "principal"


class LimitesError(Exception):
    """Lo que impide guardar, en castellano y con la raíz que lo causó."""

    def __init__(self, mensaje: str, detalle: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.detalle = detalle or []


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
        "data_dir": str(instance.data_dir),
        "plugins_dir": str(cfg.plugins_dir) if cfg.plugins_dir else None,
        "archivo": str(root / boot.ARCHIVO),
        # `fs_roots` es de v0.3.1-beta.3 en adelante; contra un núcleo viejo
        # la pantalla ofrece una sola raíz y lo dice.
        "varias_raices": hasattr(cfg, "fs_roots_efectivos"),
    }


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


def revisar(pares: list[tuple[str, str]], *, root: Path, data_dir: Path,
            plugins_dir: Path | None) -> list[str]:
    """
    Lo que hay que mirar sobre el disco, antes de escribir nada.

    Devuelve los problemas; vacío es "se puede guardar".
    """
    problemas: list[str] = []
    protegidas = [("la base y la llave", Path(data_dir))]
    if plugins_dir:
        protegidas.append(("los plugins", Path(plugins_dir)))

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

        for que, protegida in protegidas:
            try:
                prot = protegida.resolve()
            except OSError:
                continue
            if prot == resuelta or prot.is_relative_to(resuelta):
                # Con la salida escrita: quien pone `D:\` quiere llegar a
                # carpetas de esa unidad, y lo que hace falta decirle es que
                # eso se consigue nombrándolas. Sin esto, la vuelta fue probar
                # `D:` sin la barra, que pasaba y dejaba la instalación sin
                # arrancar.
                problemas.append(
                    f"{nombre}: {ruta} contiene {que} ({prot}), así que no puede ser una raíz: "
                    f"un flujo con permiso de archivos las alcanzaría. Para llegar a otras carpetas "
                    f"de esa unidad, agregá cada una por su ruta (por ejemplo {resuelta.drive}\\Casos), "
                    f"no la unidad entera."
                )

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

    if problemas := revisar(pares, root=root, data_dir=Path(instance.data_dir),
                            plugins_dir=Path(cfg.plugins_dir) if cfg.plugins_dir else None):
        raise LimitesError("Las raíces no se pueden guardar así.", problemas)

    # Una sola raíz sin alias se escribe como el `fs_root` de siempre: el
    # archivo más simple posible para el caso más común, y una instalación que
    # nunca necesitó alias no empieza a hablar de ellos.
    if len(pares) == 1 and not pares[0][0]:
        nuevo = dataclasses.replace(cfg, fs_root=pares[0][1], fs_roots=None)
    elif not pares:
        nuevo = dataclasses.replace(cfg, fs_root=None, fs_roots=None)
    else:
        # Con varias raíces, la primera se guarda **con nombre** aunque quien
        # la cargó no le haya puesto uno. El alias vacío se escribe como
        # `fs_roots==ruta`, y un núcleo anterior a v0.3.1-beta.4 descarta ese
        # par al releer: la instalación arrancaba con una raíz de menos y la
        # segunda pasaba a resolver las rutas relativas, sin un solo error. La
        # app y el núcleo se actualizan por separado, así que no se puede dar
        # por sentado cuál está abajo. Nombrarla no cambia nada para los
        # flujos —la primera resuelve las rutas relativas se llame como se
        # llame— y saca al archivo de esa dependencia.
        alias_primero = pares[0][0] or PRIMERA_POR_DEFECTO
        pares = [(alias_primero, pares[0][1]), *pares[1:]]
        nuevo = dataclasses.replace(cfg, fs_root=None, fs_roots={a: r for a, r in pares})

    # La última red: lo que el núcleo no dejaría arrancar no se guarda. Sin
    # esto, guardar desde el navegador puede dejar la instalación sin levantar
    # y sin nadie mirando una consola.
    if impiden := boot.fatal(nuevo):
        raise LimitesError("Con esas raíces la instalación no arrancaría.", impiden)

    archivo = root / boot.ARCHIVO
    if archivo.is_file():
        shutil.copy2(archivo, root / RESPALDO)
    # `utf-8-sig` como todo el resto: sin BOM, Notepad y PowerShell 5.1 leen el
    # archivo como cp1252 y devuelven los acentos rotos adentro.
    archivo.write_text(boot.render(nuevo), encoding="utf-8-sig")

    return {
        "raices": [{"alias": a, "ruta": r} for a, r in pares],
        "archivo": str(archivo),
        "respaldo": str(root / RESPALDO),
        # Se lee al construir la instancia: hasta que no reinicie, el Bot sigue
        # con las raíces viejas, y decirlo es la mitad de la pantalla.
        "restart_required": True,
        "avisos": boot.validar(nuevo),
    }

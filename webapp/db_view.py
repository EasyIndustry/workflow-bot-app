"""
El visor de la base: sólo lectura, tabla por tabla, de a páginas.

Es de la webapp y no del núcleo porque es una forma de *mirar* lo que el núcleo
guarda, no una regla de cómo se guarda. Habla con el `StoragePort` de la
instancia, igual que los stores, y no abre la base por su cuenta: hay una sola
conexión y una sola política de quién escribe.

Dos cosas que este módulo garantiza y la UI no tiene que volver a pensar:

1. **Nunca devuelve un secreto.** La tabla `env` guarda cifrados los que tienen
   `secret=1`, así que ahí igual se vería ruido; pero `settings` y
   `plugin_items` guardan en claro lo que un plugin declaró como `secret`
   (`Setting.secret`, `Field.secret`). Se tapan los tres casos mirando qué
   declaran los manifests, y la fila sale con `"•••"` en su lugar. Un token
   que ya cuesta ocultar en la pantalla de su plugin no puede aparecer en el
   visor genérico de al lado.

2. **Sólo las tablas del esquema.** No se lista lo que diga el motor sino lo
   que declara `core/schema.py`: si el día de mañana la base tiene una tabla
   que el núcleo no conoce, este visor tampoco.

Límite conocido: las columnas se piden con `PRAGMA table_info`, que es de
SQLite. El `StoragePort` abstrae la conexión y no el dialecto (lo dice su
propio docstring), y los stores del núcleo ya escriben SQL de SQLite; esto no
agrega una atadura nueva, pero sí es un lugar más a revisar si algún día se
porta el motor.
"""

from __future__ import annotations

import json
from typing import Any

from backend.core.schema import SCHEMA

TAPADO = "•••"
LIMITE_MAXIMO = 500


class TablaDesconocida(LookupError):
    pass


def tablas(db) -> list[dict]:
    """Cada tabla del esquema con su conteo. `None` si la cuenta falló."""
    salida = []
    for nombre in SCHEMA:
        try:
            fila = db.one(f"SELECT COUNT(*) AS n FROM {nombre}")  # noqa: S608 — nombre del esquema, no del usuario
            n = fila["n"] if fila else 0
        except Exception:
            n = None
        salida.append({"name": nombre, "count": n, "version": SCHEMA[nombre]})
    return salida


def columnas(db, tabla: str) -> list[str]:
    _validar(tabla)
    return [c["name"] for c in db.query(f"PRAGMA table_info({tabla})")]


def filas(db, registry, tabla: str, *, limit: int = 50, offset: int = 0) -> dict:
    """
    Una página, de la más nueva a la más vieja. `rowid DESC` y no una columna:
    ninguna tabla del esquema es `WITHOUT ROWID`, y `runs` tiene `run_id TEXT`
    como clave en vez de un `id` entero, así que el rowid implícito es lo único
    que todas comparten y que crece en el orden en que se insertó.
    """
    _validar(tabla)
    limit = max(1, min(int(limit), LIMITE_MAXIMO))
    offset = max(0, int(offset))
    total_fila = db.one(f"SELECT COUNT(*) AS n FROM {tabla}")  # noqa: S608
    total = total_fila["n"] if total_fila else 0
    crudas = db.query(
        f"SELECT * FROM {tabla} ORDER BY rowid DESC LIMIT ? OFFSET ?",  # noqa: S608
        (limit, offset),
    )
    tapar = _tapador(registry, tabla)
    return {
        "table": tabla,
        "columns": columnas(db, tabla),
        "rows": [tapar(dict(f)) for f in crudas],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── Redacción ───────────────────────────────────────────────────────────


def _tapador(registry, tabla: str):
    if tabla == "env":
        def tapar(fila: dict) -> dict:
            if fila.get("secret"):
                fila["value"] = TAPADO
            return fila
        return tapar

    if tabla == "settings":
        secretas = _settings_secretos(registry)

        def tapar(fila: dict) -> dict:
            if fila.get("key") in secretas:
                fila["value"] = TAPADO
            return fila
        return tapar

    if tabla == "plugin_items":
        secretos = _campos_secretos(registry)

        def tapar(fila: dict) -> dict:
            claves = secretos.get((fila.get("plugin"), fila.get("resource")))
            if not claves:
                return fila
            try:
                data = json.loads(fila.get("data") or "{}")
            except (TypeError, ValueError):
                # Un JSON roto no se puede tapar campo por campo: se tapa entero
                # antes que arriesgar mostrar un token a medias.
                fila["data"] = TAPADO
                return fila
            if isinstance(data, dict):
                for clave in claves:
                    if clave in data:
                        data[clave] = TAPADO
                fila["data"] = json.dumps(data, ensure_ascii=False)
            return fila
        return tapar

    return lambda fila: fila


def _manifests(registry):
    for plugin in getattr(registry, "plugins", []):
        manifest = getattr(plugin, "manifest", None)
        if manifest is not None:
            yield manifest


def _settings_secretos(registry) -> set[str]:
    claves: set[str] = set()
    for manifest in _manifests(registry):
        for s in getattr(manifest, "settings", ()):
            if getattr(s, "secret", False):
                claves.add(s.key)
    return claves


def _campos_secretos(registry) -> dict[tuple[str, str], set[str]]:
    salida: dict[tuple[str, str], set[str]] = {}
    for manifest in _manifests(registry):
        for r in getattr(manifest, "resources", ()):
            campos = {f.name for f in getattr(r, "fields", ()) if getattr(f, "secret", False)}
            if campos:
                salida[(manifest.name, r.name)] = campos
    return salida


def _validar(tabla: Any) -> None:
    if tabla not in SCHEMA:
        raise TablaDesconocida(f'No hay ninguna tabla "{tabla}" en el esquema del núcleo')

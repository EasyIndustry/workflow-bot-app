"""
El manual agéntico de una instalación: lo que un agente lee antes de tocar nada.

Un agente conectado por MCP a una instalación no sabe qué es esto ni por dónde
empezar cuando la orden es ambigua ("fijate por qué falla la fila QATF001").
Este módulo arma dos cosas para eso, y las dos salen de la instalación misma,
nunca de un texto escrito a mano que se desactualice:

- **`describir(instance)`**: la foto viva. El núcleo ya arma casi toda
  (`Instance.describe_installation`, workflow-bot-core#17: flujos, plugins,
  actores, boot, runs); acá se le suma lo que sólo la webapp conoce —las
  **fuentes** de `connections` y las **notas** de `conocimiento`— y se
  extiende el `resumen`. Es lo que devuelve la tool `describe_installation`
  del MCP de la instalación (`webapp/mcp_servidor.py`).
- **`agents_md(...)`**: el texto de `AGENTS.md` que se deja en la carpeta de
  la instalación, y que los CLIs leen **antes** de cualquier llamada. Es
  corto a propósito: dice qué es esto, las reglas, y "empezá por
  `describe_installation`". La descripción larga no va en el archivo porque
  quedaría vieja al primer plugin instalado; el archivo es el disparador y
  el MCP es el contenido.

Se regenera al arrancar el servidor y cada vez que cambia lo que describe
(un flujo guardado o borrado, un plugin instalado, una colección tocada):
ver `regenerar` y sus llamadas en `routes/core_api.py` y `mcp_servidor.py`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVO = "AGENTS.md"
# Claude Code lee CLAUDE.md, no AGENTS.md; un `@AGENTS.md` lo importa entero.
# Así el contenido está una sola vez y los tres CLIs leen lo mismo.
PUNTERO_CLAUDE = "CLAUDE.md"


# ── La foto viva ────────────────────────────────────────────────────────


def describir(instance) -> dict:
    """
    `Instance.describe_installation()` más lo que sólo esta app conoce.

    Nada de secretos: las colecciones salen enmascaradas
    (`resource_items_masked`) y de las fuentes sólo viaja lo que hace falta
    para nombrarlas —nunca headers ni payload—. Cada agregado se arma por
    separado y uno que falle no tira el resto.
    """
    d = instance.describe_installation()
    d["fuentes"] = _fuentes(instance)
    d["notas"] = _notas(instance)
    d["resumen"] = resumen(d)
    return d


def _fuentes(instance) -> list[dict]:
    try:
        items = instance.resource_items_masked("connections", "sources")
    except Exception as exc:  # noqa: BLE001 — una sección rota no vacía el resto
        return [{"error": str(exc)}]
    return [
        {
            "name": it.get("name"),
            "kind": it.get("kind") or "http",
            "key_field": it.get("key_field"),
            "default_flow": it.get("default_flow") or None,
            "url": it.get("url"),
        }
        for it in items
    ]


def _notas(instance) -> list[dict]:
    try:
        items = instance.resource_items_masked("conocimiento", "notas")
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]
    return [{"tema": it.get("tema"), "texto": it.get("texto"), "origen": it.get("origen") or "persona"} for it in items]


def resumen(d: dict) -> str:
    """El resumen del núcleo, más las fuentes con su clave, los flujos con su descripción y las notas por tema."""
    lineas = [d.get("resumen") or ""]
    fuentes = [f for f in d.get("fuentes") or [] if "error" not in f]
    if fuentes:
        lineas.append("Fuentes: " + "; ".join(
            f"{f['name']} (clave {f['key_field']}" + (f", flujo por defecto {f['default_flow']})" if f["default_flow"] else ")")
            for f in fuentes) + ".")
    else:
        lineas.append("Fuentes: ninguna todavía.")
    flujos = d.get("flows") or []
    if flujos:
        lineas.append("Flujos: " + "; ".join(
            f["name"] + (f" — {f['description']}" if f.get("description") else "")
            + ("" if f.get("enabled", True) else " [deshabilitado]")
            for f in flujos) + ".")
    notas = [n for n in d.get("notas") or [] if "error" not in n]
    lineas.append(
        f"Notas de conocimiento: {len(notas)}" + (" — " + ", ".join(n["tema"] for n in notas[:8]) + "." if notas else ".")
    )
    return "\n".join(linea for linea in lineas if linea)


# ── AGENTS.md ───────────────────────────────────────────────────────────


def agents_md(descripcion: dict, *, url_app: str | None = None) -> str:
    """
    El texto del AGENTS.md. Corto: qué es, dónde está cada cosa, las reglas y
    por dónde empezar. Lo vivo va en el resumen, y el detalle se pide por MCP
    en el momento, que es lo único que no envejece.
    """
    root = (descripcion.get("boot") or {}).get("root") or ""
    fecha = time.strftime("%Y-%m-%d %H:%M")
    app = f" La misma instalación se opera desde el navegador en {url_app}." if url_app else ""
    return f"""# Bot — instalación en `{root}`

Este archivo lo genera la app (`webapp/contexto_agente.py`) cada vez que arranca o cambia algo; no lo edites a mano, se pisa. Generado el {fecha}.

## Qué es esto

Un bot que procesa **filas de una fuente de datos** (una API) una por una, siguiendo un **flujo** escrito en Mermaid. Cada nodo del flujo es un **tool** de un **plugin**; cada ejecución (**run**) deja traza por nodo y un **log por fila** (`case_id`). Lo opera una persona desde el navegador; vos entrás por el servidor MCP `bot`, que ya apunta a esta instalación.{app}

## Empezá siempre por acá

1. **`describe_installation`** (MCP): fuentes, flujos, plugins, actores, límites, runs recientes y las notas que dejó quien opera. Leelo antes de decidir nada; una orden ambigua casi siempre se aclara con eso.
2. Si la pregunta es "por qué falló": `list_runs` (filtrable por `case_id`, `source`, `only_failed`) → `get_run` (traza por nodo con params resueltos) → `get_case_log` (la historia entera de esa fila).
3. Si hay que mirar datos de una fuente: `preview_source` con el nombre de la fuente. **Nunca abras `data/bot.db` ni leas `data/secret.key`**: los datos se consultan por MCP, que enmascara secretos.
4. Si hay que escribir o arreglar un flujo: `list_tools` → escribir el `.mmd` → `check_flow` → `dry_run_flow` → `save_flow`. Un plugin nuevo: `plugin_template` → `load_plugin` → `install_plugin`.
5. Lo que aprendas de esta instalación y no esté en ningún lado (qué significa un estado, quién corre qué), dejalo como nota: `write_resource_item` con `plugin=conocimiento`, `resource=notas`, `key=<tema>` e `item={{tema, texto, origen: "agente"}}`.

## Reglas

- **`dry_run_flow` antes de `run_flow`**, siempre. `run_flow` ejecuta de verdad sobre esta instalación: preguntá antes salvo que te lo hayan pedido explícitamente para una fila concreta.
- Los secretos viven en Config → Variables y se referencian como `{{env.CLAVE}}`; nunca pidas ni pegues un valor en claro en un flujo, una nota o una colección.
- Los plugins son genéricos, con nombre de herramienta y nunca de un cliente ni de un sistema externo. Una llamada HTTP guardada es una Action de `connections`, no un plugin.
- Un flujo con el port `fs` sólo alcanza `workspace/` (`fs_root`); `data/` y `plugins/` quedan afuera a propósito.
- Respondé en castellano, como está escrito todo acá.

## Dónde está cada cosa

| Carpeta | Qué hay |
|---|---|
| `boot.env` | límites de la instalación: `fs_root`, `process_allowlist`, timeouts, actor por defecto |
| `data/` | la base (`bot.db`) y la llave. **No se toca**: se consulta por MCP |
| `plugins/` | los plugins instalados, uno por carpeta |
| `workspace/` | lo único que un flujo puede leer y escribir con `fs` |

## La instalación hoy

{descripcion.get('resumen') or ''}
"""


def escribir(instance, root: Path, *, url_app: str | None = None) -> Path:
    """Deja `AGENTS.md` (y el puntero `CLAUDE.md`) en la raíz de la instalación."""
    root = Path(root)
    texto = agents_md(describir(instance), url_app=url_app)
    destino = root / ARCHIVO
    destino.write_text(texto, encoding="utf-8")
    puntero = root / PUNTERO_CLAUDE
    # Sólo si no hay un CLAUDE.md propio: el puntero es nuestro, uno escrito a
    # mano por quien opera no se pisa.
    if not puntero.exists() or puntero.read_text(encoding="utf-8").strip() == f"@{ARCHIVO}":
        puntero.write_text(f"@{ARCHIVO}\n", encoding="utf-8")
    return destino


def regenerar(instance, root: Path, *, url_app: str | None = None) -> None:
    """`escribir` sin que un fallo tumbe a quien lo llama: el manual es un extra, no el servicio."""
    try:
        escribir(instance, root, url_app=url_app)
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo regenerar %s en %s: %s", ARCHIVO, root, exc)


__all__ = ["ARCHIVO", "agents_md", "describir", "escribir", "regenerar", "resumen"]

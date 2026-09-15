"""
Registra el server MCP de esta instalación en el cliente del proveedor que se
acaba de instalar/loguear, para que nadie tenga que copiar a mano el bloque
que muestra la pestaña Agente.

Sólo dos proveedores tienen un archivo de configuración documentado que este
módulo pueda escribir de forma segura —mergeando, nunca pisando el resto del
archivo—: Claude Code (`.mcp.json`, JSON) y Codex CLI (`.codex/config.toml`,
TOML). Los dos quedan **project-scoped**, en la raíz de esta instalación, y no
en la carpeta home de quien lo usa: tocar `~/.codex/config.toml` pisaría la
configuración de MCP de *todos* los proyectos donde esa persona use Codex, no
sólo éste. Confirmado contra la doc de OpenAI que Codex también lee un
`.codex/config.toml` de proyecto si confía en la carpeta — es el mismo trato
que ya recibe `.mcp.json` de Claude Code.

Antigravity CLI no tiene un archivo de config documentado para tocar a mano;
en cambio expone `agy mcp add` (confirmado con `agy mcp add --help`), así que
se corre ese comando en vez de adiventar un formato no documentado.

`tomli_w` escribe el TOML de nuevo desde el dict entero: pierde comentarios y
el orden/formato exacto de un `.codex/config.toml` escrito a mano, pero
preserva cada tabla y valor que ya hubiera — el mismo trade-off que ya acepta
`json.dumps` para `.mcp.json`. Preferible a un regex sobre el texto crudo, que
sería más frágil todavía.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import tomli_w


def _mcp_json(ruta: Path, conexion: dict) -> str:
    datos: dict = {}
    if ruta.is_file():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            datos = {}
    if not isinstance(datos, dict):
        datos = {}
    datos.setdefault("mcpServers", {})
    datos["mcpServers"]["bot"] = conexion
    ruta.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    return f"✓ Registrado en {ruta.name}"


def _codex_toml(ruta: Path, conexion: dict) -> str:
    datos: dict = {}
    if ruta.is_file():
        try:
            datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            datos = {}
    datos.setdefault("mcp_servers", {})
    datos["mcp_servers"]["bot"] = {
        "command": conexion["command"],
        "args": list(conexion["args"]),
        "cwd": conexion["cwd"],
        # `env` además de `cwd`, por lo mismo que en `.mcp.json`: no todos los
        # clientes respetan `cwd`, y sin PYTHONPATH `backend` no se importa.
        "env": dict(conexion.get("env") or {}),
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(tomli_w.dumps(datos).encode("utf-8"))
    return "✓ Registrado en .codex/config.toml"


def _antigravity(conexion: dict) -> str:
    entorno = conexion.get("env") or {"PYTHONPATH": conexion["cwd"]}
    comando = ["agy", "mcp", "add"]
    for clave, valor in entorno.items():
        comando += ["--env", f"{clave}={valor}"]
    comando += ["bot", conexion["command"], *conexion["args"]]
    try:
        resultado = subprocess.run(  # noqa: S603 — argv fijo, nunca shell=True
            comando, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"⚠ No se pudo registrar en Antigravity: {exc}"
    if resultado.returncode != 0:
        detalle = (resultado.stderr or resultado.stdout or "").strip()[:200]
        return f"⚠ 'agy mcp add' devolvió un error: {detalle}"
    return "✓ Registrado en Antigravity (agy mcp add)"


_REGISTRADORES = {
    "claude-code": lambda root, conexion: _mcp_json(root / ".mcp.json", conexion),
    "codex": lambda root, conexion: _codex_toml(root / ".codex" / "config.toml", conexion),
    "antigravity": lambda root, conexion: _antigravity(conexion),
}


def registrar(provider_id: str, root: Path, conexion: dict) -> str | None:
    """
    Auto-registra la conexión MCP para el proveedor que se acaba de instalar o
    loguear. Devuelve un aviso corto para mostrar en la terminal, o `None` si
    ese proveedor no tiene (todavía) un registro automático — hoy, "manual".
    """
    fn = _REGISTRADORES.get(provider_id)
    if fn is None:
        return None
    try:
        return fn(root, conexion)
    except OSError as exc:
        return f"⚠ No se pudo escribir la configuración de {provider_id}: {exc}"


__all__ = ["registrar"]

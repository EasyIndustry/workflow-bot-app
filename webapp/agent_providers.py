"""
Proveedores de CLI conocidos, para el wizard de la pestaña Agente.

Tabla chica y editable a mano: no hay forma de descubrir "qué CLIs de agentes
existen" de manera genérica, así que en vez de fingir una extensibilidad que
no existe, se declara la lista de memoria. Sumar uno nuevo es una entrada acá,
nada más — ningún otro archivo necesita saber que existe.

Cada proveedor declara su propio comando de instalación, corrido tal cual
—nunca `shell=True`— y sin sudo ni admin: instala en el prefijo de npm del
usuario. Si ese prefijo no existe o no tiene permiso de escritura, el error de
npm sale tal cual en la terminal embebida — no se intenta adivinar ni arreglar
la configuración de npm de quien lo usa. La responsabilidad de esta app
termina en "corrí el comando oficial del vendor y te muestro lo que dijo".
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Proveedor:
    id: str
    label: str
    binario: str  # lo que se busca con shutil.which para saber si ya está
    instalar: tuple[str, ...]  # argv, nunca una línea de shell
    login: tuple[str, ...]
    doc: str = ""
    # Cómo pegar la conexión a mano si `auto_registro` no alcanza (otra
    # máquina, un cliente que no es éste): "json" (`.mcp.json`), "toml"
    # (`.codex/config.toml`) o "" si no hay un bloque propio que mostrar
    # (Antigravity sólo sabe `agy mcp add`; Manual todavía no tiene nada).
    formato_config: str = "json"
    # Si `mcp_registration.registrar` sabe escribir la conexión sola para
    # este proveedor apenas termina un install/login exitoso — ver ese módulo.
    auto_registro: bool = False


def _instalar_antigravity() -> tuple[str, ...]:
    """
    Antigravity CLI (`agy`) no se instala por npm: Google la reemplazó por un
    binario Go propio, instalado con el instalador oficial de cada SO —no hay
    paquete en ningún gestor. En Windows eso es un one-liner de PowerShell; acá
    el argv lo invoca explícito (`powershell -Command "..."`) en vez de dejar
    que `shell=True` intente correrlo con cmd.exe, que no entiende `irm`/`iex`.
    """
    if os.name == "nt":
        return (
            "powershell", "-NoProfile", "-Command",
            "irm https://antigravity.google/cli/install.ps1 | iex",
        )
    return ("bash", "-lc", "curl -fsSL https://antigravity.google/cli/install.sh | bash")


# Claude Code y Codex corren por npm. Antigravity no —ver `_instalar_antigravity`—
# pero el resto de la tabla no necesita saberlo: `instalar` sigue siendo "el
# argv que hay que correr", sea cual sea el gestor detrás.
PROVEEDORES: tuple[Proveedor, ...] = (
    Proveedor(
        id="claude-code",
        label="Claude Code",
        binario="claude",
        instalar=("npm", "install", "-g", "@anthropic-ai/claude-code"),
        login=("claude",),
        doc="CLI oficial de Anthropic. Al loguearse abre un navegador para autorizar la cuenta.",
        formato_config="json",
        auto_registro=True,
    ),
    Proveedor(
        id="codex",
        label="Codex CLI",
        binario="codex",
        instalar=("npm", "install", "-g", "@openai/codex"),
        login=("codex",),
        doc="CLI oficial de OpenAI.",
        formato_config="toml",
        auto_registro=True,
    ),
    Proveedor(
        id="antigravity",
        label="Antigravity CLI (agy)",
        binario="agy",
        instalar=_instalar_antigravity(),
        login=("agy",),
        doc=(
            "CLI oficial de Google — reemplazó a Gemini CLI (retirada en 2026). "
            "Al correrla por primera vez pide loguearse con Google Sign-In."
        ),
        formato_config="",  # no hay archivo de config documentado — sólo `agy mcp add`
        auto_registro=True,
    ),
    Proveedor(
        id="manual",
        label="Manual / otro",
        binario="",
        instalar=(),
        login=(),
        doc=(
            "Sin automatización todavía — pensado para un cliente MCP que no está en "
            "esta lista, o para IA local (Ollama, etc.) más adelante. Pegá el bloque JSON "
            "a mano en lo que sea que uses."
        ),
        formato_config="json",
        auto_registro=False,
    ),
)


def proveedor(id_: str) -> Proveedor | None:
    return next((p for p in PROVEEDORES if p.id == id_), None)


def estado() -> list[dict]:
    """Cada proveedor conocido, con si ya está instalado en esta máquina."""
    salida = []
    for p in PROVEEDORES:
        salida.append({
            "id": p.id,
            "label": p.label,
            "doc": p.doc,
            "instalado": bool(p.binario) and shutil.which(p.binario) is not None,
            # No todos instalan igual (npm para Claude Code/Codex, PowerShell/
            # bash para Antigravity): lo que hace falta es que el primer
            # comando de `instalar` exista en el PATH, sea cual sea. Sin eso
            # ni el proveedor se puede instalar ni ofrece nada útil — se lo
            # dice así, en vez de un botón que va a fallar apenas se lo apriete.
            "se_puede_instalar": bool(p.instalar) and shutil.which(p.instalar[0]) is not None,
            # "Manual" no tiene ni instalar ni login: no hay proceso que correr
            # en la terminal, así que la UI no ofrece esos botones para él.
            "automatizable": bool(p.instalar) or bool(p.login),
            "formato_config": p.formato_config,
            "auto_registro": p.auto_registro,
        })
    return salida


__all__ = ["PROVEEDORES", "Proveedor", "estado", "proveedor"]

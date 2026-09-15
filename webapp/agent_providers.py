"""
Proveedores de CLI conocidos, para el wizard de la pestaña Agente.

Tabla chica y editable a mano: no hay forma de descubrir "qué CLIs de agentes
existen" de manera genérica, así que en vez de fingir una extensibilidad que
no existe, se declara la lista de memoria. Sumar uno nuevo es una entrada acá,
nada más — ningún otro archivo necesita saber que existe.

Cada proveedor declara su propio comando de instalación, corrido tal cual
—nunca `shell=True`— y sin sudo ni admin. Los tres usan el **instalador
nativo del vendor** (un script de PowerShell en Windows, `curl | sh` en el
resto): bajan un binario y lo dejan en la carpeta del usuario. Antes Claude
Code y Codex iban por `npm install -g`, y en una PC de planta sin Node el
botón "Instalar" no tenía con qué; y el instalador de Node, con sus
"herramientas para módulos nativos", arrastra Python y Visual Studio Build
Tools que nadie pidió. Los binarios nativos no dependen de Node en absoluto.

Lo que el instalador del vendor deja en el PATH del usuario lo ve una consola
nueva, no este servidor que ya estaba corriendo: por eso cada proveedor
declara también dónde suele quedar el binario (`rutas_probables`), y tanto
"instalado" como el comando de login lo buscan ahí además del PATH. Si el
vendor cambia la carpeta, se corrige acá.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


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
    # Dónde deja el binario el instalador nativo, con variables de entorno
    # sin expandir. Se mira cuando el PATH de este proceso todavía no lo tiene.
    rutas_probables: tuple[str, ...] = ()


def _powershell(script: str) -> tuple[str, ...]:
    """
    El one-liner oficial del vendor, invocado explícito. `-ExecutionPolicy
    Bypass` porque una PC de planta suele tener la política Restricted y sin
    eso `iex` de un script bajado no corre; alcanza a este proceso, no cambia
    la política de la máquina. Sin `shell=True`: cmd.exe no entiende `irm`.
    """
    return ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)


def _bash(script: str) -> tuple[str, ...]:
    return ("bash", "-lc", script)


def _instalar(windows: str, posix: str) -> tuple[str, ...]:
    return _powershell(windows) if os.name == "nt" else _bash(posix)


PROVEEDORES: tuple[Proveedor, ...] = (
    Proveedor(
        id="claude-code",
        label="Claude Code",
        binario="claude",
        instalar=_instalar(
            "irm https://claude.ai/install.ps1 | iex",
            "curl -fsSL https://claude.ai/install.sh | bash",
        ),
        login=("claude",),
        doc=(
            "CLI oficial de Anthropic, instalada con su instalador nativo (sin Node). "
            "Al loguearse abre un navegador para autorizar la cuenta."
        ),
        formato_config="json",
        auto_registro=True,
        rutas_probables=(r"%USERPROFILE%\.local\bin\claude.exe", "~/.local/bin/claude"),
    ),
    Proveedor(
        id="codex",
        label="Codex CLI",
        binario="codex",
        instalar=_instalar(
            "irm https://chatgpt.com/codex/install.ps1 | iex",
            "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
        ),
        login=("codex",),
        doc="CLI oficial de OpenAI, instalada con su instalador nativo (sin Node).",
        formato_config="toml",
        auto_registro=True,
        rutas_probables=(
            r"%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe",
            "~/.codex/bin/codex", "~/.local/bin/codex",
        ),
    ),
    Proveedor(
        id="antigravity",
        label="Antigravity CLI (agy)",
        binario="agy",
        instalar=_instalar(
            "irm https://antigravity.google/cli/install.ps1 | iex",
            "curl -fsSL https://antigravity.google/cli/install.sh | bash",
        ),
        login=("agy",),
        doc=(
            "CLI oficial de Google — reemplazó a Gemini CLI (retirada en 2026). "
            "Al correrla por primera vez pide loguearse con Google Sign-In."
        ),
        formato_config="",  # no hay archivo de config documentado — sólo `agy mcp add`
        auto_registro=True,
        rutas_probables=(r"%LOCALAPPDATA%\agy\bin\agy.exe", "~/.agy/bin/agy", "~/.local/bin/agy"),
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


def ruta_del_binario(p: Proveedor) -> str | None:
    """
    Dónde está el CLI: en el PATH de este proceso o en la carpeta donde lo
    deja su instalador. None si no está en ningún lado.
    """
    if not p.binario:
        return None
    en_path = shutil.which(p.binario)
    if en_path:
        return en_path
    for cruda in p.rutas_probables:
        ruta = Path(os.path.expandvars(os.path.expanduser(cruda)))
        if ruta.is_file():
            return str(ruta)
    return None


def comando_login(p: Proveedor) -> tuple[str, ...]:
    """El argv de login con el binario resuelto: recién instalado, el PATH de acá todavía no lo tiene."""
    if not p.login:
        return ()
    ruta = ruta_del_binario(p)
    return (ruta, *p.login[1:]) if ruta and p.login[0] == p.binario else p.login


def estado() -> list[dict]:
    """Cada proveedor conocido, con si ya está instalado en esta máquina."""
    salida = []
    for p in PROVEEDORES:
        salida.append({
            "id": p.id,
            "label": p.label,
            "doc": p.doc,
            "instalado": ruta_del_binario(p) is not None,
            # Lo que hace falta es que el primer comando de `instalar` exista
            # (powershell en Windows, bash en el resto). Sin eso ni el proveedor
            # se puede instalar ni ofrece nada útil — se lo dice así, en vez de
            # un botón que va a fallar apenas se lo apriete.
            "se_puede_instalar": bool(p.instalar) and shutil.which(p.instalar[0]) is not None,
            # "Manual" no tiene ni instalar ni login: no hay proceso que correr
            # en la terminal, así que la UI no ofrece esos botones para él.
            "automatizable": bool(p.instalar) or bool(p.login),
            "formato_config": p.formato_config,
            "auto_registro": p.auto_registro,
        })
    return salida

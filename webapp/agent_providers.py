"""
Proveedores de CLI conocidos, para el wizard de la pestaña Agente.

Tabla chica y editable a mano: no hay forma de descubrir "qué CLIs de agentes
existen" de manera genérica, así que en vez de fingir una extensibilidad que
no existe, se declara la lista de memoria. Sumar uno nuevo es una entrada acá,
nada más — ningún otro archivo necesita saber que existe.

Cada proveedor declara su propio comando de instalación, corrido tal cual
—nunca `shell=True`— y sin sudo ni admin. Ninguno necesita Node: antes
Claude Code y Codex iban por `npm install -g`, y en una PC de planta sin
Node el botón "Instalar" no tenía con qué (y el instalador de Node arrastra
Python y Build Tools que nadie pidió). Cómo se instala cada uno, en Windows:

- **Claude Code**: `python -m webapp.instalar_agente claude-code`, que baja
  el binario firmado, verifica SHA256 y firma, y corre `claude install`
  (ver ese módulo). No el `irm ... | iex` oficial: Windows Defender lo
  marca como `Trojan:Win32/Commando.A!ml` cuando lo lanza este servidor —
  heurística sobre "PowerShell baja y ejecuta", no sobre el contenido.
- **Codex y Antigravity**: `winget install`, el gestor de paquetes de
  Windows, con manifiestos verificados por Microsoft; los dos están y van
  al día. winget no siempre está en el PATH del usuario aunque exista
  (pasa en Windows 10), así que se lo busca también en `WindowsApps`. Sin
  winget, queda el script del vendor, avisando que Defender puede saltar.
- En Linux/macOS, el `curl | sh` de cada vendor.

Lo que un instalador deja en el PATH del usuario lo ve una consola nueva,
no este servidor que ya estaba corriendo: por eso "instalado" y el comando
de login buscan el binario también en el PATH que dice el registro de
Windows y en la carpeta donde cada instalador suele dejarlo.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
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


def ruta_de_winget() -> str | None:
    """winget, en el PATH o donde lo deja la Store aunque el PATH no lo tenga."""
    if os.name != "nt":
        return None
    en_path = shutil.which("winget")
    if en_path:
        return en_path
    alias = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"))
    return str(alias) if alias.is_file() else None


_PAQUETE_WINGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{1,120}$")


def _winget(paquete: str) -> tuple[str, ...]:
    # `--source winget` a propósito: sin él winget consulta también la tienda
    # (msstore) y, cuando esa fuente falla —en la primera PC de la empresa, con
    # "0x8a15005e: el certificado del servidor no coincide"—, se niega a seguir
    # aunque el paquete esté en la fuente que sí funciona. Los tres CLIs viven
    # en la fuente `winget`, la comunitaria de Microsoft, y no en la tienda.
    return (
        ruta_de_winget() or "winget", "install", "--id", paquete, "--exact", "--source", "winget",
        "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity",
    )


def comando_winget_paquete(paquete: str) -> tuple[str, ...]:
    """
    Instalar cualquier paquete de winget por su id, para un CLI que no está en
    la tabla: es lo que hace útil a "Manual / otro". El id se valida con la
    forma de los ids de winget antes de armar el argv; sin winget en la máquina
    no hay comando.
    """
    paquete = (paquete or "").strip()
    if not _PAQUETE_WINGET.match(paquete):
        raise ValueError(f"id de paquete de winget inválido: {paquete!r} (ej. Anthropic.ClaudeCode)")
    if not ruta_de_winget():
        raise ValueError("esta máquina no tiene winget: instalá el CLI a mano y pegá la conexión MCP.")
    return _winget(paquete)


def _instalar_windows(paquete_winget: str, respaldo: tuple[str, ...]) -> tuple[str, ...]:
    """winget si está; si no, el respaldo del proveedor."""
    return _winget(paquete_winget) if ruta_de_winget() else respaldo


def _instalar(windows: tuple[str, ...], posix: tuple[str, ...]) -> tuple[str, ...]:
    return windows if os.name == "nt" else posix


def _python_con_consola() -> str:
    """
    El intérprete para correr `webapp.instalar_agente` en la terminal embebida.
    "Abrir Bot" corre con pythonw.exe, que no tiene stdout: sus prints no
    llegarían a la terminal (y reventarían). Al lado siempre está python.exe.
    """
    ejecutable = Path(sys.executable)
    if ejecutable.name.lower() == "pythonw.exe":
        consola = ejecutable.with_name("python.exe")
        if consola.is_file():
            return str(consola)
    return str(ejecutable)


# La bajada verificada de Claude Code (webapp/instalar_agente.py), como script
# por su ruta y no como `-m webapp.instalar_agente`: la terminal embebida
# corre los comandos parados en la carpeta de datos de la instalación, donde
# `webapp` no es importable — en la primera PC de la empresa falló con
# "No module named 'webapp'". El script no importa nada del paquete.
_INSTALADOR_VERIFICADO_CLAUDE = (
    _python_con_consola(), str(Path(__file__).resolve().with_name("instalar_agente.py")), "claude-code",
)


PROVEEDORES: tuple[Proveedor, ...] = (
    Proveedor(
        id="claude-code",
        label="Claude Code",
        binario="claude",
        # winget cuando está (Anthropic.ClaudeCode va al día); si no, la bajada
        # verificada desde Python. Nunca el `irm | iex` oficial: ver el docstring.
        instalar=_instalar(
            _instalar_windows("Anthropic.ClaudeCode", _INSTALADOR_VERIFICADO_CLAUDE),
            _INSTALADOR_VERIFICADO_CLAUDE,
        ),
        login=("claude",),
        doc=(
            "CLI oficial de Anthropic. Se instala con winget; sin winget, la app baja el binario "
            "firmado y lo verifica antes de instalarlo. Al loguearse abre un navegador para autorizar la cuenta."
        ),
        formato_config="json",
        auto_registro=True,
        rutas_probables=(
            r"%USERPROFILE%\.local\bin\claude.exe", r"%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe",
            "~/.local/bin/claude",
        ),
    ),
    Proveedor(
        id="codex",
        label="Codex CLI",
        binario="codex",
        instalar=_instalar(
            _instalar_windows("OpenAI.Codex", _powershell("irm https://chatgpt.com/codex/install.ps1 | iex")),
            _bash("curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
        ),
        login=("codex",),
        doc="CLI oficial de OpenAI. En Windows se instala con winget (sin Node).",
        formato_config="toml",
        auto_registro=True,
        # WinGet\Links es donde winget deja el alias de un paquete "portable".
        rutas_probables=(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Links\codex.exe",
            r"%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe",
            "~/.codex/bin/codex", "~/.local/bin/codex",
        ),
    ),
    Proveedor(
        id="antigravity",
        label="Antigravity CLI (agy)",
        binario="agy",
        instalar=_instalar(
            _instalar_windows("Google.AntigravityCLI", _powershell("irm https://antigravity.google/cli/install.ps1 | iex")),
            _bash("curl -fsSL https://antigravity.google/cli/install.sh | bash"),
        ),
        login=("agy",),
        doc=(
            "CLI oficial de Google — reemplazó a Gemini CLI (retirada en 2026). "
            "Al correrla por primera vez pide loguearse con Google Sign-In."
        ),
        formato_config="",  # no hay archivo de config documentado — sólo `agy mcp add`
        auto_registro=True,
        rutas_probables=(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Links\agy.exe", r"%LOCALAPPDATA%\agy\bin\agy.exe",
            "~/.agy/bin/agy", "~/.local/bin/agy",
        ),
    ),
    Proveedor(
        id="manual",
        label="Manual / otro",
        binario="",
        instalar=(),
        login=(),
        doc=(
            "Un CLI que no está en esta lista: se instala por su id de winget desde acá, "
            "y la conexión MCP se pega a mano con el bloque JSON de abajo."
        ),
        formato_config="json",
        auto_registro=False,
    ),
)


def proveedor(id_: str) -> Proveedor | None:
    return next((p for p in PROVEEDORES if p.id == id_), None)


def _path_del_registro() -> str:
    """
    El PATH que vería una consola nueva en Windows: el del usuario más el de
    la máquina, leídos del registro. Un instalador que agregó su carpeta al
    PATH del usuario no cambia el de este proceso, que ya estaba corriendo.
    """
    if os.name != "nt":
        return ""
    import winreg

    partes = []
    for raiz, clave in (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(raiz, clave) as k:
                valor, _tipo = winreg.QueryValueEx(k, "Path")
        except OSError:
            continue
        partes.append(os.path.expandvars(valor))
    return os.pathsep.join(partes)


def ruta_del_binario(p: Proveedor) -> str | None:
    """
    Dónde está el CLI: en el PATH de este proceso, en el PATH que dice el
    registro, o en la carpeta donde lo deja su instalador. None si no está.
    """
    if not p.binario:
        return None
    en_path = shutil.which(p.binario)
    if en_path:
        return en_path
    registro = _path_del_registro()
    if registro:
        en_registro = shutil.which(p.binario, path=registro)
        if en_registro:
            return en_registro
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

"""
Instalar Claude Code desde la app, sin PowerShell: `python -m webapp.instalar_agente claude-code`.

Por qué no el one-liner oficial (`irm https://claude.ai/install.ps1 | iex`):
Windows Defender lo marca como `Trojan:Win32/Commando.A!ml` cuando lo lanza
este servidor. `!ml` es una heurística —"un proceso sin ventana arranca
PowerShell con -ExecutionPolicy Bypass y ejecuta lo que acaba de bajar"— y
le da igual que el contenido sea legítimo; pedir permisos de administrador
no cambia el patrón, lo empeora. Encontrado en vivo en la primera
instalación en una PC de la empresa.

Lo que hace ese script oficial (`bootstrap.ps1`) es corto y está a la vista,
así que se hace lo mismo desde Python, con más verificación y sin ejecutar
nada bajado a ciegas:

1. pide la versión vigente (`/latest`) y el `manifest.json` de esa versión;
2. baja `claude.exe` de la plataforma a `%USERPROFILE%\\.claude\\downloads`;
3. comprueba el SHA256 contra el manifest — si no coincide, se borra y se
   corta;
4. en Windows, además, comprueba la firma Authenticode: tiene que ser
   válida y de Anthropic (Get-AuthenticodeSignature es PowerShell, pero sin
   bajar ni ejecutar nada);
5. recién ahí corre `claude.exe install latest`, que es lo que deja el
   lanzador en `~/.local/bin` y arma el auto-update — igual que el oficial.

Codex y Antigravity no pasan por acá: van por winget cuando está, y si no,
por el script del vendor (ver agent_providers.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "https://downloads.claude.ai/claude-code-releases"
TIMEOUT = 60
FIRMANTE = "Anthropic"


class InstalacionError(Exception):
    pass


def _plataforma() -> str:
    maquina = platform.machine().lower()
    if os.name == "nt":
        return "win32-arm64" if "arm" in maquina else "win32-x64"
    if sys.platform == "darwin":
        return "darwin-arm64" if "arm" in maquina else "darwin-x64"
    return "linux-arm64" if "aarch64" in maquina or "arm" in maquina else "linux-x64"


def _abrir(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": "bot-webapp"})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as r:  # noqa: S310 — https fijo
        return r.read()


def _firma_valida(ruta: Path, correr=subprocess.run) -> tuple[bool, str]:
    """Windows: la firma Authenticode del binario, válida y de Anthropic."""
    comando = [
        "powershell", "-NoProfile", "-Command",
        f"$f = Get-AuthenticodeSignature -FilePath '{ruta}'; "
        "Write-Output $f.Status; Write-Output $f.SignerCertificate.Subject",
    ]
    hecho = correr(comando, capture_output=True, text=True, timeout=60, shell=False)
    lineas = [l.strip() for l in (hecho.stdout or "").splitlines() if l.strip()]
    estado = lineas[0] if lineas else "?"
    sujeto = lineas[1] if len(lineas) > 1 else ""
    return estado == "Valid" and FIRMANTE.lower() in sujeto.lower(), f"{estado} · {sujeto or 'sin firmante'}"


def instalar_claude_code(*, abrir=_abrir, correr=subprocess.run, destino: Path | None = None,
                         canal: str = "latest", imprimir=print) -> int:
    """Devuelve el código de salida de `claude install`. Levanta InstalacionError si algo no verifica."""
    plataforma = _plataforma()
    version = abrir(f"{BASE}/latest").decode("utf-8", "replace").strip()
    if not version or not version[0].isdigit():
        raise InstalacionError(f"downloads.claude.ai no devolvió una versión: {version[:80]!r}")
    imprimir(f"Claude Code {version} para {plataforma}")

    manifest = json.loads(abrir(f"{BASE}/{version}/manifest.json"))
    checksum = ((manifest.get("platforms") or {}).get(plataforma) or {}).get("checksum")
    if not checksum:
        raise InstalacionError(f"el manifest no tiene la plataforma {plataforma}")

    carpeta = destino or Path.home() / ".claude" / "downloads"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = "claude.exe" if plataforma.startswith("win32") else "claude"
    binario = carpeta / f"claude-{version}-{plataforma}{'.exe' if nombre.endswith('.exe') else ''}"
    imprimir("Bajando el binario…")
    datos = abrir(f"{BASE}/{version}/{plataforma}/{nombre}")
    real = hashlib.sha256(datos).hexdigest()
    if real != checksum.lower():
        raise InstalacionError(f"el SHA256 no coincide con el manifest ({real[:12]}… vs {checksum[:12]}…): no se instala")
    binario.write_bytes(datos)
    imprimir(f"SHA256 verificado contra el manifest ({len(datos) // 1024 // 1024} MB).")

    try:
        if os.name == "nt":
            ok, detalle = _firma_valida(binario, correr)
            if not ok:
                raise InstalacionError(f"la firma del binario no es válida o no es de {FIRMANTE}: {detalle}")
            imprimir(f"Firma Authenticode: {detalle}")
        else:
            binario.chmod(0o755)
        imprimir("Corriendo `claude install`…")
        hecho = correr([str(binario), "install", canal], timeout=600, shell=False)
        codigo = int(getattr(hecho, "returncode", 1))
    finally:
        try:
            binario.unlink()
        except OSError:
            pass
    if codigo == 0:
        imprimir("Listo: Claude Code instalado. Cerrá esta terminal y usá Iniciar sesión.")
    return codigo


INSTALADORES = {"claude-code": instalar_claude_code}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in INSTALADORES:
        print(f"uso: python -m webapp.instalar_agente <{'|'.join(INSTALADORES)}>", file=sys.stderr)
        return 2
    try:
        return INSTALADORES[argv[0]]()
    except InstalacionError as exc:
        print(f"No se instaló: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"No se pudo bajar: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
#
# Construye BotSetup.exe para Windows, desde Linux.
#
#   installer/packaging/build_win.sh [version]
#
# No hace falta Windows ni Wine: NSIS compila instaladores de Windows de forma
# cruzada, y los wheels de Windows se bajan con `pip download --platform`.
#
# Lo que arma:
#
#   runtime/     CPython relocalizable (python-build-standalone) + cryptography
#   backend/     el núcleo
#   installer/   el wizard y su arranque
#   webapp/      el front
#
# Por qué un CPython adentro y no "instalá Python primero": los plugins se
# descubren con entry_points, o sea que tienen que vivir en un site-packages
# real. Congelar la app con PyInstaller sella ese site-packages y rompe la
# arquitectura de plugins; traer el intérprete la deja intacta.

set -euo pipefail

VERSION="${1:-0.1.0}"
PY_VERSION="3.12"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Lo construido queda dentro de installer/, junto a lo que lo construye.
TRABAJO="${RAIZ}/installer/build"
CARGA="${TRABAJO}/carga"
SALIDA="${TRABAJO}/BotSetup-${VERSION}.exe"

echo "==> Bot ${VERSION}"
rm -rf "${TRABAJO}"
mkdir -p "${CARGA}" "${TRABAJO}/descargas"

# ── 1. El intérprete ────────────────────────────────────────────────────
echo "==> CPython ${PY_VERSION} para Windows"
URL=$(curl -sL --max-time 30 \
  "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" \
  | grep -o "https[^\"]*cpython-${PY_VERSION}[^\"]*x86_64-pc-windows-msvc-install_only\.tar\.gz" \
  | head -1)
[ -n "${URL}" ] || { echo "no se encontró un build de CPython ${PY_VERSION}"; exit 1; }
curl -sL --max-time 300 "${URL}" -o "${TRABAJO}/descargas/python.tar.gz"
tar xzf "${TRABAJO}/descargas/python.tar.gz" -C "${TRABAJO}"
mv "${TRABAJO}/python" "${CARGA}/runtime"

# ── 2. Recorte ──────────────────────────────────────────────────────────
# 152 MB -> ~52 MB. Se va lo que no se usa: los símbolos de depuración (.pdb),
# Tcl/Tk —no hay ninguna interfaz nativa, el wizard es el navegador—, los
# headers de compilación y la suite de tests de la stdlib.
echo "==> recortando el runtime"
rm -rf "${CARGA}/runtime/Lib/test" "${CARGA}/runtime/Lib/tkinter" \
       "${CARGA}/runtime/Lib/idlelib" "${CARGA}/runtime/tcl" \
       "${CARGA}/runtime/include" "${CARGA}/runtime/libs"
find "${CARGA}/runtime" -name "*.pdb" -delete
find "${CARGA}/runtime/DLLs" \( -name "tcl*" -o -name "tk*" -o -name "_tkinter*" \) -delete
find "${CARGA}/runtime" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ── 3. Dependencias ─────────────────────────────────────────────────────
# `cryptography` es lo que el núcleo necesita para guardar secretos. Lo demás
# es lo que la webapp necesita para correr en la máquina del cliente: el
# servidor (fastapi + uvicorn), el .env, y subir archivos (python-multipart,
# para instalar un plugin desde el navegador). Sin esto "Abrir Bot" moría con
# un ModuleNotFoundError: el .exe traía la webapp pero no con qué levantarla.
# `mcp` viaja desde 0.4.1: al principio quedó afuera por peso ("herramienta
# de autoría, no de planta"), pero la pestaña Agente de la instalación mostraba
# una receta de conexión a un módulo que no existía ahí, y la idea es dejar
# el Bot instalado en una PC y que un agente escriba flujos contra ésa, no
# contra un checkout de desarrollo.
#
# `pip install --target` y no `pip download --no-deps`: con --no-deps faltaba
# `cffi`, que es de donde sale `_cffi_backend`, y la instalación reventaba al
# generar la llave. Un árbol de dependencias no se arma a mano.
echo "==> dependencias (wheels de Windows)"
SITE="${CARGA}/runtime/Lib/site-packages"
# Versiones fijas: las mismas del venv de desarrollo, que es donde se probó.
# `uvicorn` pelado y no `[standard]`: los extras (uvloop, httptools, watchfiles)
# no resuelven de forma cruzada para Windows y la webapp no los usa.
# websockets y pywinpty son de la pestaña Agente: la terminal embebida va por
# websocket, y en Windows un CLI que es una TUI necesita un pty real.
# tomli-w es de mcp_registration.py: escribe .codex/config.toml al dar de
# alta el MCP de esta instalación en Codex CLI. Sin esto en el runtime,
# "Abrir Bot" no arranca — el import está en la cadena de core_api.py.
# pywinauto es del port `window` del núcleo (backend/adapters/window_pywinauto.py,
# core#12): sin esto en el runtime, un plugin que declare ese port no arranca
# en la máquina del cliente aunque haya validado bien en desarrollo.
# pystray + pillow son el ícono de la bandeja (webapp/bandeja.py): sin ellos
# el servidor arranca igual, pero sin forma de cerrarlo que no sea el
# Administrador de tareas.
python3 -m pip install cryptography fastapi==0.136.0 uvicorn==0.45.0 python-dotenv==1.2.2 python-multipart==0.0.32 websockets pywinpty tomli-w==1.2.0 pywinauto==0.6.8 pystray==0.19.5 pillow==12.3.0 mcp==2.1.1 \
  --target "${SITE}" \
  --platform win_amd64 --python-version "${PY_VERSION}" \
  --only-binary=:all: --upgrade -q
rm -rf "${SITE}/bin"

# Que el árbol esté completo, verificado contra los metadatos de cada paquete.
# Es el chequeo que habría atajado lo de `cffi`: la falta no se nota en el
# build, se nota en la máquina del cliente y como un ModuleNotFoundError.
python3 - "${SITE}" "${PY_VERSION}" <<'PY'
import sys, pathlib

try:
    from packaging.requirements import Requirement
except ImportError:                       # pip siempre trae la suya
    from pip._vendor.packaging.requirements import Requirement

site, py = pathlib.Path(sys.argv[1]), sys.argv[2]

# El entorno de la máquina de DESTINO, no el de esta. Un marcador se evalúa
# contra Windows y contra el Python que se empaqueta: `typing-extensions` sólo
# hace falta con Python < 3.11, y evaluarlo acá con otra versión daría un
# faltante que no existe.
entorno = {
    "python_version": py,
    "python_full_version": f"{py}.0",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "implementation_name": "cpython",
    "os_name": "nt",
    "extra": "",
}

presentes = {d.name.split("-")[0].lower().replace("_", "-") for d in site.glob("*.dist-info")}
faltan = []
for meta in site.glob("*.dist-info/METADATA"):
    for linea in meta.read_text(encoding="utf-8", errors="replace").splitlines():
        if not linea.startswith("Requires-Dist:"):
            continue
        req = Requirement(linea.split(":", 1)[1].strip())
        # Sin extras: son opcionales y no se instalan salvo que se los pida.
        if req.marker is not None and not req.marker.evaluate(entorno):
            continue
        if req.name.lower().replace("_", "-") not in presentes:
            faltan.append(f"{meta.parent.name} necesita {req.name}")

if faltan:
    print("ERROR: faltan dependencias en el runtime:")
    print("\n".join(f"  {f}" for f in faltan))
    sys.exit(1)
print(f"    {len(presentes)} paquetes, árbol completo: {', '.join(sorted(presentes))}")
PY

# ── 4. La aplicación ────────────────────────────────────────────────────
#
# Con `git archive` y no con `cp -r`: copia exactamente lo que está versionado
# y nada más. Un `cp -r` se lleva lo que git ignora, y ahí vive `backend/data/`
# —la base de la instalación de desarrollo, con sus runs y sus secretos—, que
# terminaría adentro del .exe que se reparte. Pasó en el primer build.
echo "==> copiando la app (sólo lo versionado)"
if ! git -C "${RAIZ}" diff --quiet HEAD -- backend installer webapp; then
  echo "    aviso: hay cambios sin commitear; se empaqueta HEAD, no el árbol de trabajo"
fi
git -C "${RAIZ}" archive HEAD backend installer webapp core-release.json | tar -x -C "${CARGA}"
# packaging/ construye el .exe; no tiene por qué viajar adentro de él.
rm -rf "${CARGA}/installer/packaging"

# Lo que no tiene sentido en la máquina de un cliente: los tests, que no se
# corren allá. `backend/mcp` sí viaja (con su dependencia `mcp`, arriba): es
# lo que la pestaña Agente le da a Claude Code / Codex / agy para operar la
# instalación.
rm -rf "${CARGA}/backend/tests" "${CARGA}/installer/source/tests" "${CARGA}/webapp/tests"

# Verificación, no confianza: que no se haya colado ninguna base ni ninguna
# llave. Es barato y el modo de falla es repartir datos ajenos.
if find "${CARGA}" \( -name "*.db" -o -name "*.key" -o -name ".env" \) -print | grep -q .; then
  echo "ERROR: se coló un archivo de datos en la carga:"
  find "${CARGA}" \( -name "*.db" -o -name "*.key" -o -name ".env" \) -print
  exit 1
fi

# La versión de la web app que viaja en este .exe, en el mismo formato que
# deja Config → Actualizaciones al aplicar un release (webapp/updates.py):
# así la pantalla y el ícono de la bandeja saben qué web app corre, y la
# primera actualización desde la app ya tiene un "anterior" con nombre.
# El tag con "v", como lo publica `gh release create vX.Y.Z`: así la pantalla
# marca "instalado" al release que corresponde y no ofrece reinstalarlo.
python3 - "${CARGA}/webapp-release.json" "${VERSION}" <<'PY'
import json, sys, time
tag = "v" + sys.argv[2].lstrip("vV")
json.dump({"tag": tag, "applied_at": time.time(), "source": "instalador", "previous_tag": None},
          open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY

cat > "${CARGA}/LEEME.txt" <<TXT
Bot ${VERSION}

Para configurarlo: menú Inicio -> Bot -> Configurar Bot.
Se abre un asistente en el navegador que crea la instalación en la carpeta
que elijas (por defecto, una carpeta Bot en el Escritorio). Al terminar, el
botón "Abrir Bot" levanta la app en el navegador.

Para abrirla otro día: menú Inicio -> Bot -> Abrir Bot. Abre la última
instalación que hizo el asistente; para otra, desde una consola:
    runtime\python.exe -m webapp --root "C:\ruta\a\la\instalacion"

Esa carpeta es la instalación: contiene la base de datos, la configuración
y el espacio de trabajo. Para llevarla a otra máquina, se copia entera.

Desinstalar este programa NO borra esa carpeta. Adentro está data\secret.key,
que es la llave con la que se cifran las contraseñas guardadas: sin ese
archivo no se pueden recuperar, ni con una copia de la base.
TXT

# ── 5. El instalador ────────────────────────────────────────────────────
echo "==> makensis"
MAKENSIS="${MAKENSIS:-makensis}"
"${MAKENSIS}" -V2 \
  "-DVERSION=${VERSION}" \
  "-DCARGA=${CARGA}" \
  "-DSALIDA=${SALIDA}" \
  "${RAIZ}/installer/packaging/bot.nsi"

echo
echo "==> listo: ${SALIDA}"
du -h "${SALIDA}" | cut -f1 | sed 's/^/    /'

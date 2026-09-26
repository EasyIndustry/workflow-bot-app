#!/usr/bin/env bash
#
# Bot en Linux, directo desde el repo.
#
#   ./bot.sh              abre el Bot (la última instalación; sin ninguna, el wizard)
#   ./bot.sh instalar     el wizard de instalación
#   ./bot.sh acceso       deja "Abrir Bot" en el menú de aplicaciones
#   ./bot.sh --root DIR   cualquier otro argumento va a `python -m webapp`
#
# En Windows el `.exe` trae su propio CPython. Acá no hace falta: casi todo
# Linux tiene un python3, pero no siempre sirve tal cual. Debian y Ubuntu
# marcan el del sistema como "externally managed" (PEP 668, pip no instala
# ahí) y muchas veces no traen `python3-venv`, así que ni siquiera se puede
# armar un venv sin sudo. Por eso el runtime vive en `.runtime/`, al lado
# del código, y se arma una sola vez:
#
#   1. un venv del python3 del sistema, si es 3.11 o mayor y puede armarlo;
#   2. si no, el mismo CPython portable que empaqueta el `.exe`
#      (python-build-standalone), bajado sin sudo.
#
# Las dependencias son las del `.exe` menos lo que es sólo de Windows. Se
# reinstalan solas cuando cambia esta lista, no en cada arranque.

set -euo pipefail

PROGRAMA="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
RUNTIME="${PROGRAMA}/.runtime"

# Sin el site de usuario (~/.local/lib/pythonX.Y). Un venv ya lo excluye; el
# CPython portable no, y pip daba por instaladas `click` y `cffi` porque
# estaban ahí: el runtime quedaba incompleto y la app moría con otro usuario
# (ModuleNotFoundError: _cffi_backend). Lo que corre tiene que estar en .runtime/.
export PYTHONNOUSERSITE=1
PY_STANDALONE="3.12"

# Versiones fijas, las mismas de installer/packaging/build_win.sh: es donde
# se probaron. `uvicorn` pelado, como en el `.exe`. Sin pywinpty/pywinauto:
# son sólo de Windows (POSIX tiene pty en la stdlib, y el port `window` no
# existe acá). pystray/pillow son el ícono de la bandeja; en Linux además
# necesitan el `gi` del sistema, ver `enlazar_gi`.
DEPENDENCIAS=(
  cryptography
  fastapi==0.136.0
  uvicorn==0.45.0
  python-dotenv==1.2.2
  python-multipart==0.0.32
  websockets
  tomli-w==1.2.0
  mcp==2.1.1
  pystray==0.19.5
  pillow==12.3.0
)

aviso() { printf '==> %s\n' "$*" >&2; }
falla() { printf 'Bot: %s\n' "$*" >&2; exit 1; }

python_del_runtime() {
  local candidato
  for candidato in "${RUNTIME}/venv/bin/python" "${RUNTIME}/python/bin/python3"; do
    if [ -x "${candidato}" ] && "${candidato}" -c "" 2>/dev/null; then
      printf '%s' "${candidato}"
      return 0
    fi
  done
  return 1
}

# El primer python3 del sistema que sea 3.11 o mayor y que sepa armar un
# venv con pip (sin `ensurepip`, `-m venv` falla a medias en Debian/Ubuntu).
python_del_sistema() {
  local nombre ruta
  for nombre in python3.13 python3.12 python3.11 python3; do
    ruta="$(command -v "${nombre}" 2>/dev/null)" || continue
    "${ruta}" -c 'import sys, ensurepip, venv; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || continue
    printf '%s' "${ruta}"
    return 0
  done
  return 1
}

bajar() {  # bajar URL DESTINO
  if command -v curl >/dev/null; then
    curl -fsSL --max-time 300 "$1" -o "$2"
  elif command -v wget >/dev/null; then
    wget -q -O "$2" "$1"
  else
    falla "hace falta curl o wget para bajar Python."
  fi
}

armar_standalone() {
  local maquina url tmp
  case "$(uname -m)" in
    x86_64|amd64) maquina="x86_64-unknown-linux-gnu" ;;
    aarch64|arm64) maquina="aarch64-unknown-linux-gnu" ;;
    *) falla "no hay un Python portable para $(uname -m). Instalá python3 (3.11 o mayor) con python3-venv." ;;
  esac
  aviso "no hay un python3 que sirva: bajo CPython ${PY_STANDALONE} portable (una sola vez)"
  # Adentro de .runtime/ y no en /tmp: el `mv` del final tiene que ser en el
  # mismo disco para ser atómico. Un corte a mitad de la descarga no deja un
  # python/ a medias que el próximo arranque tome por bueno.
  tmp="$(mktemp -d "${RUNTIME}/descarga.XXXXXX")"
  if ! bajar "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" "${tmp}/release.json"; then
    rm -rf "${tmp}"
    falla "sin conexión a GitHub para bajar Python. Instalá python3 (3.11 o mayor) con python3-venv y volvé a correr esto."
  fi
  url="$(grep -o "https[^\"]*cpython-${PY_STANDALONE}\.[0-9]*[^\"]*${maquina}-install_only\.tar\.gz" "${tmp}/release.json" | head -1)"
  if [ -z "${url}" ] || ! bajar "${url}" "${tmp}/python.tar.gz" || ! tar xzf "${tmp}/python.tar.gz" -C "${tmp}"; then
    rm -rf "${tmp}"
    falla "no se pudo bajar un CPython ${PY_STANDALONE} para ${maquina}${url:+ (${url})}."
  fi
  rm -rf "${RUNTIME}/python"
  mv "${tmp}/python" "${RUNTIME}/python"
  rm -rf "${tmp}"
}

armar_runtime() {
  mkdir -p "${RUNTIME}"
  local sistema
  if [ "${BOT_PYTHON:-}" != "portable" ] && sistema="$(python_del_sistema)"; then
    aviso "armando el entorno con ${sistema} ($("${sistema}" -c 'import platform; print(platform.python_version())'))"
    rm -rf "${RUNTIME}/venv"
    if "${sistema}" -m venv "${RUNTIME}/venv"; then
      return 0
    fi
    rm -rf "${RUNTIME}/venv"
    aviso "no se pudo armar el venv con ${sistema}"
  fi
  armar_standalone
}

dependencias() {
  local python="$1" marca="${RUNTIME}/dependencias.txt"
  local lista
  lista="$(printf '%s\n' "${DEPENDENCIAS[@]}")"
  if [ -f "${marca}" ] && [ "$(cat "${marca}")" = "${lista}" ]; then
    return 0
  fi
  aviso "instalando dependencias en ${RUNTIME}"
  "${python}" -m pip install -q --disable-pip-version-check --upgrade pip
  "${python}" -m pip install -q --disable-pip-version-check "${DEPENDENCIAS[@]}" \
    || falla "no se pudieron instalar las dependencias (¿sin internet?). Se reintenta en el próximo arranque."
  printf '%s' "${lista}" > "${marca}"
}

# El ícono de la bandeja en Linux va por pystray con appindicator o gtk, y
# los dos necesitan PyGObject (`gi`). Ese no se instala con pip: no tiene
# wheels, compila contra las librerías del escritorio. Viene con el sistema
# (python3-gi) y el runtime no lo ve, porque el venv excluye el site del
# sistema a propósito. Se enlaza sólo el paquete `gi`, no dist-packages
# entero: abrir todo el site del sistema dejaría que un paquete viejo de la
# distro tape uno de los fijos. Y sólo si el `_gi` está compilado para esta
# misma versión de Python. Sin `gi`, pystray no carga y el servidor
# arranca sin ícono, como antes.
enlazar_gi() {
  local python="$1" sitio etiqueta candidato gi
  sitio="$("${python}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  if "${python}" -c 'import gi' 2>/dev/null; then
    return 0
  fi
  etiqueta="$("${python}" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
  for candidato in /usr/bin/python3 /usr/bin/python3.[0-9]*; do
    [ -x "${candidato}" ] || continue
    gi="$("${candidato}" -c 'import gi, os; print(os.path.dirname(gi.__file__))' 2>/dev/null)" || continue
    [ -e "${gi}/_gi${etiqueta}" ] || continue
    mkdir -p "${RUNTIME}/sistema"
    ln -sfn "${gi}" "${RUNTIME}/sistema/gi"
    printf '%s\n' "${RUNTIME}/sistema" > "${sitio}/bot-gi-del-sistema.pth"
    "${python}" -c 'import gi' 2>/dev/null && return 0
    rm -f "${sitio}/bot-gi-del-sistema.pth"
  done
  return 0
}

# "Abrir Bot" en el menú: un .desktop que llama a este mismo script. Apunta
# al repo donde está, así que mover el repo es volver a correr `acceso`.
acceso() {
  local apps="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
  local archivo="${apps}/bot.desktop"
  mkdir -p "${apps}"
  cat > "${archivo}" <<EOF
[Desktop Entry]
Type=Application
Name=Abrir Bot
Comment=Abre el Bot en el navegador
Exec="${PROGRAMA}/bot.sh"
Icon=${PROGRAMA}/installer/packaging/bot.svg
Terminal=false
Categories=Utility;
EOF
  chmod +x "${archivo}"
  aviso "listo: \"Abrir Bot\" en el menú de aplicaciones (${archivo})"
  local escritorio
  escritorio="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  if [ -n "${escritorio}" ] && [ -d "${escritorio}" ] && [ "${escritorio}" != "${HOME}" ]; then
    cp "${archivo}" "${escritorio}/bot.desktop"
    chmod +x "${escritorio}/bot.desktop"
    command -v gio >/dev/null && gio set "${escritorio}/bot.desktop" metadata::trusted true 2>/dev/null || true
    aviso "y en el escritorio (${escritorio}/bot.desktop)"
  fi
}

main() {
  if [ "${1:-}" = "acceso" ]; then
    acceso
    return 0
  fi

  local python
  python="$(python_del_runtime)" || { armar_runtime; python="$(python_del_runtime)" || falla "no quedó un Python usable en ${RUNTIME}."; }
  dependencias "${python}"
  enlazar_gi "${python}"
  cd "${PROGRAMA}"

  if [ "${1:-}" = "instalar" ]; then
    shift
    exec "${python}" installer/instalar.py "$@"
  fi

  # Con argumentos manda quien llama (`--root`, `--port`…).
  if [ $# -gt 0 ]; then
    exec "${python}" -m webapp "$@"
  fi

  # Sin argumentos, la última instalación que anotó el wizard, y con `--root`
  # explícito. `python -m webapp` pelado prefiere el repo si tiene un data/
  # al lado —el modo desarrollo—, y ese data/ aparece solo con correr los
  # tests: pasó al probar esto, y la app abrió el repo en vez de la
  # instalación recién hecha. Sin ninguna anotada, va el wizard.
  local raiz
  raiz="$("${python}" -c 'from webapp import ubicacion; print(ubicacion.ultima() or "")')"
  if [ -z "${raiz}" ]; then
    aviso "no hay ninguna instalación todavía: abro el wizard"
    exec "${python}" installer/instalar.py
  fi
  # `--red` como el acceso directo de Windows: se opera desde otra PC de la
  # red local.
  exec "${python}" -m webapp --root "${raiz}" --red
}

main "$@"

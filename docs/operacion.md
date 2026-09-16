# Operación

## Instalar en una PC nueva

1. Bajar `BotSetup-<versión>.exe` del release
   (https://github.com/EasyIndustry/workflow-bot-app/releases). Instala en
   `%LOCALAPPDATA%\Programs\Bot`, sin UAC. Al final: "Configurar Bot ahora"
   y la casilla del ícono en el escritorio.
2. El wizard crea la instalación en la carpeta que se elija. "Abrir Bot"
   levanta la app con `--red` y deja el ícono en la bandeja (en Windows 10
   queda en el desborde `^` hasta arrastrarlo). Windows pregunta por el
   firewall de `pythonw.exe`: permitir en redes privadas para entrar desde
   otras PCs.
3. Plug ins → **Plugins en línea**: elegir repo y rama, instalar lo que
   haga falta. Un repo privado necesita `PLUGINS_GITHUB_TOKEN` en Config →
   Variables (secreta).
4. Config → Variables: `GITHUB_TOKEN` si el repo de actualizaciones de la
   app es privado (el público no lo necesita).
5. Agente → **Instalar** el CLI que se use; **Iniciar sesión** deja el
   `.mcp.json` (Claude Code) o `.codex/config.toml` en la instalación.
   En la carpeta de la instalación ya hay un `AGENTS.md` (y un `CLAUDE.md`
   que lo importa) que la app regenera sola: le dice al agente qué es esto,
   las reglas y que empiece por la tool `describe_installation`. No se
   edita a mano; lo que haya que contarle al agente va en Plug ins →
   Conocimiento → Notas.

## Actualizar

Config → Actualizaciones. Dos bloques, Núcleo y Web app, cada uno con su
repo (editable, guardado por instalación). Instalar un tag valida en otro
proceso, aplica con la carpeta anterior al lado (`backend.anterior/`,
`webapp.anterior/`) y pide reiniciar; "Reiniciar ahora" vuelve solo. Sin
internet: subir el `.tar.gz`/`.zip` del tag. Si la app no levanta después:

```
runtime\python.exe -m webapp --revertir-nucleo
runtime\python.exe -m webapp --revertir-webapp
```

desde una consola en la carpeta del programa. Si ni eso importa, renombrar
`webapp/` ↔ `webapp.anterior/` a mano.

## Publicar una versión

```bash
git push origin main
gh release create vX.Y.Z --prerelease --target main --title vX.Y.Z --notes "..."
```

El workflow *Instalador de Windows* construye `BotSetup-X.Y.Z.exe` y lo
cuelga del release (unos 4 minutos). Config → Actualizaciones de cualquier
instalación lista ese tag; con "incluir releases de prueba" si es
pre-release. Para rehacer el `.exe` de un tag: `gh workflow run "Instalador
de Windows" -f tag=vX.Y.Z`.

Build local (Git Bash): `installer/packaging/build_win.sh X.Y.Z` con
`python3` y `makensis` en el PATH (en la máquina de desarrollo están en
`D:\Proyectos\herramientas-build\`; el PATH va en forma POSIX).

## Correr desde el repo

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r webapp/requirements.txt cryptography pytest pywinauto pystray pillow pywinpty
git config core.hooksPath .githooks
python -m webapp                    # data/ al lado del código
python -m pytest webapp installer -q
```

Contra una instalación: `python -m webapp --root C:\...\Bot --port 8010`.
Para probar la UI sin mirar: Chrome headless por CDP (ver un ejemplo en el
historial de commits; `--headless=new --remote-debugging-port`).

## Desde otra PC o desde un agente remoto

Con `--red`, `http://<ip>:8000` sirve la misma UI y la misma API. "Copiar
dirección para otras PCs" en la bandeja da la URL. Un agente remoto usa la
API (ver `docs/arquitectura.md` y el README del plugin `bots` en el
catálogo). Un flujo puede hablarle a otro Bot con el plugin `bots`.

## Traer un cambio del núcleo

Config → Actualizaciones, o a mano:

```bash
git fetch core "+refs/tags/*:refs/tags/core/*"
git checkout core/vX.Y.Z -- backend/
```

El hook de pre-commit bloquea un `backend/` que no coincida con el release.

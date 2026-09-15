# workflow-bot-app

La app de [`workflow-bot-core`](https://github.com/EasyIndustry/workflow-bot-core):
un front en el navegador y una API HTTP sobre el núcleo, más el instalador
de Windows. Bot procesa filas de una fuente de datos (una API) una por una,
siguiendo un flujo escrito en Mermaid. Cada nodo es un tool de un plugin;
cada ejecución deja traza por nodo, con los parámetros ya resueltos.

Se instala en una máquina Windows, muchas veces sin internet, acotado a una
carpeta, y lo opera una persona desde el navegador. Un agente por MCP puede
escribir flujos y plugins contra la instalación.

## Las tres piezas

| Carpeta | Qué es | Regla |
|---|---|---|
| `backend/` | el núcleo, vendorizado de [`workflow-bot-core`](https://github.com/EasyIndustry/workflow-bot-core) | **no se edita acá**: se trae de un release (Config → Actualizaciones). El hook de pre-commit lo hace cumplir |
| `webapp/` | el front y la API HTTP | FastAPI + JS sin build, módulos ES nativos |
| `installer/` | el wizard de primera instalación y el build del `.exe` | `installer/packaging/build_win.sh <version>` |

El tag vendorizado está en `core-release.json`.

## Arrancar

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r webapp/requirements.txt cryptography pytest
git config core.hooksPath .githooks              # una vez por clon

python -m webapp                                 # la app, contra el repo (data/ al lado)
python -m webapp --root C:\ruta\Bot --port 8010  # contra una instalación
python installer/instalar.py                     # el wizard
python -m pytest webapp installer backend/tests -q
```

## Una instalación

```
<carpeta>/
├── boot.env        cómo arranca
├── data/           la base y la llave · fuera de la caja
├── plugins/        los plugins instalados · fuera de la caja
└── workspace/      la caja · lo único que los flujos tocan
```

`data/` y `plugins/` quedan fuera de `fs_root` a propósito: un flujo con el
port `fs` no puede alcanzar la base, la llave ni el código que se carga. Los
flujos no pueden ejecutar ningún programa hasta que se lo nombre en
`boot.env` (`process_allowlist`).

El `.exe` instala el Bot **sin plugins**: se traen desde Plug ins → *Plugins
en línea*, un catálogo en GitHub con la forma de
[`workflow-bot-plugins`](https://github.com/EasyIndustry/workflow-bot-plugins)
(rama `cured` = curado, `draft` = sin terminar). El repo y la rama se eligen
por instalación; un catálogo propio, privado, necesita un token como variable
`PLUGINS_GITHUB_TOKEN`.

## Qué hace la app

- **Sources**: la fuente de filas (una API), su grilla, y ejecutar un flujo
  sobre una fila o un lote. La columna Log muestra el progreso mientras corre.
- **Workflows**: los flujos en Mermaid, como tarjetas o como texto, con
  diagrama, diagnóstico y dry run.
- **Plug ins**: lo instalado, sus settings y colecciones dibujados desde el
  manifest; instalar desde el catálogo o desde un archivo.
- **Agente**: la receta MCP de la instalación, y la terminal embebida para
  instalar y loguear Claude Code, Codex o Antigravity, que la registran solos.
- **Config**: secretos y variables, límites, diagnóstico, base de datos,
  actores, y **Actualizaciones** del núcleo y de la app desde releases de
  GitHub (repos editables por instalación).

El servidor que levanta "Abrir Bot" queda como ícono en la bandeja: abrir,
copiar la dirección para otras PCs, ver el registro, reiniciar, cerrar. Con
`--red` escucha en toda la red local.

## `backend/` se trae de `workflow-bot-core`, no se edita acá

La fuente de la verdad es su último release (tag `vX.Y.Z`). Traer un cambio
del núcleo es acotado a esa carpeta:

```bash
git remote add core https://github.com/EasyIndustry/workflow-bot-core.git   # una vez
git fetch core "+refs/tags/*:refs/tags/core/*"
git checkout core/vX.Y.Z -- backend/
```

Es lo mismo que hace Config → Actualizaciones. El hook `.githooks/pre-commit`
bloquea un commit que deje `backend/` distinto de ese release. Lo que haya
que cambiar en el núcleo es un issue en ese repo.

## Publicar una versión

```bash
gh release create vX.Y.Z --generate-notes          # lo que lista Config → Actualizaciones
installer/packaging/build_win.sh X.Y.Z             # BotSetup-X.Y.Z.exe, desde Linux o Git Bash
```

`CLAUDE.md` tiene las reglas de cómo se escribe acá.

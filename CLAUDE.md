# workflow-bot-app — guía para trabajar en este repo

Bot procesa filas de una fuente de datos (una API) una por una, siguiendo un
flujo escrito en Mermaid. Cada nodo es un tool de un plugin; cada ejecución
deja traza por nodo. Se instala en una máquina Windows, muchas veces sin
internet, acotado a una carpeta, y lo opera una persona desde el navegador. Un
agente por MCP puede escribir flujos y plugins.

## Las tres piezas

| Carpeta | Qué es | Regla |
|---|---|---|
| `backend/` | el núcleo, vendorizado de [`EasyIndustry/workflow-bot-core`](https://github.com/EasyIndustry/workflow-bot-core) | **no se edita acá**. Se trae de un release con Config → Actualizaciones (o `webapp.updates.aplicar`). El hook de pre-commit lo hace cumplir. Lo que haya que cambiar en el núcleo es un issue en ese repo |
| `webapp/` | el front y la API HTTP sobre el núcleo | acá se trabaja. FastAPI + JS sin build, módulos ES nativos |
| `installer/` | el wizard de primera instalación y el build del `.exe` | acá se trabaja |

El tag vendorizado está en `core-release.json`. Los issues del núcleo se abren
en `workflow-bot-core`; los de la app, acá.

**Antes de tocar nada, leer [`docs/README.md`](docs/README.md)**: el índice
de la documentación del proyecto (estado por fecha, arquitectura, operación,
decisiones y pendientes). Cada cambio que altere qué existe o cómo se opera
actualiza el archivo que corresponde y agrega una línea fechada en
`docs/estado-del-proyecto.md`.

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

Una instalación es una carpeta con `boot.env`, `data/`, `plugins/` y
`workspace/`. `data/` y `plugins/` quedan fuera de `fs_root` a propósito: un
flujo con el port `fs` no puede alcanzar la base, la llave ni el código que se
carga.

## Cómo se escribe acá

- **Comentarios y commits en castellano**, y explican el *por qué*, no el qué.
  Un commit cuenta qué se veía roto y qué decisión se tomó. Sin firmas de
  herramientas.
- **La UI no promete lo que el núcleo no cumple.** Una sección sin backend lo
  dice y nombra lo que falta, en vez de dibujar controles que no hacen nada.
- **Los secretos no salen por ninguna API.** `env` cifra; `settings` y
  `plugin_items` guardan en claro lo declarado `secret`, así que cualquier
  listado nuevo los tapa (ver `webapp/db_view.py`).
- **Lo que carga código corre en otro proceso.** Instalar un plugin o un
  núcleo nuevo se valida con `python -m backend.core ... --json` en un
  subproceso, contra una raíz temporal, antes de tocar el disco.
- **Ninguna pantalla conoce un plugin por nombre.** Settings, colecciones y
  acciones se dibujan desde el manifest (`GET /tools`). Si hace falta tocar
  `plugins.js` para que un plugin se vea bien, algo se declaró en el lugar
  equivocado.
- **Lo que un flujo alcanza del disco son las raíces declaradas**, y pueden
  ser varias. `fs_root` es una sola —la clásica, `workspace/`—; `fs_roots`
  (núcleo v0.3.1-beta.3, core#23) son varias con alias
  (`fs_roots=casa=C:\Bot\workspace, origen=\\servidor\share`): la primera
  resuelve las rutas relativas, a las demás se llega con `origen:archivo`.
  Existe porque una instalación real necesita el workspace local y un share
  de red a la vez, y antes había que elegir o vaciar `fs_root`, que es apagar
  el acotamiento. Una raíz declarada que no existe **impide arrancar**
  (core#22): antes la instalación levantaba y el error salía mucho después
  adentro de un run, como `PortError: ruta fuera del árbol permitido`, que
  parece un error del flujo. Al escribir una ruta UNC tiene que ir el share
  (`\\servidor\share`), no sólo el host. En la UI esto se lee en Inicio →
  "Hasta dónde llega", que es la pantalla que muestra los límites; si se
  agrega un límite nuevo al núcleo, va ahí.
- **Un plugin pide ports para I/O y declara librerías para cómputo.** Lo que
  toca red, disco, procesos o ventanas va por un port del núcleo. numpy o
  trimesh van en un `requirements.txt` junto al `__init__.py`, con versión y
  hash fijos: la app los instala con pip en el runtime del programa, sólo
  desde wheels, antes de validar el plugin (`webapp/librerias.py`). El
  `.exe` publica `runtime-release.json` y el catálogo cura contra esa
  versión.
- **Los plugins son genéricos**, con nombre de herramienta y nunca de un
  cliente ni de un sistema externo: una llamada HTTP guardada es una Action
  de `connections`, no un plugin. Los plugins no viven en este repo: el
  `.exe` instala el Bot sin plugins y se traen de un catálogo (Plug ins →
  Plugins en línea, `webapp/plugin_catalog.py`) con la forma de
  [`EasyIndustry/workflow-bot-plugins`](https://github.com/EasyIndustry/workflow-bot-plugins).
- Antes de commitear una vista, correr el recorrido real y mirarlo: Chrome
  headless por CDP con un script, o el navegador. Los chequeos de sintaxis no
  alcanzaron nunca.

## Qué hay

- Config → Actualizaciones trae el núcleo (`backend/`) y la app (`webapp/`)
  de releases de GitHub, con la misma mecánica (`webapp/updates.py`, un
  `Componente` por carpeta): validar en otro proceso, aplicar con la carpeta
  anterior al lado, reiniciar. El repo de cada componente se guarda en la
  base por instalación; el del código es sólo el default. Un repo privado
  necesita `GITHUB_TOKEN` en Config → Variables. Publicar una versión de la
  app es `gh release create vX.Y.Z`; el `.exe` deja `webapp-release.json` con
  la suya.
- La pestaña Agente da la receta MCP de la instalación y la registra sola en
  Claude Code / Codex / agy al loguearlos desde la terminal embebida. La
  receta arranca `webapp/mcp_servidor.py`: el `backend/mcp` del núcleo (viaja
  en el `.exe` con su dependencia `mcp`) con `root` = la instalación y
  `connections` cargado, que el núcleo solo no conoce. Lleva `cwd` **y**
  `env.PYTHONPATH`/`BOT_ROOT`: Claude Code ignora `cwd`.
- El servidor que levanta "Abrir Bot" queda como ícono en la bandeja
  (`webapp/bandeja.py`). Con `--red` escucha en toda la red local; es lo que
  usan el acceso directo y el wizard.
- Mientras una fila corre, la columna Log muestra el progreso por nodo
  (`GET /runs/en-vuelo`, con el `on_step` del núcleo desde v0.3.1-beta.1).
- Una instalación lleva un `AGENTS.md` generado (`webapp/contexto_agente.py`)
  que le dice al agente qué es esto y que empiece por `describe_installation`;
  lo que haya que contarle va en Plug ins → Conocimiento → Notas, no en el
  archivo.

## Lo que muerde en este clon

En Windows fallan algunos tests de `backend/tests` que son del núcleo, no de
la webapp; no son del cambio que estés haciendo. Contra qué compararlos: la
actualización deja la carpeta anterior al lado (`backend.anterior/`), así que
se corren ahí los mismos tests y se ve si ya fallaban antes.

Antes de commitear, mirá **qué** cambió y no sólo qué figura como modificado:

- Muchos archivos de `webapp/` aparecen como modificados con **cero** cambios
  de contenido: es CRLF contra LF, no código.
  `git diff --ignore-cr-at-eol --numstat -- <archivo>` devuelve `0` para
  esos. No los metas en un commit: enterrarían el cambio real.
- `webapp.anterior/`, `webapp-release.json` y `core-release.anterior.json`
  son restos de una actualización aplicada sobre el repo; van sin versionar.
- `backend/VERSION` lo genera el tarball del release y no existe en el tag
  del núcleo, así que está en `.gitignore`. El hook de pre-commit compara
  `backend/` contra el tag archivo por archivo, y cualquier cosa que el
  tarball traiga de más lo frena: la salida del hook nombra el archivo.

Vendorizar un release del núcleo es la misma mecánica que Config →
Actualizaciones, desde Python: `updates.descargar` → `updates.preparar` →
`updates.validar` → `updates.aplicar(REPO, nuevo, tag=…, comp=updates.CORE)`.
`descargar` devuelve el **tarball**, no la carpeta; sin `preparar` en el medio,
`validar` falla con "no armó el catálogo". Después, verificar los issues que el
release dice cerrar corriéndolos de verdad contra una instalación, y comentar
el resultado en cada uno.

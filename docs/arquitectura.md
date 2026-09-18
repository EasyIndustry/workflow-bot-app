# Arquitectura

## Las piezas

```
backend/     el núcleo (workflow-bot-core), vendorizado por release. No se edita acá.
webapp/      FastAPI + JS sin build (módulos ES). La API HTTP y el front.
installer/   el wizard de primera instalación (stdlib) y el build del .exe (NSIS).
```

Una **instalación** es una carpeta elegida en el wizard: `boot.env`,
`data/` (base SQLite y llave), `plugins/`, `workspace/` (lo único que los
flujos tocan por el port `fs`). El **programa** vive aparte, en
`%LOCALAPPDATA%\Programs\Bot` (runtime CPython, `backend/`, `webapp/`,
`installer/`). En el repo de desarrollo, código y datos son la misma
carpeta; muchos bugs sólo aparecen cuando no lo son.

## El núcleo, en una frase

`Instance(root)` carga plugins (de `plugins/` y los *locales* que le pasa la
app, hoy `connections`), guarda flujos y runs en la base, y `Instance.run(
flow, case_id, row)` recorre el grafo Mermaid nodo por nodo llamando tools.
Cada tool declara params/outputs y sólo habla con el mundo por **ports**
(`http`, `fs`, `process`, `clock`, `window`, `browser`). El MCP
(`backend/mcp`) expone lo mismo a un agente.

## Módulos clave de la webapp

| Módulo | Qué hace |
|---|---|
| `webapp/server.py` | arma la app FastAPI, monta `routes/core_api.py` bajo `/api/core` y los estáticos |
| `webapp/routes/core_api.py` | toda la API. Construye `_instance` al importarse (por eso `BOT_ROOT` va por entorno) |
| `webapp/__main__.py` | el lanzador: `--root`, `--port`, `--red`, `--sin-bandeja`, `--revertir-nucleo/-webapp`; reinicio relanzando el mismo comando |
| `webapp/run_gate.py` | lector-escritor para runs concurrentes; `run_with_gate` es el único punto por donde arranca un run |
| `webapp/runs_en_vuelo.py` | qué corre ahora (para la barra de la grilla) y los resultados por ticket de `POST /runs` |
| `webapp/connections/` | plugin local: Sources (la grilla) y Actions (una llamada HTTP guardada como nodo) |
| `webapp/librerias.py` | las librerías Python que pide un plugin en su `requirements.txt` (versión y hash fijos, sólo wheels), instaladas con pip en el runtime del programa antes de validar el plugin; la versión del runtime (`runtime-release.json`, la deja el `.exe`) contra la que cura el catálogo |
| `webapp/conocimiento/` | plugin local: la colección `notas`, lo que un agente tiene que saber de la instalación y no está en ningún otro lado |
| `webapp/contexto_agente.py` | el manual agéntico: `describir` (el `describe_installation` del núcleo más fuentes y notas) y el `AGENTS.md` que se deja en la instalación al arrancar y al cambiar flujos, plugins o colecciones |
| `webapp/plugin_install.py` · `plugin_catalog.py` | instalar un plugin desde archivo o desde el catálogo en GitHub, validando en otro proceso |
| `webapp/updates.py` | actualizar `backend/` y `webapp/` desde releases, por `Componente` |
| `webapp/agent_providers.py` · `instalar_agente.py` · `mcp_registration.py` · `mcp_servidor.py` · `agent_terminal.py` | la pestaña Agente: CLIs, su instalación, su registro MCP, el servidor MCP de la instalación, la terminal por websocket |
| `webapp/bandeja.py` | el ícono de la bandeja del sistema |
| `webapp/static/js/views/*.js` | una vista por pestaña; `api.js` es el único que habla con la API; `dom.js` el `h()` |

## Endpoints que importan (prefijo `/api/core`)

| Ruta | Para qué |
|---|---|
| `GET /overview` | resumen |
| `GET/PUT /workflows[/<n>]`, `GET /workflows/<n>/graph` | flujos |
| `POST /validate` | dry run |
| `POST /run` | correr y esperar |
| `POST /runs` → `GET /runs/ticket/<t>` | correr sin esperar |
| `GET /runs`, `GET /runs/<id>`, `GET /runs/en-vuelo`, `GET /logs/<case>` | historial, traza, en vuelo, registro |
| `GET /tools`, `GET /plugins`, `POST /plugins/install`, `GET /plugins/catalog`, `POST /plugins/catalog/install` | plugins |
| `GET/PUT/DELETE /resources/<plugin>/<coleccion>[/<clave>]` | items de colecciones (conexiones, Bots conocidos…) |
| `POST /actions/<plugin>/<accion>` | una Action de plugin (probar, previsualizar) |
| `GET /env`, `PUT /env/<N>` | variables y secretos |
| `GET /updates`, `PUT /updates/config`, `GET /updates/releases`, `POST /updates/install/{tag,upload}`, `POST /updates/revert`, `POST /updates/restart` | actualizaciones |
| `GET /agent`, `GET /agent/providers`, `WS /agent/terminal` | pestaña Agente |

Sin autenticación: la app vive en la red local (`--red`). Exponerla afuera
pide un proxy que la ponga.

## Front

Sin build: `index.html` carga `main.js`, que enruta por hash
(`#sources/...`, `#workflows/<nombre>`, `#/config/<seccion>`, `#agente`,
`#plugins`). Ninguna vista conoce un plugin por nombre: settings,
colecciones y acciones se dibujan desde `GET /tools`. Sondeos: Sources
(`runs/en-vuelo`, 1.5/5 s) y Workflows (lista, 5 s).

El diagrama de un flujo lo dibuja `views/workflows-graph.js` en SVG a mano,
sin librería, con la estética de n8n (lienzo de puntos, cajas con ícono y
nombre adentro, puertos, curvas; el flujo baja como en el `.mmd`). El layout
es Sugiyama (capas por camino más largo, barycenter, nodos fantasma para los
saltos largos). El mismo módulo aloja el dry run: el botón del pie del lienzo
pide `POST /validate` con la fila elegida en **Registro** (una fuente y una
fila, vía `api.filasDeFuente`), y pinta el trace sobre el dibujo sin
reconstruirlo (`actualizarDryRun`, `enfocarNodo` y `actualizarPanel` mutan el
SVG en el lugar para no perder el paneo/zoom). Se edita ahí mismo: "+" en nodos
y aristas (con la lista de tools del manifest), "×" para borrar, arrastrar un
cable o doble clic en un puerto para conectar, y el lápiz de una arista para su
condición; el lienzo sólo describe el gesto (`edicion.*`) y `workflows.js` muta
el grafo con las reglas de la pila (`crearNodo`/`quitarNodo` en
`workflows-cards.js`). El nodo elegido se dibuja **abierto**, con el editor de
`workflows-node-panel.js` adentro en un `foreignObject`: el layout reserva su
tamaño (las medidas van por nodo en `posicion`, y el alto de cada fila es el de
su nodo más alto), así que elegir un nodo sí rearma el dibujo — el encuadre se
guarda y se repone (`obtenerVista`/`aplicarVista`). El render Mermaid
(`views/workflows-mermaid.js`, librería embarcada en `static/vendor`) comparte
el visor (`envolverEnLienzo`) y queda como segunda vista para comparar.

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
| `GET /tools/<tool>/params-extra?<params>` | los params extra que ese tool acepta según lo que el nodo ya tiene elegido |
| `GET /limites`, `PUT /limites/raices`, `PUT /limites/programas` | hasta dónde llega la instalación: carpetas y programas permitidos |
| `GET/PUT/DELETE /resources/<plugin>/<coleccion>[/<clave>]` | items de colecciones (conexiones, Bots conocidos…). Los campos `secret` salen en `None`; un PUT que los manda así conserva el guardado, `""` lo vacía |
| `POST /actions/<plugin>/<accion>` | una Action de plugin (probar, previsualizar). Su resultado puede traer `outputs.vista` y la pantalla lo dibuja: tabla, casillas y una acción de seguimiento |
| `POST /diff`, `POST /migrar` | qué difiere contra otro Bot, y empujarle lo elegido. **Sólo desde la propia máquina**: la pantalla corre acá y un plugin que lo ofrezca corre adentro del propio Bot. `incluir_secretos` arranca en `false` — el item viaja igual y el destino conserva los suyos |
| `POST /migrar/recibir` | el otro lado: abre el sobre cifrado y escribe. Que el sobre abra **es** la autenticación de esta ruta — la única autenticada |
| `GET/POST/DELETE /emparejamientos`, `POST /emparejamientos/importar` | la clave compartida con otro Bot; la pantalla es Config → Emparejamientos. **Sólo desde la propia máquina** (`127.0.0.1`): con esto abierto a la red, cualquiera pediría un código y el sobre dejaría de autenticar. La clave no sale nunca; el código se ve una vez. Abrir el Bot por su IP, aun sentado en esa PC, también da 403 — la pantalla lo explica en vez de mostrar el error |
| `GET /env`, `PUT /env/<N>` | variables y secretos |
| `GET /updates`, `PUT /updates/config`, `GET /updates/releases`, `POST /updates/install/{tag,upload}`, `POST /updates/revert`, `POST /updates/restart` | actualizaciones |
| `GET /agent`, `GET /agent/providers`, `WS /agent/terminal` | pestaña Agente |

Sin autenticación: la app vive en la red local (`--red`). Exponerla afuera
pide un proxy que la ponga.

## Front

Sin build: `index.html` carga `main.js`, que enruta por hash
(`#sources/...`, `#workflows/<nombre>`, `#/config/<seccion>[/<subvista>]`,
`#agente`, `#plugins`). Ninguna vista conoce un plugin por nombre: settings,
colecciones y acciones se dibujan desde `GET /tools`. Una sección que son dos
pantallas se parte con `components/subvistas.js`, y la vista elegida va en la
URL para que un enlace lleve a donde uno quiere. Tipear `{` en un parámetro de
la tarjeta de un nodo abre `components/autocompletar.js` con las salidas de los
nodos de arriba (y quién deja cada una) y los nombres de Config. Sondeos: Sources
(`runs/en-vuelo`, 1.5/5 s) y Workflows (lista, 5 s).

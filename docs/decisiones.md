# Decisiones

Lo que no se deduce leyendo el código: qué se vio roto y qué se eligió.
Cada entrada: contexto → decisión → consecuencia.

## El núcleo no se edita acá
`backend/` es un release de workflow-bot-core, verificado por el hook de
pre-commit. Un cambio del núcleo es un issue allá (core#15 `on_step`,
core#16 root/plugins por defecto en el MCP). Consecuencia: la webapp
envuelve lo que le falta al núcleo (`mcp_servidor.py`, `runs_en_vuelo.py`)
en vez de parcharlo.

## Los plugins no viven en el repo de la app
El `.exe` instala sin plugins; se traen de un catálogo en GitHub con la
forma del índice público más `path` (el código en el repo). Motivo: separar
lo genérico y público de lo de cada cliente, y poder instalar "pelado" en
otra PC. Los plugins son genéricos, con nombre de herramienta, nunca de un
cliente ni de un sistema externo; una llamada HTTP guardada es una Action
de `connections`.

## Lo que carga código corre en otro proceso
Instalar un plugin o un núcleo nuevo se valida con `python -m backend.core
… --json` en un subproceso contra una raíz temporal. Un plugin que se cuelga
al importarse se lleva un proceso descartable, no el servidor. La web app
nueva se **compila** pero no se arranca: arrancarla es abrir la base real.

## Repos de actualización editables, no fijos
El default vive en el código; el valor, en la base por instalación
(`resource webapp/actualizaciones`), como el repo del catálogo. Motivo:
cambiar de repo (privado → público) sin release.

## Correr sin esperar devuelve un ticket, no un run_id
El `run_id` del núcleo existe al final; el ticket, antes de pasar el gate.
`RunsEnVuelo` recuerda los últimos 500 resultados. Consecuencia: otro Bot o
un agente remoto disparan y preguntan, sin conexiones largas.

## Bots que se hablan directo, sin intermediario
Cada Bot ya es una API; el plugin `bots` la usa desde un flujo. Lo que sí
necesita un intermediario es el **reclamo atómico** de un caso entre Bots
que miran la misma lista: eso es un campo en la fuente de datos, no un
canal.

## Sondeo, no websocket
La grilla y la lista de flujos sondean (1.5/5 s). Dos requests livianos
cada pocos segundos resolvieron "no veo lo que disparó otro" sin sumar un
canal de eventos que habría que mantener también en el MCP y en los Bots.

## Agentes: winget, y nunca `irm | iex` desde la app
Defender marcó `powershell -ExecutionPolicy Bypass -Command "irm … | iex"`
lanzado por `pythonw` como `Trojan:Win32/Commando.A!ml` (heurística sobre
el patrón; admin no ayuda, lo empeora). winget es el camino común
(`--source winget`, porque la tienda puede fallar por certificado). Sin
winget: Claude Code se baja y verifica desde Python (SHA256 del manifest +
Authenticode de Anthropic), los otros con el script del vendor. Node no
hace falta para ninguno.

## Los binarios recién instalados se buscan también en el PATH del registro
Un instalador toca el PATH del usuario; el servidor ya corre con el PATH
viejo. `agent_providers.ruta_del_binario` mira `which`, el PATH del
registro y las carpetas conocidas.

## La receta MCP lleva `cwd` y `env`
Claude Code ignora `cwd` en `.mcp.json`; `PYTHONPATH` y `BOT_ROOT` en `env`
lo entienden todos. `python.exe`, no `pythonw.exe`: el servidor MCP habla
por stdio.

## Reiniciar con guardia
Una vez el servidor quedó en "Shutting down" esperando conexiones y nunca
se relanzó. Ahora: cierre prolijo y, a los 8 s, `force_exit`. No
`force_exit` directo: saltea el lifespan y deja un traceback en el registro
en cada reinicio normal.

## Relanzar con `Popen`, no `execv`
En Windows `execv` pega los argumentos sin comillas y una raíz con espacios
llegaba partida. Encontrado en el primer QA.

## Sin Node, sin UAC, sin PyInstaller
El `.exe` trae un CPython relocalizable y instala en el perfil del usuario:
los plugins se descubren con entry points en un site-packages real, y el
instalador corre igual con o sin administrador.

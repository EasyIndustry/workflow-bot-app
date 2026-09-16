# Pendientes

Lo que queda, con el porqué. Sacar de acá lo que se hace y anotarlo en
`estado-del-proyecto.md`.

## Depende del núcleo
- Nada abierto que frene a la webapp: core#15 (`on_step`), #16 (root y
  plugins por defecto en el MCP) y #17 (tools de orientación) llegaron en
  v0.3.1-beta.1. Los issues quedan abiertos hasta verificarlos en la QA y
  cerrarlos desde allá.

## Webapp
- `BOT_ROOT` y `BOT_PORT` en el entorno aparecen como settings fantasma
  `ROOT` y `PORT` en `effective_config` (el núcleo lee `BOT_<CLAVE>` como
  override de un setting). Se vio en `describe_installation` desde la QA.
  Renombrar las variables de la webapp a otro prefijo, y la receta MCP con
  ellas.
- Plantilla "otro Bot" al crear un Source: hoy hay que escribir la URL
  `http://<hijo>/api/core/runs` y el campo clave `run_id` a mano.
- Login a Codex y Antigravity desde la terminal embebida sin probar en
  Windows (los dos son TUI; `pywinpty` está para eso).
- La receta MCP asume código y datos en la misma máquina; un agente remoto
  usa la API HTTP (ver README del plugin `bots`).
- Config → General: puerto, retención de runs, arranque con Windows.
  Diseñada, sin backend.
- Sin autenticación: la app es de red local. Exponerla afuera pide un
  proxy.

## Instalador y releases
- `actions/checkout@v4` y `setup-python@v5` apuntan a Node 20; GitHub los
  corre en 24 y avisa. Subir cuando publiquen las versiones nuevas.
- El `.exe` no está firmado: SmartScreen puede avisar la primera vez.

## Plugins (catálogo)
- `bots`: falta el reclamo atómico para Bots colaborativos con la misma
  lista; es un campo en la fuente de datos (una Action de `connections`),
  no un tool más.
- Sincronía manual entre el catálogo privado y el índice público.

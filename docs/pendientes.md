# Pendientes

Lo que queda, con el porqué. Sacar de acá lo que se hace y anotarlo en
`estado-del-proyecto.md`.

## Depende del núcleo
- Nada abierto que frene a la webapp: core#15 (`on_step`), #16 (root y
  plugins por defecto en el MCP) y #17 (tools de orientación) llegaron en
  v0.3.1-beta.1. Los issues quedan abiertos hasta verificarlos en la QA y
  cerrarlos desde allá.

## Webapp
- **Librerías de plugins, lo que falta**: la pantalla Librerías no muestra
  las huérfanas (instaladas por un plugin ya desinstalado); un botón para
  subir wheels desde el navegador en vez de copiarlas a `wheels/`. El
  camino entero ya se probó con `convertidor` (17/09); falta que pase a
  `cured` (workflow-bot-plugins#1).
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
- **Al llegar a la 1.0, limpiar las prereleases** (decidido el 17/09/2026):
  se borran todas menos la inmediatamente anterior a la oficial, que queda
  como el último paso antes del salto. No es por espacio —los assets de un
  release no cuentan para el tamaño del repo, y un repo público no tiene
  cuota para ellos: al 17/09 son 220 MB en 9 releases contra 1,4 MB de git—,
  es por ruido: `updates.disponibles` lista los últimos 30 y Config →
  Actualizaciones los muestra todos, así que con cuarenta prereleases nadie
  sabe cuál instalar. Lo que se borra es el asset (el `.exe`, 31 MB, casi
  todo el CPython embebido); conviene dejar el release con sus notas, que
  son el historial, y el `.exe` se puede reconstruir del tag si hiciera
  falta.
- `actions/checkout@v4` y `setup-python@v5` apuntan a Node 20; GitHub los
  corre en 24 y avisa. Subir cuando publiquen las versiones nuevas.
- El `.exe` no está firmado: SmartScreen puede avisar la primera vez.
- `Bot.exe` tiene el nombre pero no el ícono: el administrador de tareas lo
  muestra con el de Python. Cambiarlo es escribir los recursos `RT_ICON` /
  `RT_GROUP_ICON` del ejecutable copiado (se puede con `ctypes` y
  `UpdateResource`, sin dependencias nuevas) usando `installer/packaging/bot.ico`.

## Plugins (catálogo)
- `bots`: falta el reclamo atómico para Bots colaborativos con la misma
  lista; es un campo en la fuente de datos (una Action de `connections`),
  no un tool más.
- Sincronía manual entre el catálogo privado y el índice público.

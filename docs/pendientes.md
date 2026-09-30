# Pendientes

Lo que queda, con el porqué. Sacar de acá lo que se hace y anotarlo en
`estado-del-proyecto.md`.

## Depende del núcleo
- **core#26**: que el port `fs` pueda negar subárboles adentro de una raíz,
  armados por el núcleo con lo que sabe de su instalación (su raíz, `data/`,
  `plugins/`). Sin eso, una raíz que contenga la instalación entrega la base,
  la llave, el código de los plugins y —peor— el propio `boot.env`, así que la
  app la rechaza y usar una unidad entera obliga a enumerar carpeta por
  carpeta. Cuando exista: sacar ese rechazo de `webapp/limites.py` y mostrar
  en Inicio qué queda negado.
- **Una fuente declarada que no existe** (core#31): el núcleo no la señala en
  `check_flow`; la app la marca en ámbar en la cabecera del flujo y en el
  helper de la tarjeta. Si hace falta que un agente por MCP lo vea, es un
  issue nuevo en el núcleo.
- **Plug ins → Acciones no pasa por `params-extra`**: los params que un tool
  descubre en runtime (`describe_extra_params`) sólo se dibujan en el editor de
  flujos. Los de `bots` ya no lo necesitan (core#32 los declara), así que hoy
  no hay caso que lo pida.
- Nada abierto que frene a la webapp: core#15 (`on_step`), #16 (root y
  plugins por defecto en el MCP) y #17 (tools de orientación) llegaron en
  v0.3.1-beta.1. Los issues quedan abiertos hasta verificarlos en la QA y
  cerrarlos desde allá.

## Webapp
- **Resaltado de `{variables}` en el JSON de un payload**: hoy sólo en los
  campos de una línea; el textarea envuelve líneas y el espejo tendría que
  copiar ese envolvimiento (`components/resaltar-variables.js`).
- **numpy en el runtime del `.exe`**: el núcleo v0.3.1-beta.10 lo declara como
  dependencia (core#19) pero carga con un adapter nulo si falta; el runtime no
  lo trae. Cuando un plugin lo necesite de verdad, sumarlo al build
  (`installer/packaging/build_win.sh`) y publicar `runtime-release.json`.
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
- Config → General: el nombre de la instalación ya tiene backend
  (`webapp/identidad.py`, 23/09); puerto, retención de runs y arranque con
  Windows siguen diseñados y sin escribir.
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
- `bots`: abrir una pestaña nueva hacia otro Bot conocido y dejar un check
  persistente de "Probar conexión" por fila (23/09) — ver estado-del-proyecto
  del mismo día. Del lado de la app ya está todo: `outputs.abrir_url` en
  cualquier Action de fila abre la pestaña (`plugins.js`), `outputs.indicador`
  se guarda y se dibuja como check (`webapp/indicadores.py`), y `?bot=` en la
  URL titula la pestaña cuando el Bot remoto no se nombró a sí mismo
  (`main.js`). Nada de esto depende de que `bots` esté instalado. Lo que
  falta es sólo del lado del plugin: que sus Actions "probar" y "abrir"
  devuelvan esas dos claves.
- Sincronía manual entre el catálogo privado y el índice público.

# Pendientes

Lo que queda, con el porqué. Sacar de acá lo que se hace y anotarlo en
`estado-del-proyecto.md`.

## Depende del núcleo
- **Progreso por nodo** (core#15, `on_step`): hoy la barra de la grilla es
  indeterminada y `bots.esperar` anota "0/10 · en curso". Cuando llegue, la
  webapp ya lo consume (`run_with_gate` pasa `on_step` si la firma lo
  acepta).
- **MCP con root y plugins por defecto** (core#16): `webapp/mcp_servidor.py`
  queda en un `main()` que pasa los dos datos.

## Webapp
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

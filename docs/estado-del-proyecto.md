# Estado del proyecto

Qué hay hecho y verificado, por fecha. Lo más nuevo arriba. "Verificado"
quiere decir corrido de verdad en una instalación Windows (la QA de
desarrollo o la PC de un cliente), no sólo con tests.

## 2026-09-17

- **Los Bots fantasma.** En la QA aparecieron dos servidores vivos en el mismo
  puerto, de un día para el otro, y el acceso directo dejó de abrir sin decir
  nada (cinco intentos, todos anotados en un `webapp.log` que nadie mira).
  Tres causas, las tres arregladas en `webapp/__main__.py`:
  - `_puerto_libre` preguntaba con un `bind` y `SO_REUSEADDR`, y en Windows
    eso no significa "reusar lo que quedó en TIME_WAIT" sino "quedarse con la
    dirección aunque esté en uso": decía "libre" con un servidor escuchando.
    De ahí salían dos Bots en un puerto. Ahora pregunta con un `connect`, que
    además resuelve el falso positivo que el `SO_REUSEADDR` venía a tapar.
  - Con el puerto ocupado por **otro Bot**, ahora abre la pantalla de ése y
    sale bien: es lo que quería quien hizo doble clic. Si lo ocupa otro
    programa, lo dice con un cartel del sistema, porque sin consola el mensaje
    no llegaba a ningún lado.
  - El hilo del ícono de la bandeja (`pystray.run_detached`) **no es daemon**,
    y el `stop()` estaba envuelto en un `except` que se tragaba cualquier
    error: si fallaba, quedaba un proceso sin servidor, imposible de cerrar
    desde la bandeja —el menú que lo cerraría es el de ese mismo ícono— y que
    sólo se iba con el administrador de tareas. Un guardia daemon baja el
    proceso si a los 6 s sigue vivo.
- **Bot figura como Bot en el administrador de tareas.** Corría con el
  intérprete del runtime, así que aparecía como un `python.exe` más entre
  todos los de la máquina: justo cuando hay que cerrar uno a mano no había con
  qué encontrarlo. El build deja `Bot.exe` y `BotConsola.exe` (copias de
  `pythonw.exe` y `python.exe`), los accesos directos lanzan el primero, y la
  app las crea al vuelo si faltan —una instalación que ya existe actualiza
  `webapp/` y no el runtime, así que si dependiera del instalador las máquinas
  de hoy no lo tendrían nunca—. El ícono propio necesita editar los recursos
  del `.exe`; queda pendiente.
- `python -m webapp --help` moría con `UnicodeEncodeError` en una consola de
  Windows por un `↔` en el texto de ayuda — justo el comando que alguien corre
  cuando la app no abre.
- **Config → Alcance de archivos**: las carpetas que un flujo puede tocar se
  editan desde la app, con alias, sin abrir `boot.env` a mano
  (`webapp/limites.py`, `GET /limites`, `PUT /limites/raices`). Hacía falta
  porque el único camino era editar el archivo en la máquina —fuera del
  alcance de quien opera el Bot, que es el que sabe dónde están los archivos
  de hoy— y porque desde core#22 una raíz que no existe **impide arrancar**,
  así que editarlo a mano pasó a poder dejar la instalación sin levantar. El
  backend valida contra el disco antes de escribir y rechaza lo que no
  arrancaría: una carpeta inexistente, un UNC sin el nombre del recurso
  compartido, un alias repetido, y cualquier raíz que contenga `data/` o
  `plugins/` —esto último el núcleo no lo puede chequear solo, porque `data/`
  no es un valor declarado cuando se usa el default—. Deja `boot.env.anterior`
  al lado y ofrece reiniciar. Con varias raíces, la primera se guarda con
  nombre aunque no se lo hayan puesto: el alias vacío se escribe
  `fs_roots==ruta` y un núcleo anterior a v0.3.1-beta.4 descarta ese par al
  releer, y app y núcleo se actualizan por separado.
- **Los límites de la instalación se ven en Inicio.** `fs_root` era el único
  límite que decidía si un flujo llega a un archivo y el único que no se
  mostraba en ninguna pantalla: en producción se descubrió con un run
  fallando por "ruta fuera del árbol permitido" contra un `fs_root` mal
  escrito. `GET /overview` lo publica e Inicio lo muestra junto a la raíz y a
  `plugins_dir` ("Hasta dónde llega"), con "todo el disco" cuando no está
  declarado.
- **El diagnóstico de la web corría a medias.** `GET /doctor` llamaba a
  `run_checks` sin `boot`, sin `workflows` y sin `crypto`, así que salteaba
  los chequeos que dependen de cada uno: "Flujos" avisaba "no hay ninguno
  guardado" en una instalación con once (falso positivo), y `check_boot`
  —el que dice `fs_root: X no existe`— no corría nunca desde la app (falso
  negativo). Ahora corre completo, e Inicio levanta un aviso con los
  chequeos que no están en ok, con link al detalle.
- **Núcleo v0.3.1-beta.3** vendorizado, con core#22 y core#23, los dos
  abiertos hoy a partir de una instalación de producción cuyo `fs_root`
  apuntaba a un share de red. Verificado acá: una instalación con
  `fs_root=\server-nuevo` ya **no construye la `Instance`** —levanta
  `BootError` diciendo que un UNC necesita el share y no sólo el host— y
  `fs_roots=casa=…, origen=…` en `boot.env` llega hasta el port `fs` con las
  dos raíces: una ruta relativa resuelve contra la primera, `origen:pieza.stl`
  alcanza el share, y lo que cae fuera de las dos sigue dando `PortError`,
  ahora listando las raíces permitidas. Inicio muestra una fila por raíz con
  su alias. Quedan dos cosas menores comentadas en core#23: `render()` escribe
  la raíz sin alias como `fs_roots==ruta` y `load()` la descarta —el viaje de
  ida y vuelta pierde una raíz sin que `validar()` lo note—, y un alias con un
  typo se lee como ruta relativa de la raíz por defecto en vez de fallar.
- **Núcleo v0.3.1-beta.4**: los dos pendientes del punto anterior, arreglados.
  El `boot.env` con `fs_roots` sobrevive al viaje de ida y vuelta sin perder
  la raíz por defecto, y un alias con typo es `PortError` listando los alias
  declarados — con una letra de unidad (`C:\…`) siguiendo tratada como ruta
  y no como alias, que era lo que ese arreglo podía romper.
- **Los avisos de Sources dejaron de empujar la tabla.** Un run que fallaba
  metía un banner entre la cabecera y la grilla: la tabla bajaba sola justo
  cuando estabas por clickear una fila, y el aviso se borraba en el redibujo
  siguiente. Ahora se acumulan por fuente y se despliegan desde el botón
  "Avisos" de la cabecera, en un panel flotante que no mueve nada (contador
  de no leídos, "Limpiar", cierra al clickear afuera). De paso cada aviso
  lleva su tono: un flujo que falla ya no se anuncia con el tilde verde.
- **Arista con condición editable de verdad.** En el formulario de un nodo
  (modo tarjetas y panel del diagrama), el campo "si" de A dónde sigue
  redibujaba la tarjeta en cada tecla y el input perdía el foco al primer
  caracter. Escribe sin redibujar; el rótulo del diagrama se actualiza al
  salir del campo.
- **Núcleo v0.3.1-beta.2** vendorizado: core#18 (`run_action` por item con
  el campo clave; `describe_installation` con actions), core#20
  (`PluginManifest.requires` visible en el catálogo) y core#21 (un param
  JSON recibe la lista/dict del contexto). Verificado en la QA: el plugin
  `convertidor` del catálogo (`draft`) instaló numpy/scipy/rtree/trimesh en
  el runtime 3.12 desde su `requirements.txt` con hash; renombró 50 STL con
  `reescribir_archivos` alimentado por `archivos.buscar` en un solo run
  (antes de #21 hacía falta un run por archivo); `parsear_pts` e
  `inspeccionar_malla` andan con las librerías reales. Primer plugin con
  dependencias de punta a punta.

## 2026-09-16

- **Librerías Python para plugins** (decidido con core#20 y
  workflow-bot-plugins#1). Un plugin trae `requirements.txt` con versión y
  hash fijos; `plugin_install.instalar()` lo instala con pip en el runtime
  del programa —sólo wheels, `--require-hashes`— antes de validar, y si falla
  no copia nada (`webapp/librerias.py`). Sin internet: `wheels/` del plugin
  o de la instalación y la opción "sin internet" al instalar. Plug ins →
  Librerías: runtime, qué pide cada plugin, qué falta, instalar. El build del
  `.exe` deja `runtime-release.json` (Python exacto + librerías base) y el
  workflow lo sube como asset del release; el catálogo pasa
  `compatible_runtime`. `describe_installation` suma `librerias` y el
  resumen dice el runtime y qué falta.
- **Terminal del agente flotante.** La terminal de instalar/loguear un CLI
  salió de la vista Agente a `webapp/static/js/agent_terminal.js`, un
  singleton montado sobre `body` con un indicador fijo en la barra lateral:
  sobrevive al cambio de pestaña mientras un login OAuth tarda. Con un solo
  proveedor instalado, Agente lo abre directo con su acordeón desplegado.
- **Grilla de Sources sin filtrarse por detrás.** El grupo fijo de las
  columnas del bot medía lo que medía su contenido, no la fila: en la fila
  de filtros eran 8px opacos y los selects de los datos asomaban por arriba
  y por abajo (se veía a 1181–1400px de ancho). `align-self: stretch` en
  `.tabla__grupo-fijo`; verificado por CDP a 1360/1280/1100.
- **Filtros en las columnas del bot** (Estado, Últ. ejec., Flujo, marca):
  filtran las filas de la página ya cargada, sin releer la fuente, porque
  ese estado no está en la API sino en el bot; la nota de la barra lo dice
  cuando hay uno activo. La marca de selección pasó al final de la fila.
- **Núcleo v0.3.1-beta.1** vendorizado (desde v0.3.0-beta.4): trae core#15
  (`on_step`: la barra de la columna Log pasa a ser por nodo; `run_with_gate`
  ya lo pasaba), core#16 (`default_root`/`default_plugins` en el MCP) y
  core#17 (`describe_installation`, `list_flows`/`get_flow`,
  `list_runs`/`get_run`/`get_case_log`, `write_resource_item`/
  `delete_resource_item`, instrucciones que arrancan por la orientación,
  `extra_tools`/`extra_handlers`/`instructions_extra`).
- **Manual agéntico.** La app deja `AGENTS.md` (+ `CLAUDE.md` → `@AGENTS.md`)
  en la carpeta de la instalación y lo regenera al arrancar y al cambiar
  flujos, plugins o colecciones (`webapp/contexto_agente.py`); contra el
  repo no se genera. `webapp/mcp_servidor.py` quedó en pasar al núcleo
  `default_root`, `default_plugins` y lo propio de la app:
  `describe_installation` enriquecido con `fuentes` y `notas`,
  `preview_source`, y `write/delete_resource_item` envueltos para
  regenerar el manual. Plugin local `conocimiento` con la colección `notas`
  (Plug ins → Conocimiento), que el agente también escribe.
- **Panel lateral plegable**: « junto a FLOW-BOT lo deja en una franja de
  38px con la marca sola, que lo vuelve a abrir; se recuerda en
  `localStorage` del navegador (`lateral-plegado`).
- **Bots que se hablan.** `POST /runs` corre un flujo sin esperar y
  devuelve un ticket; `GET /runs/ticket/<t>` dice en cola / en vuelo (con
  paso) / terminado (con el run). Plugin `bots` en el catálogo (`estado`,
  `elegir_libre`, `correr`, `esperar`, colección *Bots conocidos* con
  *Probar*). Verificado: un flujo padre eligió un Bot, derivó un caso con
  ticket y esperó el resultado; el hijo corrió con source `bot:<caso>`.
- **Sondeo permanente.** Sources mira `runs/en-vuelo` siempre (1.5 s con
  algo corriendo, 5 s sin nada); Workflows relee la lista cada 5 s. Un run
  o un flujo que dispara otro Bot, un agente remoto u otra pestaña se ve
  sin recargar.
- **Agentes sin Node, sin `irm | iex`.** Windows Defender marcaba el
  instalador oficial de Claude Code lanzado desde la app como
  `Trojan:Win32/Commando.A!ml` (heurística sobre "PowerShell baja y
  ejecuta"). Los tres CLIs se instalan con **winget** (`--source winget`,
  porque la tienda fallaba con certificado en la PC del cliente); sin
  winget, Claude Code se baja y verifica (SHA256 + Authenticode) desde
  `webapp/instalar_agente.py`; "Manual / otro" instala cualquier id de
  winget. Verificado: `OpenAI.Codex` 0.152.0 instalado desde la fila Manual.
- **Ícono propio** (`installer/packaging/bot.ico`) en instalador, accesos
  directos y buscador de Windows; casilla "ícono en el escritorio" al
  terminar de instalar.
- **Instalador como asset del release**: `.github/workflows/release.yml`
  construye `BotSetup-<versión>.exe` al publicar un release. Verificado con
  `v0.4.1-beta.2`, `beta.3` y `beta.4`.
- Repo abierto nacido de Bot-Produccion (15/09 tarde): sin plugins, sin
  referencias a la empresa. Primer release `v0.4.1-beta.1`.

## 2026-09-15

- **Actualizaciones de la web app** además del núcleo, con los repos
  editables por instalación (Config → Actualizaciones). Verificado dos veces
  seguidas por la ruta sin internet y una desde GitHub con token.
- **MCP desde una instalación**: `webapp/mcp_servidor.py` envuelve
  `backend.mcp` con `root` = la instalación y `connections` cargado; la
  receta lleva `cwd` y `env.PYTHONPATH`/`BOT_ROOT` (Claude Code ignora
  `cwd`). Verificado con `claude -p` desde el `.mcp.json` que deja el login
  en la terminal embebida. Core#16 pide absorberlo.
- Workflows: filtro de la pila junto a "Nodos", "Buscar nodo…" junto a
  "Diagrama", "Ubicar" por tarjeta; abrir una tarjeta ya no abre el panel
  flotante.
- Guardia al reiniciar: si a los 8 s el servidor no salió, `force_exit`.

## 2026-09-14 (todavía en Bot-Produccion)

- Plugins en línea desde un catálogo en GitHub (rama por instalación,
  `.procedencia.json`); el `.exe` instala sin plugins.
- Ícono de bandeja (`webapp/bandeja.py`) y `--red` para operar desde otra
  PC; verificado LAN.
- Barra de progreso en la columna Log (`GET /runs/en-vuelo`); indeterminada
  hasta core#15 (`on_step`).
- ToothFORM por línea de comandos (plugin `toothform`, flujo V3), en el
  catálogo privado.

## Antes

Núcleo v0.3.0-beta.4 vendorizado; wizard de instalación; Sources con
grilla, filtros y ejecución por fila o lote; Workflows en tarjetas/texto con
diagrama y dry run; Config con secretos, límites, base de datos, actores y
actualizaciones del núcleo; pestaña Agente con terminal embebida.

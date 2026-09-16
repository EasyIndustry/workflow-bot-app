# Estado del proyecto

Qué hay hecho y verificado, por fecha. Lo más nuevo arriba. "Verificado"
quiere decir corrido de verdad en una instalación Windows (la QA de
desarrollo o la PC de un cliente), no sólo con tests.

## 2026-09-16

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

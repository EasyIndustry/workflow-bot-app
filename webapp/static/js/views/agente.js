/**
 * Agente: cómo conectar un agente MCP a esta instalación, y una terminal
 * embebida para instalar/loguear un proveedor de CLI.
 *
 * `backend/mcp` es un servidor por stdio — lo levanta el cliente del agente
 * (Claude Desktop, Claude Code, Cursor, Codex, cualquiera que hable MCP), no
 * esta webapp. Por eso esta pantalla no tiene un estado "conectado": es la
 * receta para que ese cliente lo levante él mismo. Acá también vive el wizard
 * de instalar/loguear un proveedor — una terminal embebida (xterm.js, cargado
 * del CDN al abrirla) contra un proceso real del lado del servidor. El
 * servidor sólo corre los argv fijos que declara `agent_providers.py`; esta
 * vista nunca arma un comando, sólo elige cuál proveedor y cuál modo.
 *
 * La terminal vive en una columna fija a la derecha (arrastrable, ancho
 * recordado en localStorage), ocupando toda la altura de la pantalla — no un
 * cuadro que aparece metido en el medio del texto. La idea original —y a la
 * que se vuelve acá— es que la única interfaz de interacción con el agente
 * sea esta terminal, corriendo el CLI real, no una UI de chat propia encima
 * (eso existió y se sacó).
 *
 * Cada proveedor es un acordeón: clic en la fila para ver su configuración
 * particular (el bloque JSON/TOML para pegar a mano, si `formato_config` no
 * es vacío) y dejar notas propias (modelo, skills, lo que sea — guardado por
 * proveedor vía `agent_provider_config.py`). Para Claude Code, Codex y
 * Antigravity ni hace falta copiar nada: `mcp_registration.py` escribe la
 * conexión sola apenas termina un install/login exitoso.
 */

import { h, poner } from "../dom.js";
import { api } from "../api.js";
import { aviso } from "../components/aviso.js";

let shell = null;
let sesionActiva = null; // { ws, limpiar, providerId, modo }
let xtermCargando = null;

export async function montar(elShell) {
  shell = elShell;
  shell.ponerRotulo("AGENTE");
  shell.limpiarLateral();

  cerrarSesionActiva();
  poner(shell.vista, h("div", { class: "cargando", text: "Cargando…" }));

  let conexion;
  let proveedores;
  try {
    [conexion, proveedores] = await Promise.all([api.agente(), api.agentProveedores()]);
  } catch (e) {
    poner(shell.vista, aviso("error", "No se pudo leer la configuración", e.message || String(e)));
    return;
  }

  await dibujarPantalla(conexion, proveedores.providers || []);
}

// ── Clientes MCP que no son "proveedores" (no hay CLI que instalar/loguear) ─

const OTROS_CLIENTES = [
  { nombre: "Claude Desktop", donde: "Config → Developer → Edit Config" },
  { nombre: "Cursor", donde: "`.cursor/mcp.json`, en el proyecto o en tu carpeta de usuario" },
];

function seccionOtrosClientes(datos) {
  const bloqueJson = JSON.stringify({ mcpServers: { bot: datos.connection } }, null, 2);
  return [
    h("div", { class: "seccion" }, [h("span", { text: "OTROS CLIENTES MCP" })]),
    h("div", { class: "campo__ayuda" }, [
      "No tienen una CLI que esta pantalla pueda instalar o loguear — pegales esto a mano.",
    ]),
    h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [bloqueJson]),
    botonCopiar(() => bloqueJson),
    ...OTROS_CLIENTES.map((c) =>
      h("div", { style: { display: "flex", gap: "12px", padding: "6px 0" } }, [
        h("span", { style: { fontWeight: "600", width: "140px", flex: "0 0 140px" }, text: c.nombre }),
        h("span", { class: "campo__ayuda", style: { margin: 0 }, text: c.donde }),
      ]),
    ),
  ];
}

// ── Bloque de config particular de un proveedor (JSON o TOML) ───────────
//
// Cada proveedor lee la conexión en un lugar y una sintaxis distinta — Claude
// Code y "Manual" en JSON (`mcpServers`), Codex en TOML (`.codex/config.toml`,
// confirmado contra developers.openai.com/codex) — por eso el formato sale de
// `p.formato_config` (agent_providers.py) en vez de asumir uno solo. Antigravity
// no tiene ninguno documentado (`formato_config: ""`): sólo sabe `agy mcp add`.

function bloqueToml(conexion) {
  const escapar = (s) => String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const args = conexion.args.map((a) => `"${escapar(a)}"`).join(", ");
  return [
    "[mcp_servers.bot]",
    `command = "${escapar(conexion.command)}"`,
    `args = [${args}]`,
    `cwd = "${escapar(conexion.cwd)}"`,
  ].join("\n");
}

function bloqueConfigProveedor(p, conexion) {
  if (p.formato_config === "toml") {
    return [
      h("div", { class: "campo__ayuda" }, [
        "Codex no lee `.mcp.json` — busca esto en ",
        h("span", { class: "mono", text: "~/.codex/config.toml" }),
        " (o ",
        h("span", { class: "mono", text: ".codex/config.toml" }),
        " en la raíz del proyecto, si Codex confía en esta carpeta).",
      ]),
      h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [bloqueToml(conexion)]),
      botonCopiar(() => bloqueToml(conexion)),
    ];
  }
  if (p.formato_config === "json") {
    const bloque = JSON.stringify({ mcpServers: { bot: conexion } }, null, 2);
    return [
      h("pre", { class: "bloque-codigo" }, [bloque]),
      botonCopiar(() => bloque),
    ];
  }
  return [];
}

// ── Pantalla: configuración (izquierda) + terminal fija (derecha) ────────

async function dibujarPantalla(datos, proveedores) {
  const terminalCuerpo = h("div", { class: "agente-terminal__cuerpo" });
  dibujarTerminalVacia(terminalCuerpo);

  let herramientasPermitidas = "";
  try {
    herramientasPermitidas = (await api.agentHerramientasPermitidas()).allowed_tools || "";
  } catch { /* si falla, la sección arranca vacía y guardar la vuelve a intentar */ }

  const columnaConfig = h("div", { class: "agente-layout__config" }, [
    h("div", { style: { marginBottom: "16px" } }, [
      h("div", { class: "titulo", text: "Agente" }),
      h("div", { class: "subtitulo" }, [
        "Cualquier agente que hable MCP puede leer y escribir workflows, y " +
          "autorar, validar e instalar plugins acá. Lo levanta el cliente del " +
          "agente, no esta pantalla — no hay un \"conectado\" que mostrar, sólo " +
          "la configuración para pegar en el tuyo.",
      ]),
    ]),

    !datos.mcp_instalado
      ? aviso(
          "falta",
          "Falta el paquete mcp",
          "python -m webapp.mcp_servidor no va a arrancar hasta instalarlo en este entorno: pip install mcp",
        )
      : null,

    h("div", { class: "seccion" }, [h("span", { text: "PROVEEDORES DE CLI" })]),
    h("div", { class: "campo__ayuda" }, [
      "Instalá y logueá el CLI de un proveedor — se abre en la terminal de la derecha. " +
        "Corre en esta misma máquina, con tus propios permisos de usuario — nunca con sudo ni admin. " +
        "Hacé clic en un proveedor para ver su configuración particular y dejar notas.",
    ]),
    h("div", { class: "tarjeta", style: { marginTop: "8px" } },
      proveedores.map((p) => filaProveedor(p, terminalCuerpo, datos.connection)),
    ),

    ...seccionOtrosClientes(datos),

    h("div", { class: "seccion" }, [h("span", { text: "ROOT DE ESTA INSTALACIÓN" })]),
    h("div", { class: "campo__ayuda" }, [
      "No va en ninguna configuración de conexión: cada tool del MCP lo recibe " +
        "como argumento propio, en cada llamada (salvo Codex, que ya lo tiene como ",
      h("span", { class: "mono", text: "cwd" }),
      "). Pasáselo igual al agente —en su prompt, o donde tu cliente permita fijar " +
        "contexto— para que trabaje contra ",
      h("span", { class: "mono", text: "esta" }),
      " instalación y no contra un checkout de desarrollo.",
    ]),
    h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [datos.root]),
    botonCopiar(() => datos.root),

    h("div", { class: "seccion" }, [h("span", { text: "HERRAMIENTAS SIEMPRE PERMITIDAS" })]),
    h("div", { class: "campo__ayuda" }, [
      "Se auto-aprueban en toda sesión nueva, sin volver a preguntar — es " +
        "`--allowedTools` del CLI. Separadas por coma; un patrón entre paréntesis las acota " +
        "más, ej. ",
      h("span", { class: "mono", text: 'Bash(git *)' }),
      ".",
    ]),
    seccionHerramientasPermitidas(herramientasPermitidas),
  ]);

  const columnaTerminal = h("div", { class: "agente-layout__terminal" }, [
    h("div", { class: "agente-terminal__cabecera" }, [
      h("span", { text: "TERMINAL" }),
    ]),
    terminalCuerpo,
  ]);
  columnaTerminal.style.flexBasis = anchoTerminalGuardado() + "px";

  const resizer = h("div", { class: "agente-layout__resizer", title: "Arrastrar para cambiar el ancho" });
  activarResize(resizer, columnaTerminal);

  poner(shell.vista, h("div", { class: "agente-layout" }, [columnaConfig, resizer, columnaTerminal]));
}

// ── Ancho de la columna de terminal, arrastrable y recordado ────────────

const ANCHO_MIN = 280;
const ANCHO_MAX = 900;
const ANCHO_DEFECTO = 440;
const CLAVE_ANCHO = "agente.anchoTerminal";

function anchoTerminalGuardado() {
  const guardado = Number(localStorage.getItem(CLAVE_ANCHO));
  if (!guardado || Number.isNaN(guardado)) return ANCHO_DEFECTO;
  return Math.min(ANCHO_MAX, Math.max(ANCHO_MIN, guardado));
}

/**
 * Arrastrar el separador cambia el ancho de la columna de terminal, no la de
 * config —la columna de config ya se banca cualquier ancho porque scrollea
 * sola, y es la terminal la que tiene un tamaño de grilla (cols/rows) que vale
 * la pena poder agrandar o achicar. El `ResizeObserver` que ya escucha a la
 * pantalla de xterm (ver `abrirTerminal`) hace el resto: cada frame de este
 * arrastre dispara un `fit()` y un resize real de la sesión, no sólo al soltar.
 */
function activarResize(resizer, columnaTerminal) {
  let arrancoEnX = 0;
  let anchoAlArrancar = 0;

  const mover = (e) => {
    const delta = arrancoEnX - e.clientX; // la terminal está a la derecha: mover a la izquierda agranda
    const nuevoAncho = Math.min(ANCHO_MAX, Math.max(ANCHO_MIN, anchoAlArrancar + delta));
    columnaTerminal.style.flexBasis = nuevoAncho + "px";
  };

  const soltar = () => {
    document.removeEventListener("mousemove", mover);
    document.removeEventListener("mouseup", soltar);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    localStorage.setItem(CLAVE_ANCHO, parseInt(columnaTerminal.style.flexBasis, 10));
  };

  resizer.addEventListener("mousedown", (e) => {
    e.preventDefault();
    arrancoEnX = e.clientX;
    anchoAlArrancar = columnaTerminal.getBoundingClientRect().width;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", mover);
    document.addEventListener("mouseup", soltar);
  });
}

function seccionHerramientasPermitidas(valorInicial) {
  const input = h("input", {
    class: "entrada entrada--mono", type: "text", value: valorInicial,
    placeholder: "ej: Bash, WebFetch",
  });
  const btnGuardar = h("button", { class: "btn btn--chico", text: "Guardar" });
  const estado = h("span", { class: "campo__ayuda", style: { margin: "0 0 0 8px" } });

  const guardar = async () => {
    btnGuardar.disabled = true;
    estado.textContent = "Guardando…";
    try {
      const guardado = await api.guardarAgentHerramientasPermitidas(input.value.trim());
      input.value = guardado.allowed_tools;
      estado.textContent = "✓ Guardado — vale desde la próxima sesión.";
    } catch (e) {
      estado.textContent = "✕ " + (e.message || String(e));
    } finally {
      btnGuardar.disabled = false;
    }
  };
  btnGuardar.addEventListener("click", guardar);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); guardar(); } });

  return h("div", { class: "fila-control", style: { marginTop: "8px" } }, [input, btnGuardar, estado]);
}

function filaProveedor(p, terminalCuerpo, conexion) {
  const botones = [];
  if (p.automatizable) {
    if (!p.instalado) {
      const btn = h("button", {
        class: "btn btn--chico",
        text: "Instalar",
        disabled: !p.se_puede_instalar,
        title: p.se_puede_instalar ? "" : "Hace falta PowerShell (o bash) en esta máquina para correr el instalador del proveedor",
      });
      btn.addEventListener("click", (e) => { e.stopPropagation(); abrirTerminal(terminalCuerpo, p.id, "install"); });
      botones.push(btn);
    } else {
      const btnLogin = h("button", { class: "btn btn--chico btn--azul", text: "Iniciar sesión" });
      btnLogin.addEventListener("click", (e) => { e.stopPropagation(); abrirTerminal(terminalCuerpo, p.id, "login"); });
      botones.push(btnLogin);
    }
  }

  const flecha = h("span", { class: "acordeon__flecha", text: "▸" });
  const panel = h("div", { class: "acordeon__panel", hidden: true });
  let cargado = false;

  const encabezado = h("div", {
    class: "campo campo--clickeable",
    style: { alignItems: "center" },
    onClick: () => alternarPanel(),
  }, [
    flecha,
    h("div", { class: "campo__etiqueta", style: { width: "160px", flex: "0 0 160px" } }, [
      h("div", { class: "campo__nombre", text: p.label }),
    ]),
    h("div", { class: "campo__control" }, [
      h("span", {
        class: "badge " + (p.instalado ? "badge--ok" : "badge--falta"),
        text: p.automatizable ? (p.instalado ? "instalado" : "no instalado") : "sin automatizar",
      }),
      h("div", { class: "campo__ayuda", text: p.doc }),
    ]),
    h("div", { style: { display: "flex", gap: "6px" }, onClick: (e) => e.stopPropagation() }, botones),
  ]);

  function alternarPanel() {
    panel.hidden = !panel.hidden;
    flecha.textContent = panel.hidden ? "▸" : "▾";
    if (!panel.hidden && !cargado) {
      cargado = true;
      poner(panel, ...panelProveedor(p, conexion));
    }
  }

  return h("div", { class: "acordeon" }, [encabezado, panel]);
}

function panelProveedor(p, conexion) {
  const notasArea = h("textarea", {
    class: "entrada entrada--area", placeholder: "Modelo a usar, qué le sirve mejor, cualquier recordatorio…",
  });
  const btnGuardarNotas = h("button", { class: "btn btn--chico", text: "Guardar" });
  const estadoNotas = h("span", { class: "campo__ayuda", style: { margin: "0 0 0 8px" } });

  api.agentProveedorConfig(p.id)
    .then((cfg) => { notasArea.value = cfg.notas || ""; })
    .catch(() => { estadoNotas.textContent = "No se pudieron leer las notas guardadas."; });

  btnGuardarNotas.addEventListener("click", async () => {
    btnGuardarNotas.disabled = true;
    estadoNotas.textContent = "Guardando…";
    try {
      await api.guardarAgentProveedorConfig(p.id, notasArea.value);
      estadoNotas.textContent = "✓ Guardado";
    } catch (e) {
      estadoNotas.textContent = "✕ " + (e.message || String(e));
    } finally {
      btnGuardarNotas.disabled = false;
    }
  });

  const bloques = [];

  if (p.auto_registro) {
    bloques.push(aviso(
      "ok",
      "Se registra sola",
      "Al instalar o iniciar sesión arriba, esta instalación queda dada de alta como servidor MCP " +
        "de este proveedor — no hace falta pegar nada a mano.",
    ));
  }

  const bloqueConfig = bloqueConfigProveedor(p, conexion);
  if (bloqueConfig.length) {
    bloques.push(
      h("div", { class: "seccion", style: { marginTop: p.auto_registro ? "10px" : "0" } }, [
        h("span", { text: p.auto_registro ? "O PEGALA A MANO" : "CONFIGURACIÓN DE CONEXIÓN" }),
      ]),
      ...bloqueConfig,
    );
  }

  bloques.push(
    h("div", { class: "seccion", style: { marginTop: "10px" } }, [h("span", { text: "NOTAS / SKILLS" })]),
    h("div", { class: "fila-control", style: { marginTop: "4px", alignItems: "flex-start" } }, [notasArea]),
    h("div", { style: { marginTop: "4px" } }, [btnGuardarNotas, estadoNotas]),
  );

  return bloques;
}

// ── Terminal embebida (instalar / loguear) ──────────────────────────────

function cargarXterm() {
  if (window.Terminal && window.FitAddon) return Promise.resolve();
  if (xtermCargando) return xtermCargando;

  const cargarScript = (src) => new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`no se pudo cargar ${src} desde el CDN`));
    document.head.appendChild(script);
  });

  xtermCargando = (async () => {
    const hoja = h("link", {
      rel: "stylesheet",
      href: "https://cdnjs.cloudflare.com/ajax/libs/xterm/5.5.0/xterm.min.css",
    });
    document.head.appendChild(hoja);

    // cdnjs dejó de publicar `xterm.min.js` desde la 5.4.0 en adelante — sólo
    // queda el bundle sin minificar (`xterm.js`), misma API UMD (`window.Terminal`).
    await cargarScript("https://cdnjs.cloudflare.com/ajax/libs/xterm/5.5.0/xterm.js");
    // El addon de auto-ajuste no está en cdnjs (nunca lo publicaron): jsdelivr
    // sirve el mismo paquete de npm tal cual. Sin esto la terminal queda fija
    // en 80x24 aunque la columna de al lado sea más grande o más chica.
    await cargarScript("https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js");
  })();
  return xtermCargando;
}

function cerrarSesionActiva() {
  if (!sesionActiva) return;
  try { sesionActiva.observador?.disconnect(); } catch { /* ya estaba desconectado */ }
  try { sesionActiva.ws.close(); } catch { /* ya estaba cerrado */ }
  try { sesionActiva.limpiar?.(); } catch { /* ya estaba destruido */ }
  sesionActiva = null;
}

function wsUrl(providerId, modo) {
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${location.host}/api/core/agent/terminal` +
    `?provider=${encodeURIComponent(providerId)}&mode=${encodeURIComponent(modo)}&actor=agente-mcp`;
}

function dibujarTerminalVacia(terminalCuerpo) {
  poner(terminalCuerpo, h("div", {
    class: "agente-terminal__vacio",
    text: "Elegí \"Instalar\" o \"Iniciar sesión\" en un proveedor para abrir la terminal acá.",
  }));
}

async function abrirTerminal(terminalCuerpo, providerId, modo) {
  cerrarSesionActiva();

  const estado = h("div", { class: "campo__ayuda", text: "Cargando la terminal…" });
  poner(terminalCuerpo, estado);

  try {
    await cargarXterm();
  } catch (e) {
    poner(terminalCuerpo, aviso("error", "No se pudo abrir la terminal", e.message));
    return;
  }

  const pantalla = h("div", { class: "terminal-embebida" });
  const cerrar = h("button", { class: "btn btn--chico", text: "Cerrar", style: { marginTop: "8px", flex: "0 0 auto" } });
  cerrar.addEventListener("click", () => { cerrarSesionActiva(); dibujarTerminalVacia(terminalCuerpo); });
  poner(terminalCuerpo, estado, pantalla, cerrar);

  const term = new window.Terminal({ convertEol: true, fontSize: 13 });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(pantalla);
  fit.fit();

  const ws = new WebSocket(wsUrl(providerId, modo));
  ws.binaryType = "arraybuffer";

  const enviarResize = () => {
    if (ws.readyState !== WebSocket.OPEN) return;
    try { fit.fit(); } catch { /* la pantalla puede no tener tamaño todavía (recién montada) */ }
    ws.send(JSON.stringify({ resize: { rows: term.rows, cols: term.cols } }));
  };
  // La columna de la terminal ocupa toda la altura fija de la pantalla, así que
  // el único motivo por el que su tamaño cambia es que alguien redimensione la
  // ventana del navegador — no hay splitter que arrastrar acá.
  const observador = new ResizeObserver(() => enviarResize());
  observador.observe(pantalla);

  sesionActiva = { ws, observador, limpiar: () => term.dispose(), providerId, modo };

  ws.addEventListener("open", () => {
    estado.textContent = modo === "install" ? "Instalando…" : "Iniciando sesión…";
    enviarResize();
  });

  ws.addEventListener("message", (evento) => {
    if (typeof evento.data === "string") {
      let control = null;
      try { control = JSON.parse(evento.data); } catch { /* texto suelto, se ignora */ }
      if (control?.aviso) estado.textContent = "⚠ " + control.aviso;
      else if (control?.error) estado.textContent = "✕ " + control.error;
      return;
    }
    term.write(new Uint8Array(evento.data));
  });

  ws.addEventListener("close", () => {
    // No se pisa el texto: puede traer el aviso de auto-registro que mandó el
    // servidor justo antes de cerrar (ver `agent_terminal_ws`) — perderlo acá
    // sería que nadie llegue a leer "✓ Registrado en .mcp.json".
    estado.textContent = (estado.textContent ? estado.textContent + " · " : "") + "Sesión terminada.";
    // Si fue una instalación, el estado de "instalado" pudo haber cambiado —
    // se refresca la pantalla entera para que la fila pase a ofrecer login.
    // Con demora: sin esto, el aviso de arriba desaparece antes de poder leerlo.
    if (modo === "install") setTimeout(() => montar(shell), 2500);
  });

  ws.addEventListener("error", () => {
    estado.textContent = "Error de conexión con el servidor.";
  });

  term.onData((datos) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(datos));
  });
}

// ── Compartido ────────────────────────────────────────────────────────

function botonCopiar(obtenerTexto) {
  const boton = h("button", { class: "btn", style: { marginTop: "8px" }, text: "Copiar" });
  boton.addEventListener("click", () => copiar(boton, obtenerTexto()));
  return boton;
}

async function copiar(boton, texto) {
  const original = boton.textContent;
  try {
    await navigator.clipboard.writeText(texto);
    boton.textContent = "✓ Copiado";
  } catch {
    // Sin permiso de portapapeles —o sin HTTPS en algunos navegadores— se cae a
    // seleccionar el texto, que es peor pero funciona en todos lados.
    const area = h("textarea", { value: texto, style: { position: "fixed", top: "-1000px" } });
    document.body.appendChild(area);
    area.select();
    boton.textContent = document.execCommand("copy") ? "✓ Copiado" : "No se pudo copiar";
    area.remove();
  }
  setTimeout(() => { boton.textContent = original; }, 1500);
}

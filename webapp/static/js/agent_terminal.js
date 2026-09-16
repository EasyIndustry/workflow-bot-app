/**
 * La sesión de terminal del agente (instalar/loguear un proveedor de CLI),
 * como singleton independiente de qué vista está montada.
 *
 * Antes vivía adentro de `views/agente.js`: se creaba y se destruía con la
 * vista, así que salir de la pestaña Agente (o incluso volver a entrar)
 * mataba la sesión — un problema real cuando un login es un OAuth que tarda
 * y el usuario quiere mirar otra pestaña mientras espera. Este módulo se
 * importa una sola vez (desde `main.js`) y guarda el WebSocket, la instancia
 * de xterm y el panel flotante en variables de módulo: sobreviven a cualquier
 * cambio de ruta porque nadie los cuelga de `shell.vista`, que el router vacía
 * en cada navegación.
 *
 * El panel flotante se monta una sola vez, directo sobre `document.body`
 * (fuera del árbol que arma `shell.js`), y un indicador fijo en la barra
 * lateral (`shell.indicadorTerminal`, que `limpiarLateral()` no toca) permite
 * abrirlo o esconderlo desde cualquier pestaña sin tocar la sesión de abajo.
 */

import { h, poner } from "./dom.js";
import { aviso } from "./components/aviso.js";

let xtermCargando = null;

let ws = null;
let term = null;
let fit = null;
let observador = null;
let providerActivo = null; // { id, modo }

let panel = null; // el flotante entero
let pantalla = null; // donde xterm pinta
let estadoEl = null;
let indicadorMontado = false;
let indicadorPill = null;
let listener = null; // callback de la vista actualmente montada, ver `escuchar`

/** La vista activa se suscribe para saber cuándo abrir/cerrar/cambiar el estado. */
export function escuchar(cb) {
  listener = cb;
}

function avisarCambio() {
  if (listener) listener(estado());
}

export function estado() {
  return { activa: Boolean(ws), providerId: providerActivo?.id ?? null, modo: providerActivo?.modo ?? null };
}

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
    // sirve el mismo paquete de npm tal cual.
    await cargarScript("https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js");
  })();
  return xtermCargando;
}

function wsUrl(providerId, modo, paquete) {
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${location.host}/api/core/agent/terminal` +
    `?provider=${encodeURIComponent(providerId)}&mode=${encodeURIComponent(modo)}&actor=agente-mcp` +
    (paquete ? `&paquete=${encodeURIComponent(paquete)}` : "");
}

// ── Ancho del panel, arrastrable y recordado ────────────────────────────

const ANCHO_MIN = 320;
const ANCHO_MAX = 900;
const ANCHO_DEFECTO = 640;
const CLAVE_ANCHO = "agente.anchoTerminal";

function anchoGuardado() {
  const guardado = Number(localStorage.getItem(CLAVE_ANCHO));
  if (!guardado || Number.isNaN(guardado)) return ANCHO_DEFECTO;
  return Math.min(ANCHO_MAX, Math.max(ANCHO_MIN, guardado));
}

/**
 * El panel está anclado a la derecha (`right: 0`) — arrastrar el separador
 * hacia la izquierda lo agranda, hacia la derecha lo achica. Mismo cálculo
 * que tenía la columna vieja, ahora sobre un `width` en vez de un `flexBasis`
 * porque el panel es `position: fixed`, no parte del flujo de `.vista`.
 */
function activarResize(resizer) {
  let arrancoEnX = 0;
  let anchoAlArrancar = 0;

  const mover = (e) => {
    const delta = arrancoEnX - e.clientX;
    const nuevoAncho = Math.min(ANCHO_MAX, Math.max(ANCHO_MIN, anchoAlArrancar + delta));
    panel.style.width = nuevoAncho + "px";
  };

  const soltar = () => {
    document.removeEventListener("mousemove", mover);
    document.removeEventListener("mouseup", soltar);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    localStorage.setItem(CLAVE_ANCHO, parseInt(panel.style.width, 10));
  };

  resizer.addEventListener("mousedown", (e) => {
    e.preventDefault();
    arrancoEnX = e.clientX;
    anchoAlArrancar = panel.getBoundingClientRect().width;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", mover);
    document.addEventListener("mouseup", soltar);
  });
}

/** Crea el panel flotante y el indicador la primera vez que hacen falta. */
function asegurarChrome(shell) {
  if (panel) return;

  pantalla = h("div", { class: "terminal-embebida" });
  estadoEl = h("div", { class: "campo__ayuda", text: "" });
  const btnEsconder = h("button", { class: "btn btn--chico", text: "Esconder" });
  const btnCerrar = h("button", { class: "btn btn--chico", text: "Cerrar sesión" });
  btnEsconder.addEventListener("click", () => ocultarPanel());
  btnCerrar.addEventListener("click", () => cerrar());

  const resizer = h("div", { class: "terminal-flotante__resizer", title: "Arrastrar para cambiar el ancho" });
  const columna = h("div", { class: "terminal-flotante__columna" }, [
    h("div", { class: "terminal-flotante__cabecera" }, [
      h("span", { class: "terminal-flotante__titulo" }),
      h("div", { style: { display: "flex", gap: "6px" } }, [btnEsconder, btnCerrar]),
    ]),
    h("div", { class: "terminal-flotante__cuerpo" }, [estadoEl, pantalla]),
  ]);

  panel = h("div", { class: "terminal-flotante", hidden: true }, [resizer, columna]);
  panel.style.width = anchoGuardado() + "px";
  document.body.appendChild(panel);
  activarResize(resizer);

  observador = new ResizeObserver(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try { fit?.fit(); } catch { /* la pantalla puede no tener tamaño todavía */ }
    ws.send(JSON.stringify({ resize: { rows: term.rows, cols: term.cols } }));
  });
  observador.observe(pantalla);

  montarIndicador(shell);
}

function montarIndicador(shell) {
  if (indicadorMontado) return;
  indicadorMontado = true;
  indicadorPill = h("div", { class: "indicador-terminal", hidden: true, onClick: () => alternarPanel() }, [
    h("span", { class: "indicador-terminal__punto" }),
    h("span", { class: "indicador-terminal__texto" }),
  ]);
  poner(shell.indicadorTerminal, indicadorPill);
}

function refrescarIndicador() {
  if (!indicadorPill) return;
  indicadorPill.hidden = !providerActivo;
  if (providerActivo) {
    indicadorPill.querySelector(".indicador-terminal__texto").textContent =
      `Terminal: ${providerActivo.id}`;
  }
}

function refrescarTitulo() {
  const titulo = panel.querySelector(".terminal-flotante__titulo");
  titulo.textContent = providerActivo
    ? `${providerActivo.id} · ${providerActivo.modo === "install" ? "instalando" : "sesión"}`
    : "";
}

function mostrarPanel() {
  panel.hidden = false;
  try { fit?.fit(); } catch { /* recién visible, puede no tener tamaño aún */ }
}

function ocultarPanel() {
  panel.hidden = true;
}

function alternarPanel() {
  if (!panel) return;
  if (panel.hidden) mostrarPanel(); else ocultarPanel();
}

/** "install" | "login" | null: si `providerId` tiene la sesión activa ahora. */
export function sesionDe(providerId) {
  return providerActivo?.id === providerId ? providerActivo.modo : null;
}

export function estaAbierta() {
  return Boolean(ws);
}

/** Vuelve a mostrar el panel de la sesión activa (no arranca una nueva). */
export function verPanel() {
  if (panel) mostrarPanel();
}

/** Cierra la sesión activa (si hay). No toca el panel: sólo el WS y xterm. */
export function cerrar() {
  if (observador) { try { observador.disconnect(); } catch { /* ya estaba desconectado */ } observador = null; }
  if (ws) { try { ws.close(); } catch { /* ya estaba cerrado */ } ws = null; }
  if (term) { try { term.dispose(); } catch { /* ya estaba destruido */ } term = null; }
  providerActivo = null;
  fit = null;
  if (panel) ocultarPanel();
  refrescarIndicador();
  avisarCambio();
}

/**
 * Abre una sesión para `providerId` en modo `install` o `login`. Si ya había
 * una activa, la corta primero — sólo una sesión de terminal a la vez, como
 * antes.
 */
export async function abrir(shell, providerId, modo, paquete = "") {
  cerrar();
  asegurarChrome(shell);
  providerActivo = { id: providerId, modo };
  refrescarIndicador();
  refrescarTitulo();
  mostrarPanel();

  poner(pantalla);
  estadoEl.textContent = "Cargando la terminal…";

  try {
    await cargarXterm();
  } catch (e) {
    poner(pantalla, aviso("error", "No se pudo abrir la terminal", e.message));
    providerActivo = null;
    refrescarIndicador();
    return;
  }

  term = new window.Terminal({ convertEol: true, fontSize: 13 });
  fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(pantalla);
  fit.fit();

  ws = new WebSocket(wsUrl(providerId, modo, paquete));
  ws.binaryType = "arraybuffer";

  const enviarResize = () => {
    if (ws.readyState !== WebSocket.OPEN) return;
    try { fit.fit(); } catch { /* la pantalla puede no tener tamaño todavía */ }
    ws.send(JSON.stringify({ resize: { rows: term.rows, cols: term.cols } }));
  };

  ws.addEventListener("open", () => {
    estadoEl.textContent = modo === "install" ? "Instalando…" : "Iniciando sesión…";
    enviarResize();
  });

  ws.addEventListener("message", (evento) => {
    if (typeof evento.data === "string") {
      let control = null;
      try { control = JSON.parse(evento.data); } catch { /* texto suelto, se ignora */ }
      if (control?.aviso) estadoEl.textContent = "⚠ " + control.aviso;
      else if (control?.error) estadoEl.textContent = "✕ " + control.error;
      return;
    }
    term.write(new Uint8Array(evento.data));
  });

  ws.addEventListener("close", () => {
    // No se pisa el texto: puede traer el aviso de auto-registro que mandó el
    // servidor justo antes de cerrar (ver `agent_terminal_ws`) — perderlo acá
    // sería que nadie llegue a leer "✓ Registrado en .mcp.json".
    estadoEl.textContent = (estadoEl.textContent ? estadoEl.textContent + " · " : "") + "Sesión terminada.";
    ws = null;
    if (term) { try { term.dispose(); } catch { /* ya estaba destruido */ } term = null; }
    if (observador) { try { observador.disconnect(); } catch { /* ya estaba desconectado */ } observador = null; }
    providerActivo = null;
    fit = null;
    refrescarIndicador();
    // "instalado" pudo haber cambiado — se avisa a quien esté escuchando (la
    // vista Agente, si sigue montada) para que se refresque; si el usuario ya
    // navegó a otra pestaña, no hay nadie escuchando y no pasa nada.
    avisarCambio();
  });

  ws.addEventListener("error", () => {
    estadoEl.textContent = "Error de conexión con el servidor.";
  });

  term.onData((datos) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(datos));
  });

  avisarCambio();
}

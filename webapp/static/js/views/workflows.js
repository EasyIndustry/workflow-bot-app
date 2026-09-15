/**
 * Workflows: el árbol de carpetas, el flujo abierto y el dry run.
 *
 * Cuatro decisiones del diseño se ven en este archivo:
 *
 * 1. **Las carpetas viven en el panel lateral, ramificadas.** En el legacy
 *    estaban dentro del body y se comían el espacio del flujo. En la base son
 *    una ruta materializada —`folder = "FORM/CNC4"`, en la columna TEXT que ya
 *    existe— y el árbol lo arma esta vista partiendo por `/`. Consecuencia
 *    directa: una carpeta existe porque un flujo lo dice, así que **no hay
 *    carpetas vacías**.
 * 2. **Tarjetas y texto son el mismo artefacto.** Por eso son un toggle y no dos
 *    paneles. El legacy tenía tres columnas de `1fr` y por eso se solapaban los
 *    títulos; acá son dos, anchas.
 * 3. **El render está siempre.** El "embellecedor" del legacy queda para después.
 * 4. **El Mermaid lo escribe el backend** (`POST /flow/serialize`). Este archivo
 *    nunca concatena texto del DSL.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api, ErrorApi } from "../api.js";
import { irA, rutaActual } from "../router.js";
import { tabla } from "../components/tabla.js";
import { abrirModal, confirmar } from "../components/modal.js";
import { aviso } from "../components/aviso.js";
import { crearEditorDeCodigo } from "../components/editor-codigo.js";
import { dibujarGrafo } from "./workflows-graph.js";
import { dibujarMermaid } from "./workflows-mermaid.js";
import { pilaDeTarjetas, textoBuscable } from "./workflows-cards.js";
import { tarjetaFlotante } from "./workflows-node-panel.js";

let shell = null;
let flujos = [];
let catalogo = null;
let confirmacion = null;

// El ancho de la columna izquierda (Nodos/Texto), en % de la fila. Vive acá y
// no en `abierto` a propósito: es una preferencia de cómo mirar la pantalla,
// no del flujo — cambiar de flujo no tiene por qué resetear el reparto.
let anchoIzquierdoPct = 55;

// Qué dibuja la columna derecha: el render propio ("propio") o el archivo tal
// cual, dibujado por Mermaid ("mermaid"). Misma razón que el ancho: es una
// preferencia de cómo mirar, no del flujo.
let render = "propio";

// Estado del flujo abierto. Vive acá y no en el DOM porque el editor de tarjetas
// y el de texto son vistas del mismo grafo.
let abierto = null;

/**
 * Esta pantalla dispara varias cosas que terminan mucho después de que el
 * usuario ya se fue: un `await` de red (`abrirFlujo`, `correrDry`, `guardar`)
 * que resuelve tarde, o el listener de "clic afuera" del dropdown de
 * diagnósticos, que queda escuchando en `document` mientras el dropdown siga
 * abierto. Cualquiera de los dos termina en `dibujar()`, y `dibujar()` pisa
 * `shell.vista` sin mirar qué hay ahí — si para entonces el usuario ya está
 * en Sources, el próximo clic en esa pantalla resucitaba el panel de
 * Workflows encima. `dibujar()` corta acá si la ruta ya cambió.
 */
function vigente() {
  return rutaActual().vista === "workflows";
}

export async function montar(elShell, partes) {
  shell = elShell;
  shell.ponerRotulo("WORKFLOWS");

  [flujos, catalogo] = await Promise.all([
    api.workflows(),
    catalogo ? Promise.resolve(catalogo) : api.tools(),
  ]);

  if (!vigente()) return;

  const nombre = partes[0] ? decodeURIComponent(partes[0]) : null;
  const elegido = flujos.find((f) => f.name === nombre) || null;

  dibujarLateral(elegido);
  if (!elegido) return dibujarSinElegir();
  await abrirFlujo(elegido.name);
}

// ── Panel lateral: el árbol ─────────────────────────────────────────────

/**
 * El árbol desde las rutas materializadas.
 *
 * `folder = "FORM/CNC4"` se parte por `/` y cada tramo es un nivel. No hay tabla
 * de carpetas: una carpeta existe mientras algún flujo la nombre.
 */
function armarArbol(lista) {
  const raiz = { carpetas: new Map(), flujos: [] };
  for (const f of lista) {
    const tramos = (f.folder || "").split("/").map((t) => t.trim()).filter(Boolean);
    let nodo = raiz;
    for (const tramo of tramos) {
      if (!nodo.carpetas.has(tramo)) nodo.carpetas.set(tramo, { carpetas: new Map(), flujos: [] });
      nodo = nodo.carpetas.get(tramo);
    }
    nodo.flujos.push(f);
  }
  return raiz;
}

// Qué carpetas están cerradas. Por defecto todas abiertas: con diez flujos,
// esconderlos obliga a un clic para ver lo que ya cabía en la pantalla.
const cerradas = new Set();

function dibujarLateral(elegido) {
  shell.limpiarLateral();
  const arbol = armarArbol(flujos);

  const filaFlujo = (f, profundidad) => h("div", {
    class: "item" + (elegido && f.name === elegido.name ? " item--activo" : ""),
    style: { paddingLeft: `${8 + profundidad * 13}px` },
    onClick: () => irA("workflows", f.name),
  }, [
    h("span", { class: "item__punto " + (f.state === "disabled" ? "" : "item__punto--ok") }),
    h("span", { class: "item__texto", text: f.name }),
  ]);

  const filaCarpeta = (nombre, ruta, contenido, profundidad) => {
    const abiertaAhora = !cerradas.has(ruta);
    const cuantos = contarFlujos(contenido);
    return [
      h("div", {
        class: "item item--carpeta",
        style: { paddingLeft: `${8 + profundidad * 13}px` },
        onClick: () => {
          if (abiertaAhora) cerradas.add(ruta); else cerradas.delete(ruta);
          dibujarLateral(elegido);
        },
      }, [
        h("span", { style: { flex: "0 0 9px", fontSize: "9px", color: "var(--texto-4)" },
                    text: abiertaAhora ? "▾" : "▸" }),
        h("span", { class: "item__texto", style: { fontWeight: "500" }, text: nombre }),
        h("span", { class: "item__meta", text: String(cuantos) }),
      ]),
      ...(abiertaAhora ? nivel(contenido, profundidad + 1, ruta) : []),
    ];
  };

  const nivel = (nodo, profundidad, prefijo) => [
    ...[...nodo.carpetas].sort((a, b) => a[0].localeCompare(b[0])).flatMap(
      ([nombre, contenido]) => filaCarpeta(nombre, `${prefijo}/${nombre}`, contenido, profundidad)),
    ...nodo.flujos.map((f) => filaFlujo(f, profundidad)),
  ];

  poner(shell.cuerpoLateral,
    ...nivel(arbol, 0, ""),
    h("div", { class: "item item--dashed", onClick: () => nuevoFlujo() }, [
      h("span", { style: { fontSize: "13px", lineHeight: "1" }, text: "+" }),
      h("span", { text: "Nuevo flujo" }),
    ]),
  );
}

function contarFlujos(nodo) {
  return nodo.flujos.length + [...nodo.carpetas.values()].reduce((n, c) => n + contarFlujos(c), 0);
}

function dibujarSinElegir() {
  poner(shell.vista, h("div", { class: "columna" }, [
    h("div", { class: "titulo", text: flujos.length ? "Elegí un flujo" : "Todavía no hay ningún flujo" }),
    h("div", { class: "subtitulo", text: flujos.length
      ? "Están en el panel de la izquierda, agrupados por carpeta."
      : "Un flujo es la secuencia de pasos que el bot corre sobre cada fila de una fuente." }),
    flujos.length ? null : h("div", { style: { marginTop: "16px" } }, [
      h("button", { class: "btn btn--primario", text: "Crear el primer flujo", onClick: () => nuevoFlujo() }),
    ]),
  ]));
}

// ── El flujo abierto ────────────────────────────────────────────────────

async function abrirFlujo(nombre) {
  poner(shell.vista, h("div", { class: "cargando", text: "Cargando el flujo…" }));

  let wf, grafo;
  try {
    [wf, grafo] = await Promise.all([api.workflow(nombre), api.grafo(nombre)]);
  } catch (e) {
    if (!vigente()) return;
    return poner(shell.vista, h("div", { class: "columna" }, [
      aviso("error", "No se pudo abrir el flujo", e.message),
    ]));
  }
  if (!vigente()) return;

  abierto = {
    nombre,
    wf,
    // El grafo se edita en memoria; el texto es la otra cara del mismo objeto.
    grafo: grafo.graph || grafo,
    diagnosticos: (grafo.graph || grafo).diagnostics || grafo.diagnostics || [],
    texto: wf.content || "",
    modo: (abierto && abierto.nombre === nombre) ? abierto.modo : "tarjetas",
    // Quién manda al guardar: el grafo o el texto — no necesariamente el
    // mismo que `modo` está mostrando. Cambian juntos casi siempre, pero la
    // tarjeta flotante del diagrama edita el grafo sin tocar `modo` (no
    // cambia de pestaña), así que tienen que ser dos cosas separadas o un
    // cambio ahí se perdería en silencio si `modo` seguía en "texto".
    fuenteDeVerdad: "grafo",
    seleccionado: null,
    sucio: false,
    dryRun: null,
    dryAbierto: false,
    diagnosticoAbierto: false,
  };
  dibujar();
}

function dibujar() {
  if (!vigente()) return;
  const a = abierto;
  const errores = a.diagnosticos.filter((d) => d.severity === "error");
  const avisos = a.diagnosticos.filter((d) => d.severity === "warning");

  poner(shell.vista, h("div", { style: { display: "flex", flexDirection: "column", gap: "0", height: "100%" } }, [
    cabecera(a, errores, avisos),
    confirmacion ? (() => { const n = aviso("ok", confirmacion, null); confirmacion = null; return n; })() : null,
    // Dos columnas anchas, no tres: es lo que arregla el solapamiento del
    // legacy, que tenía tres de 1fr. `alignItems` por default (stretch) y no
    // "flex-start": sin eso ninguna de las dos toma una altura acotada, cada
    // una crece a la de su contenido y es la página entera la que termina
    // scrolleando en vez de cada columna por su lado — y con eso el "Dry run"
    // de más abajo queda visualmente en cualquier lado del scroll.
    filaDeColumnas(a),
    barraDryRun(a),
  ].filter(Boolean)));
}

/**
 * Las dos columnas (Nodos/Texto y Diagrama), con un divisor de por medio para
 * correr el límite entre una y otra.
 */
function filaDeColumnas(a) {
  // `display:flex` y no `overflow:auto` en cada columna: cada panel arma su
  // propio corte entre lo que queda fijo (el título, "Volver a parsear") y lo
  // que scrollea — sin esto, un texto largo hacía crecer el editor entero sin
  // límite y esta columna terminaba con su propio scroll por afuera, dos
  // scrolls verticales por la misma razón.
  const colIzq = h("div", {
    style: { flex: `0 0 ${anchoIzquierdoPct}%`, minWidth: "0", minHeight: "0", display: "flex" },
  }, [a.modo === "texto" ? panelTexto(a) : panelTarjetas(a)]);

  const colDer = h("div", {
    style: { flex: "1 1 auto", minWidth: "0", minHeight: "0", display: "flex" },
  }, [panelRender(a)]);

  // Dos columnas anchas, no tres: es lo que arregla el solapamiento del
  // legacy, que tenía tres de 1fr. `alignItems` por default (stretch) y no
  // "flex-start": sin eso ninguna de las dos toma una altura acotada, cada
  // una crece a la de su contenido y es la página entera la que termina
  // scrolleando en vez de cada columna por su lado — y con eso el "Dry run"
  // de más abajo queda visualmente en cualquier lado del scroll.
  return h("div", { style: { display: "flex", flex: "1", minHeight: "0" } }, [
    colIzq,
    divisor(colIzq),
    colDer,
  ]);
}

const DIVISOR_MIN_PCT = 20;
const DIVISOR_MAX_PCT = 80;

/**
 * La barra angosta entre las dos columnas: arrastrarla corre el límite entre
 * una y otra. Muta `colIzq.style.flexBasis` directo en vez de pasar por
 * `dibujar()` en cada `pointermove` — redibujar toda la pantalla en cada
 * pixel de arrastre reconstruye el editor de texto entero (pierde el foco) y
 * la grilla de tarjetas, y se siente con un frenazo perceptible.
 */
function divisor(colIzq) {
  const el = h("div", {
    style: {
      flex: "0 0 9px", cursor: "col-resize", position: "relative",
      background: "transparent",
    },
  }, [
    h("div", {
      style: {
        position: "absolute", top: "0", bottom: "0", left: "4px", width: "1px",
        background: "var(--borde)",
      },
    }),
  ]);
  const linea = el.firstChild;

  let arrastrando = false;

  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    arrastrando = true;
    el.setPointerCapture(e.pointerId);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    linea.style.background = "var(--azul)";
  });

  el.addEventListener("pointermove", (e) => {
    if (!arrastrando) return;
    const fila = el.parentElement;
    const rect = fila.getBoundingClientRect();
    const pct = ((e.clientX - rect.left) / rect.width) * 100;
    anchoIzquierdoPct = Math.min(DIVISOR_MAX_PCT, Math.max(DIVISOR_MIN_PCT, pct));
    colIzq.style.flexBasis = `${anchoIzquierdoPct}%`;
  });

  const soltar = () => {
    arrastrando = false;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    linea.style.background = "var(--borde)";
  };
  el.addEventListener("pointerup", soltar);
  el.addEventListener("pointercancel", soltar);

  el.addEventListener("mouseenter", () => { if (!arrastrando) linea.style.background = "var(--borde-fuerte)"; });
  el.addEventListener("mouseleave", () => { if (!arrastrando) linea.style.background = "var(--borde)"; });

  return el;
}

function cabecera(a, errores, avisos) {
  return h("div", { class: "cabecera", style: { marginBottom: "12px", flexShrink: "0" } }, [
    h("div", { style: { minWidth: "0" } }, [
      h("div", { style: { display: "flex", alignItems: "center", gap: "9px" } }, [
        h("div", { class: "titulo", text: a.nombre }),
        a.wf.folder
          ? h("span", { class: "chip-id", text: a.wf.folder })
          : null,
        h("span", { class: a.wf.state === "disabled" ? "badge" : "badge badge--ok",
                    text: a.wf.state === "disabled" ? "deshabilitado" : "habilitado" }),
        badgeDiagnostico(a, errores, avisos),
        a.sucio ? h("span", { class: "badge badge--falta", text: "sin guardar" }) : null,
      ]),
      h("div", { class: "subtitulo", text: a.wf.description
        || `${Object.keys(a.grafo.nodes || {}).length} nodos · ${(a.grafo.edges || []).length} aristas` }),
    ]),
    h("div", { style: { display: "flex", gap: "7px", flexShrink: "0", alignItems: "center" } }, [
      toggle(a),
      h("button", { class: "btn", text: "Propiedades", onClick: () => abrirPropiedades(a) }),
      h("button", { class: "btn", title: "Eliminar el flujo", style: { color: "var(--rojo)" },
                    onClick: () => borrar(a) }, [icono(ICONOS.basura, 12, 2)]),
      h("button", { class: "btn btn--primario", text: "Guardar", disabled: !a.sucio,
                    onClick: (e) => guardar(a, e.currentTarget) }),
    ]),
  ]);
}

/** Tarjetas ↔ texto. Un toggle porque es el mismo artefacto visto de dos formas. */
function toggle(a) {
  const boton = (modo, etiqueta) => h("button", {
    class: "btn" + (a.modo === modo ? " btn--activo" : ""),
    text: etiqueta,
    onClick: () => {
      if (a.modo === modo) return;
      a.modo = modo;
      dibujar();
    },
  });
  return h("div", { class: "grupo-botones" }, [boton("tarjetas", "Tarjetas"), boton("texto", "Texto")]);
}

/**
 * Buscar un nodo por id, etiqueta, variable o tool, y llevarlo al centro del
 * diagrama con zoom — no reconstruye nada del diagrama en sí (mismo motivo
 * que `actualizarSeleccion`): sólo lo mueve y lo resalta, ver `enfocarNodo` en
 * workflows-graph.js.
 */
function buscadorDeNodos(a) {
  const entrada = h("input", {
    class: "entrada entrada--filtro", type: "text",
    placeholder: "Buscar nodo…", style: { width: "150px", flexShrink: "0" },
    onInput: (e) => {
      const q = e.target.value.trim().toLowerCase();
      entrada.classList.remove("entrada--falta");
      if (!q) return;
      const nodos = a.grafo.nodes || {};
      const id = Object.keys(nodos).find((id) => [
        id, nodos[id].display, nodos[id].label, nodos[id].variable, nodos[id].fn,
      ].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)));
      if (id && a.diagramaEl && a.diagramaEl.enfocarNodo) a.diagramaEl.enfocarNodo(id);
      else if (!id) entrada.classList.add("entrada--falta");
    },
  });
  return entrada;
}

/**
 * El badge de errores/avisos, con la lista en un desplegable propio.
 *
 * Antes era un bloque fijo entre la cabecera y las columnas: con muchos
 * problemas (24 en un flujo de treinta nodos) empujaba todo el resto de la
 * pantalla para abajo cada vez que se abría el flujo. Ahora vive en el mismo
 * lugar que ya lo anuncia — el badge, a la altura del nombre del flujo — y
 * sólo ocupa espacio mientras alguien lo tiene abierto.
 */
function badgeDiagnostico(a, errores, avisos) {
  if (!errores.length && !avisos.length) {
    return h("span", { class: "badge badge--ok", text: "sin problemas" });
  }

  const tono = errores.length ? "badge--error" : "badge--falta";
  const texto = errores.length
    ? `${errores.length} error${errores.length === 1 ? "" : "es"}`
    : `${avisos.length} aviso${avisos.length === 1 ? "" : "s"}`;

  const contenedor = h("div", { style: { position: "relative" } }, [
    h("span", {
      class: `badge ${tono}`, style: { cursor: "pointer" }, text: texto,
      onClick: (e) => {
        e.stopPropagation();
        a.diagnosticoAbierto = !a.diagnosticoAbierto;
        dibujar();
      },
    }),
    a.diagnosticoAbierto ? panelDiagnosticoFlotante(errores, avisos) : null,
  ].filter(Boolean));

  if (a.diagnosticoAbierto) {
    // Un clic afuera lo cierra. Se registra en el siguiente turno para que el
    // propio clic que lo abrió no cuente ya como "afuera".
    setTimeout(() => {
      const cerrar = (e) => {
        if (contenedor.contains(e.target)) return;
        document.removeEventListener("click", cerrar);
        a.diagnosticoAbierto = false;
        dibujar();
      };
      document.addEventListener("click", cerrar);
    });
  }

  return contenedor;
}

function panelDiagnosticoFlotante(errores, avisos) {
  const linea = (d) => h("div", { style: { display: "flex", gap: "8px", fontSize: "11.5px", lineHeight: "1.5", padding: "2px 0" } }, [
    h("span", { class: "mono", style: { flex: "0 0 92px", color: "var(--texto-4)" },
                text: [d.node_id, d.line ? `L${d.line}` : ""].filter(Boolean).join(" ") || "—" }),
    h("span", { text: d.message }),
  ]);

  return h("div", {
    style: {
      position: "absolute", top: "calc(100% + 6px)", left: "0", zIndex: "20",
      minWidth: "360px", maxWidth: "560px", maxHeight: "360px", overflow: "auto",
      background: "var(--fondo)", border: "1px solid var(--borde)", borderRadius: "4px",
      boxShadow: "0 4px 16px rgba(0,0,0,.16)", padding: "10px 12px", cursor: "auto",
    },
  }, [
    errores.length ? h("div", { style: { marginBottom: avisos.length ? "10px" : "0" } }, [
      h("div", { style: { fontWeight: "600", fontSize: "11.5px", color: "var(--rojo)", marginBottom: "4px" },
                 text: `${errores.length} error${errores.length === 1 ? "" : "es"}` }),
      ...errores.map(linea),
    ]) : null,
    avisos.length ? h("div", {}, [
      h("div", { style: { fontWeight: "600", fontSize: "11.5px", color: "var(--ambar)", marginBottom: "4px" },
                 text: `${avisos.length} aviso${avisos.length === 1 ? "" : "s"}` }),
      ...avisos.map(linea),
    ]) : null,
  ].filter(Boolean));
}

// ── Modo texto ──────────────────────────────────────────────────────────

function panelTexto(a) {
  // Se re-parsea al soltar el foco y no en cada tecla: parsear por caracter
  // manda una request por tecla y llena la pantalla de errores a medio escribir.
  const editor = crearEditorDeCodigo(a.texto, {
    anchoNumeros: "38px",
    llenarAltura: true,
    onCambiar: () => { a.texto = editor.textarea.value; a.sucio = true; a.fuenteDeVerdad = "texto"; },
  });
  editor.textarea.style.resize = "none";
  editor.textarea.addEventListener("blur", () => revalidar(a));

  return h("div", { style: { display: "flex", flexDirection: "column", flex: "1", width: "100%", height: "100%", minHeight: "0", minWidth: "0" } }, [
    h("div", { class: "seccion", style: { flexShrink: "0" } }, [
      h("span", {}, ["Mermaid", h("span", { class: "seccion__suave", text: " · el archivo tal cual se guarda" })]),
      h("button", { class: "btn btn--chico", text: "Volver a parsear", onClick: () => revalidar(a) }),
    ]),
    h("div", { style: { flex: "1", minHeight: "0" } }, [editor.elemento]),
    h("div", { class: "tabla__pie", style: { flexShrink: "0" } }, [
      "La cabecera ",
      h("span", { class: "mono", text: "%% clave: valor" }),
      " es parte del archivo: carpeta, estado y descripción. Se editan también en Propiedades.",
    ]),
  ]);
}

/** Del texto al grafo. Lo hace el backend: el parser vive en el núcleo. */
async function revalidar(a) {
  try {
    const respuesta = await api.parsear(a.texto);
    a.grafo = respuesta.graph || respuesta;
    a.diagnosticos = a.grafo.diagnostics || [];
  } catch (e) {
    a.diagnosticos = [{ severity: "error", message: e.message, line: null, node_id: null }];
  }
  dibujar();
}

// ── Modo tarjetas ───────────────────────────────────────────────────────

function panelTarjetas(a) {
  // `a.abierta` (la tarjeta desplegada en la pila) y `a.seleccionado` (el
  // nodo elegido en el diagrama, con su panel flotante) son dos estados a
  // propósito: cuando eran uno, abrir una tarjeta abría también el panel
  // sobre el diagrama y quedaban dos editores del mismo nodo a la vista.
  const pila = pilaDeTarjetas(a.grafo, catalogo, {
    seleccionado: a.abierta,
    alSeleccionar: (id) => { a.abierta = id; dibujar(); },
    alUbicar: (id) => { if (a.diagramaEl && a.diagramaEl.enfocarNodo) a.diagramaEl.enfocarNodo(id); },
    alCambiar: ({ redibujar }) => {
      a.sucio = true;
      a.fuenteDeVerdad = "grafo";
      if (redibujar) dibujar();
      else marcarSucio(a);
    },
  });
  const contador = h("span", { class: "seccion__suave" });
  aplicarFiltroDeTarjetas(a, pila, contador);
  return h("div", { style: { display: "flex", flexDirection: "column", flex: "1", width: "100%", height: "100%", minHeight: "0", minWidth: "0" } }, [
    h("div", { class: "seccion", style: { flexShrink: "0", margin: "0 0 8px" } }, [
      h("span", { style: { whiteSpace: "nowrap" } }, ["Nodos", contador]),
      filtroDeTarjetas(a, pila, contador),
    ]),
    h("div", { style: { flex: "1", minHeight: "0", overflow: "auto" } }, [pila]),
  ]);
}

/**
 * El filtro de la pila. Distinto del buscador del diagrama: aquél lleva al
 * nodo y lo resalta; éste esconde las tarjetas que no coinciden, que es lo
 * que hace falta cuando el flujo tiene cuarenta pasos y se busca "el que
 * comenta en el sistema externo" sin saber en qué posición está. Se filtra por id, nombre
 * visible, variable, tool y params. Sobrevive a un redibujo (`a.filtroTarjetas`)
 * porque abrir una tarjeta reconstruye la pila.
 */
function filtroDeTarjetas(a, pila, contador) {
  return h("input", {
    class: "entrada entrada--filtro", type: "text",
    placeholder: "Filtrar nodos…", value: a.filtroTarjetas || "",
    style: { width: "160px", flexShrink: "0" },
    onInput: (e) => {
      a.filtroTarjetas = e.target.value;
      aplicarFiltroDeTarjetas(a, pila, contador);
    },
  });
}

function aplicarFiltroDeTarjetas(a, pila, contador) {
  const q = (a.filtroTarjetas || "").trim().toLowerCase();
  const nodos = a.grafo.nodes || {};
  const tarjetas = [...pila.querySelectorAll("[data-nodo]")];
  let visibles = 0;
  for (const el of tarjetas) {
    const nodo = nodos[el.dataset.nodo];
    const coincide = !q || (nodo && textoBuscable(el.dataset.nodo, nodo).includes(q));
    el.hidden = !coincide;
    if (coincide) visibles += 1;
  }
  contador.textContent = q
    ? ` · ${visibles} de ${tarjetas.length}`
    : " · en el orden del recorrido";
  pila.classList.toggle("pila--sin-coincidencias", Boolean(q) && visibles === 0);
}

/**
 * Escribir en un campo no puede redibujar la pila: el input perdería el foco a
 * la primera tecla. Se actualiza sólo lo que cambió de estado.
 */
function marcarSucio(a) {
  const boton = shell.vista.querySelector(".btn--primario");
  if (boton) boton.disabled = false;
  const cabeceraFlujo = shell.vista.querySelector(".cabecera");
  if (cabeceraFlujo && !cabeceraFlujo.querySelector('[data-sucio]')) {
    const chip = h("span", { class: "badge badge--falta", text: "sin guardar", dataset: { sucio: "1" } });
    cabeceraFlujo.querySelector("div > div").appendChild(chip);
  }
}

// ── Render ──────────────────────────────────────────────────────────────

function panelRender(a) {
  const estados = {};
  for (const paso of (a.dryRun && a.dryRun.run && a.dryRun.run.trace) || []) {
    estados[paso.node_id || paso.node] = paso.status === "err" ? "err" : "ok";
  }

  // El clic en un nodo NO pasa por `dibujar()`: eso reconstruye la pantalla
  // entera, y con ella el diagrama de cero — perdiendo el paneo y el zoom que
  // ya se habían armado. En cambio, se resalta el nodo mutando el SVG
  // (`actualizarSeleccion`, ver workflows-graph.js) y se refresca sólo la
  // tarjeta flotante, que vive en su propio hueco.
  let diagramaEl;
  const huecoFlotante = h("div");

  const refrescarFlotante = () => {
    // "tarjetas" es el modo por default al abrir cualquier flujo: excluirlo
    // acá dejaba el panel sin mostrarse casi siempre, que es lo contrario de
    // la idea. Se muestra siempre que haya un nodo elegido, sea cual sea la
    // pestaña — ver el mismo nodo dos veces (acá y en la pila) no molesta;
    // no verlo en ningún lado, sí.
    const mostrar = a.seleccionado && a.grafo.nodes[a.seleccionado];
    poner(huecoFlotante, mostrar
      ? tarjetaFlotante(a.seleccionado, a.grafo, catalogo, {
          alCambiar: ({ redibujar }) => {
            a.sucio = true;
            // El grafo manda al guardar aunque `a.modo` siga en "texto": esto
            // edita el grafo, no el texto, sin cambiar de pestaña.
            a.fuenteDeVerdad = "grafo";
            marcarSucio(a);
            // Sólo si cambió la estructura de la tarjeta (tool, aristas): un
            // simple tipeo no necesita reconstruirla, y hacerlo igual le haría
            // perder el foco al input a la primera tecla.
            if (redibujar) refrescarFlotante();
          },
          alCerrar: () => {
            a.seleccionado = null;
            diagramaEl.actualizarSeleccion(null);
            refrescarFlotante();
          },
          alAbrirCompleta: () => {
            // Pasa a la pila y cierra el flotante: un solo editor a la vista.
            a.abierta = a.seleccionado;
            a.seleccionado = null;
            a.modo = "tarjetas";
            dibujar();
            const tarjeta = shell.vista.querySelector(`.tarjeta[data-nodo="${a.abierta}"]`);
            if (tarjeta) tarjeta.scrollIntoView({ block: "nearest" });
          },
        })
      : null);
  };

  diagramaEl = dibujarGrafo(a.grafo, {
    seleccionado: a.seleccionado,
    estados,
    // Un segundo clic sobre el mismo nodo lo cierra, igual que en la pila de
    // Tarjetas.
    alClic: (id) => {
      const nuevo = a.seleccionado === id ? null : id;
      a.seleccionado = nuevo;
      diagramaEl.actualizarSeleccion(nuevo);
      refrescarFlotante();
    },
  });
  // El buscador de la cabecera vive en otra función y no tiene forma de ver
  // este cierre: se cuelga del propio estado del flujo para llegar al mismo
  // diagrama sin recrearlo.
  a.diagramaEl = diagramaEl;
  refrescarFlotante();

  // `flex:"1", width:"100%"`: es el único hijo de una fila flex (la columna
  // derecha), y sin esto no se estira a ocupar el ancho real que le toca —
  // se queda en el ancho de su contenido, y con eso el diagrama va y viene
  // en vez de crecer en lockstep con el divisor. Mismo bug que ya se había
  // encontrado en panelTexto/panelTarjetas.
  return h("div", { style: { display: "flex", flexDirection: "column", flex: "1", width: "100%", height: "100%", minHeight: "0", minWidth: "0" } }, [
    h("div", { class: "seccion", style: { flexShrink: "0" } }, [
      h("span", { style: { flex: "1", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, ["Diagrama", h("span", {
        class: "seccion__suave",
        text: render === "mermaid"
          ? " · el archivo tal cual lo dibuja Mermaid"
          : " · clic en un nodo para editarlo acá mismo",
      })]),
      // El buscador vive al lado del diagrama porque actúa sobre él (lo
      // centra en el nodo); el filtro de la pila está al lado de "Nodos".
      // Con Mermaid no hay dónde enfocar, así que no se ofrece.
      render === "mermaid" ? null : buscadorDeNodos(a),
      toggleRender(),
    ]),
    h("div", {
      // `position:relative`: es el que aloja la tarjeta flotante del nodo
      // elegido, anclada adentro del propio visor.
      style: { flex: "1", minHeight: "0", minWidth: "0", position: "relative", border: "1px solid var(--borde)", background: "var(--fondo)" },
    }, render === "mermaid" ? [visorMermaid(a)] : [diagramaEl, huecoFlotante]),
  ]);
}

/** Propio ↔ Mermaid. Dos dibujos del mismo archivo; el propio es el que se edita. */
function toggleRender() {
  const boton = (valor, etiqueta, titulo) => h("button", {
    class: "btn" + (render === valor ? " btn--activo" : ""),
    text: etiqueta,
    title: titulo,
    onClick: () => {
      if (render === valor) return;
      render = valor;
      dibujar();
    },
  });
  return h("div", { class: "grupo-botones" }, [
    boton("propio", "Propio", "El render de la app: estados del dry run y edición por clic"),
    boton("mermaid", "Mermaid", "El mismo archivo dibujado por Mermaid, como lo vería cualquier otro visor"),
  ]);
}

/**
 * El visor de Mermaid dibuja el texto del archivo. Si lo que manda es el grafo
 * y hay cambios sin guardar, ese texto está viejo: se le pide al backend el
 * que se escribiría al guardar (`POST /flow/serialize`), así se ve lo que se
 * va a guardar y no lo que se abrió.
 */
function visorMermaid(a) {
  if (a.fuenteDeVerdad !== "grafo" || !a.sucio) return dibujarMermaid(a.texto);
  const hueco = h("div", { style: { width: "100%", height: "100%" } }, [
    h("div", { class: "tabla__vacia", text: "Escribiendo el archivo desde el grafo…" }),
  ]);
  api.serializar(a.grafo)
    .then((r) => { if (hueco.isConnected) poner(hueco, dibujarMermaid(r.content || "")); })
    .catch((e) => { if (hueco.isConnected) poner(hueco, aviso("error", "No se pudo escribir el archivo desde el grafo", e.message)); });
  return hueco;
}

// ── Dry run ─────────────────────────────────────────────────────────────

function barraDryRun(a) {
  const barra = h("div", {
    style: {
      flexShrink: "0", marginTop: "12px", borderTop: "1px solid var(--borde)",
      background: "var(--fondo-panel)",
    },
  }, [
    h("div", {
      style: { display: "flex", alignItems: "center", gap: "10px", height: "42px", padding: "0 4px" },
    }, [
      h("button", {
        class: "btn btn--chico",
        text: a.dryAbierto ? "▾ Dry run" : "▸ Dry run",
        onClick: () => { a.dryAbierto = !a.dryAbierto; dibujar(); },
      }),
      h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)", flex: "1" } },
        [resumenDry(a)]),
      h("button", { class: "btn btn--chico", text: "Correr en seco",
                    onClick: (e) => correrDry(a, e.currentTarget) }),
    ]),
    a.dryAbierto ? detalleDry(a) : null,
  ].filter(Boolean));
  return barra;
}

function resumenDry(a) {
  if (!a.dryRun) return "Resuelve todas las variables y no toca nada. Es lo que hay que mirar antes de ejecutar de verdad.";
  const d = a.dryRun;
  if (!d.runnable && !d.run) return "El flujo tiene errores: no se llegó a resolver nada.";
  const pasos = (d.run && d.run.trace) || [];
  return `${pasos.length} nodo${pasos.length === 1 ? "" : "s"} recorrido${pasos.length === 1 ? "" : "s"} · ` +
         (d.runnable ? "sin problemas" : "se detuvo antes del final");
}

async function correrDry(a, boton) {
  boton.disabled = true;
  boton.textContent = "Corriendo…";
  try {
    a.dryRun = await api.validar({ flow: a.nombre, case_id: "dry-run", row: {} });
  } catch (e) {
    a.dryRun = { runnable: false, diagnostics: [], missing_config: {}, run: null, error: e.message };
  }
  a.dryAbierto = true;
  dibujar();
}

function detalleDry(a) {
  if (!a.dryRun) {
    return h("div", { style: { padding: "16px" } }, [
      h("div", { class: "tabla__vacia", text:
        "Correlo para ver, nodo por nodo, con qué parámetros se ejecutaría." }),
    ]);
  }

  const d = a.dryRun;
  const faltantes = Object.entries(d.missing_config || {});
  const pasos = (d.run && d.run.trace) || [];

  const columnas = [
    { clave: "node_id", label: "Nodo", ancho: "130px", mono: true,
      render: (p) => p.node_id || p.node || "—" },
    { clave: "fn", label: "Tool", ancho: "170px", mono: true },
    {
      clave: "status", label: "", ancho: "62px",
      render: (p) => h("span", { class: p.status === "err" ? "badge badge--error" : "badge badge--ok",
                                 text: p.status || "ok" }),
    },
    {
      // La columna que justifica el producto: los params **ya resueltos**, con
      // las interpolaciones hechas. Es lo que nadie puede saber leyendo el .mmd.
      clave: "params", label: "Parámetros ya resueltos", envuelve: true,
      render: (p) => {
        const params = p.params || {};
        const claves = Object.keys(params);
        if (!claves.length) return "—";
        return h("div", {}, claves.map((k) => h("div", { style: { fontSize: "11px", lineHeight: "1.5" } }, [
          h("span", { class: "mono", style: { color: "var(--texto-3)" }, text: `${k}=` }),
          h("span", { class: "mono", text: String(params[k]) }),
        ])));
      },
    },
    { clave: "message", label: "", envuelve: true,
      render: (p) => p.message || "—" },
  ];

  return h("div", { style: { padding: "0 4px 12px" } }, [
    d.error ? aviso("error", "No se pudo correr en seco", d.error) : null,
    faltantes.length
      ? aviso("falta", "Falta configuración para poder ejecutar de verdad",
          h("div", {}, faltantes.map(([plugin, items]) => h("div", { style: { fontSize: "11.5px" } }, [
            h("span", { class: "mono", text: plugin }),
            ": ",
            items.map((m) => m.label || m.key).join(", "),
          ]))))
      : null,
    pasos.length
      ? tabla(columnas, pasos, { clase: "tabla" })
      : h("div", { class: "tabla__vacia", text:
          d.runnable === false
            ? "El flujo tiene errores, así que no se recorrió ningún nodo."
            : "El recorrido no pasó por ningún nodo." }),
    h("div", { class: "tabla__pie", text:
      "Un dry run resuelve las variables y no toca nada: no escribe archivos, " +
      "no hace requests, no mueve carpetas." }),
  ].filter(Boolean));
}

// ── Guardar, propiedades, alta y baja ───────────────────────────────────

async function guardar(a, boton) {
  boton.disabled = true;
  boton.textContent = "Guardando…";
  try {
    // Cuando el grafo manda, el texto lo escribe el backend desde ahí. Este
    // archivo no concatena DSL: ver el docstring del módulo. Es
    // `fuenteDeVerdad` y no `modo` porque la tarjeta flotante del diagrama
    // edita el grafo sin cambiar de pestaña — si esto mirara `modo`, esa
    // edición se perdería en silencio al guardar estando en "texto".
    let contenido = a.texto;
    let problemas = [];
    if (a.fuenteDeVerdad === "grafo") {
      const serializado = await api.serializar(a.grafo);
      contenido = serializado.content;
      problemas = serializado.problems || [];
    }

    if (problemas.length) {
      const seguir = await confirmarProblemas(problemas);
      if (!seguir) {
        boton.disabled = false;
        boton.textContent = "Guardar";
        return;
      }
    }

    const respuesta = await api.guardarWorkflow(a.nombre, {
      content: contenido,
      folder: a.wf.folder || "",
      state: a.wf.state || "enabled",
      description: a.wf.description || "",
    });
    a.texto = contenido;
    a.wf = respuesta.workflow;
    a.diagnosticos = respuesta.diagnostics || [];
    a.sucio = false;
    // El grafo se relee del backend: es la única forma de que las líneas y los
    // ids queden como quedaron en el archivo y no como los tenía el editor.
    const grafo = await api.grafo(a.nombre);
    a.grafo = grafo.graph || grafo;
    flujos = await api.workflows();
    confirmacion = `Se guardó "${a.nombre}".`;
    dibujarLateral(a.wf);
    dibujar();
  } catch (e) {
    a.diagnosticos = [{ severity: "error", message: e.message, line: null, node_id: null }];
    dibujar();
  }
}

function confirmarProblemas(problemas) {
  return new Promise((resolver) => {
    const { cerrar } = abrirModal({
      titulo: "Hay valores que no van a volver iguales",
      sub: "Guardar igual los deja escritos a medias.",
      cuerpo: h("div", { style: { padding: "14px 16px" } }, [
        h("div", { style: { fontSize: "12.5px", marginBottom: "10px", lineHeight: "1.55" }, text:
          "El DSL usa | y , para separar parámetros y \" para cerrar la etiqueta " +
          "del nodo. Un valor que los contiene se parte al volver a leer el flujo." }),
        ...problemas.map((p) => h("div", { class: "mono", style: { fontSize: "11px", lineHeight: "1.6", color: "var(--rojo)" }, text: `· ${p}` })),
      ]),
      acciones: [
        h("button", { class: "btn", text: "Volver a corregir", onClick: () => { cerrar(); resolver(false); } }),
        h("button", { class: "btn btn--rojo", text: "Guardar igual", onClick: () => { cerrar(); resolver(true); } }),
      ],
      alCerrar: () => resolver(false),
    });
  });
}

function abrirPropiedades(a) {
  const carpeta = h("input", { class: "entrada entrada--mono", type: "text", value: a.wf.folder || "",
                               placeholder: "FORM/CNC4" });
  const descripcion = h("textarea", { class: "entrada entrada--area", value: a.wf.description || "" });
  const habilitado = h("input", { type: "checkbox", checked: a.wf.state !== "disabled" });

  const { cerrar } = abrirModal({
    titulo: `Propiedades de "${a.nombre}"`,
    sub: "Se guardan en la cabecera %% del archivo.",
    cuerpo: h("div", {}, [
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Carpeta" })]),
        h("div", { class: "campo__control" }, [carpeta, h("div", { class: "campo__ayuda", text:
          "La ruta se parte por / y arma el árbol del panel lateral. Una carpeta " +
          "existe porque algún flujo la nombra: no hay carpetas vacías, y dejar " +
          "esto en blanco pone el flujo en la raíz." })]),
      ]),
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Descripción" })]),
        h("div", { class: "campo__control" }, [descripcion]),
      ]),
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Estado" })]),
        h("div", { class: "campo__control" }, [
          h("label", { class: "fila-control", style: { cursor: "pointer" } }, [
            habilitado, h("span", { style: { fontSize: "12.5px" }, text: "Habilitado" }),
          ]),
          h("div", { class: "campo__ayuda", text:
            "Un flujo deshabilitado se puede editar y ver, pero no aparece para ejecutar." }),
        ]),
      ]),
    ]),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Aplicar", onClick: () => {
        a.wf.folder = carpeta.value.trim();
        a.wf.description = descripcion.value;
        a.wf.state = habilitado.checked ? "enabled" : "disabled";
        // La cabecera es parte del texto, así que el grafo se lleva la metadata
        // y el serializador la escribe.
        a.grafo.meta = { folder: a.wf.folder, state: a.wf.state, description: a.wf.description };
        a.sucio = true;
        cerrar();
        dibujar();
      }}),
    ],
  });
}

function nuevoFlujo() {
  const nombre = h("input", { class: "entrada", type: "text", placeholder: "mi-flujo" });
  const carpeta = h("input", { class: "entrada entrada--mono", type: "text", placeholder: "FORM/CNC4" });
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });

  const { cerrar } = abrirModal({
    titulo: "Nuevo flujo",
    sub: "Arranca con un nodo de inicio y nada más.",
    cuerpo: h("div", {}, [
      error,
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [
          h("div", { class: "campo__nombre" }, ["Nombre", h("span", { class: "requerido", text: " *" })]),
        ]),
        h("div", { class: "campo__control" }, [nombre, h("div", { class: "campo__ayuda", text:
          "Sin barras ni puntos. Es la clave del flujo: los runs lo guardan." })]),
      ]),
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Carpeta" })]),
        h("div", { class: "campo__control" }, [carpeta, h("div", { class: "campo__ayuda", text:
          "Opcional. Se parte por / para armar el árbol." })]),
      ]),
    ]),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Crear", onClick: async () => {
        try {
          const valor = nombre.value.trim();
          if (!valor) throw new Error("El nombre es obligatorio.");
          const { content } = await api.serializar({
            nodes: { SN1: { type: "start", label: "inicio", line: 1 } },
            edges: [], start_node: "SN1",
            meta: { folder: carpeta.value.trim(), state: "enabled", description: "" },
          });
          await api.guardarWorkflow(valor, {
            content, folder: carpeta.value.trim(), state: "enabled", description: "",
          });
          cerrar();
          flujos = await api.workflows();
          confirmacion = `Se creó "${valor}".`;
          irA("workflows", valor);
        } catch (e) {
          error.style.display = "";
          poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
        }
      }}),
    ],
  });
  nombre.focus();
}

function borrar(a) {
  confirmar({
    titulo: `Eliminar el flujo "${a.nombre}"`,
    texto: "Se borra el flujo. Los runs que ya se ejecutaron quedan en el " +
           "historial con este nombre guardado, y las fuentes que lo tengan " +
           "como flujo por defecto se quedan sin uno.",
    alConfirmar: async () => {
      await api.borrarWorkflow(a.nombre);
      flujos = await api.workflows();
      confirmacion = `Se eliminó "${a.nombre}".`;
      abierto = null;
      dibujarLateral(null);
      if (flujos.length) irA("workflows", flujos[0].name);
      else { irA("workflows"); dibujarSinElegir(); }
    },
  });
}

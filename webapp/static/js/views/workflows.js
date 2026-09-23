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
import { pilaDeTarjetas, textoBuscable, crearNodo, quitarNodo } from "./workflows-cards.js";
import { panelDeNodo } from "./workflows-node-panel.js";
import { soloDiagrama, guardarSoloDiagrama } from "../preferencias.js";

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

// Las columnas de la fila por flujo, para el autocompletado de las tarjetas.
// La fuente es la que el flujo declara (`%% source:`, núcleo v0.3.1-beta.11,
// core#31; se fija en Propiedades) y, si no declara ninguna, la de su última
// corrida: `Run.source` dice contra cuál corrió. Una página de esa fuente —la
// misma vista previa que usa la grilla de Sources— da las columnas con un
// valor de ejemplo. Se guarda un rato por flujo y fuente: la lista se abre con
// cada `{` tipeada, y esto son dos pedidos y una lectura de la fuente.
const _columnasPorFlujo = new Map();
const VIGENCIA_COLUMNAS = 60_000;

// Las fuentes de la instalación, para el selector de Propiedades y para saber
// si la que un flujo declara existe acá. Se leen al montar y al abrir
// Propiedades; hasta que llegan, `fuenteExiste` no acusa a nadie.
let fuentes = null;
function fuenteExiste(nombre) {
  return fuentes === null || fuentes.some((f) => f.name === nombre);
}
async function cargarFuentes() {
  try {
    fuentes = await api.fuentes();
  } catch {
    fuentes = fuentes || null;
  }
  return fuentes || [];
}

function ejemploCorto(valor) {
  if (valor === null || valor === undefined || valor === "") return "";
  const texto = typeof valor === "object" ? JSON.stringify(valor) : String(valor);
  return texto.length > 28 ? texto.slice(0, 27) + "…" : texto;
}

/**
 * @returns {Promise<null|{fuente: string, declarada: boolean, existe: boolean,
 *   columnas: Array<{nombre: string, ejemplo: string}>}>}  null cuando no hay
 *   fuente declarada ni corrida de la que inferirla. `existe: false` es una
 *   fuente declarada que esta instalación no tiene (el flujo vino de otro Bot).
 */
async function columnasDeLaFila(a) {
  const declarada = (a.wf && a.wf.source) || "";
  const clave = `${a.nombre}\n${declarada}`;
  const guardado = _columnasPorFlujo.get(clave);
  if (guardado && Date.now() - guardado.cuando < VIGENCIA_COLUMNAS) return guardado.promesa;
  const promesa = (async () => {
    let nombreFuente = declarada;
    if (!nombreFuente) {
      const runs = await api.runs({ limit: 200 });
      const ultimo = runs.find((r) => r.flow === a.nombre && r.source);
      if (!ultimo) return null;
      nombreFuente = ultimo.source;
    }
    const fuente = (await api.fuentes()).find((f) => f.name === nombreFuente);
    if (!fuente) return { fuente: nombreFuente, declarada: !!declarada, existe: false, columnas: [] };
    const resp = await api.filasDeFuente(fuente, { limit: 1 });
    const fila = resp.result && resp.result.status === "ok" ? (resp.result.outputs.rows || [])[0] : null;
    return {
      fuente: nombreFuente,
      declarada: !!declarada,
      existe: true,
      columnas: fila ? Object.keys(fila).map((c) => ({ nombre: c, ejemplo: ejemploCorto(fila[c]) })) : [],
    };
  })().catch(() => null);
  _columnasPorFlujo.set(clave, { cuando: Date.now(), promesa });
  return promesa;
}

export async function montar(elShell, partes) {
  shell = elShell;
  shell.ponerRotulo("WORKFLOWS");

  [flujos, catalogo] = await Promise.all([
    api.workflows(),
    catalogo ? Promise.resolve(catalogo) : api.tools(),
    cargarFuentes(),
  ]);

  if (!vigente()) return;

  const nombre = partes[0] ? decodeURIComponent(partes[0]) : null;
  const elegido = flujos.find((f) => f.name === nombre) || null;

  dibujarLateral(elegido);
  vigilarLista(elegido);
  if (!elegido) return dibujarSinElegir();
  await abrirFlujo(elegido.name);
}

// ── La lista, al día ────────────────────────────────────────────────────
//
// Un flujo que guarda otro —un agente por MCP, otra PC de la red— no
// aparecía hasta recargar la página: la lista se leía una vez al montar.
// Un sondeo cada 5 s de `GET /workflows` (nombres, carpetas y fecha de
// cambio, sin contenido) alcanza para que el árbol se ponga al día solo. No
// toca el flujo abierto: pisar lo que alguien está editando es peor que
// mostrarlo viejo; para eso está el aviso "sin guardar" y volver a abrirlo.
const SONDEO_LISTA_MS = 5000;
let vigilanciaLista = null;

function vigilarLista(elegido) {
  if (vigilanciaLista) clearTimeout(vigilanciaLista);
  const firma = (lista) => lista.map((f) => `${f.name}|${f.folder}|${f.state}|${f.updated_at}`).sort().join("\n");
  const tick = async () => {
    if (!vigente()) { vigilanciaLista = null; return; }
    try {
      const nueva = await api.workflows();
      if (vigente() && firma(nueva) !== firma(flujos)) {
        flujos = nueva;
        const actual = elegido && flujos.find((f) => f.name === elegido.name);
        dibujarLateral(actual || null);
      }
    } catch {
      // Sin servidor, el próximo tick vuelve a probar.
    }
    if (vigente()) vigilanciaLista = setTimeout(tick, SONDEO_LISTA_MS);
  };
  vigilanciaLista = setTimeout(tick, SONDEO_LISTA_MS);
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
  // El mismo flujo que ya estaba abierto, con cambios sin guardar: se vuelve a
  // dibujar lo que hay en memoria. Volver de otra pestaña no puede descartar
  // una edición a medias, y menos en silencio; el aviso "sin guardar" sigue ahí.
  if (abierto && abierto.nombre === nombre && abierto.sucio) return dibujar();

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

  // Sin cambios pendientes se relee del servidor —otro Bot o un agente pueden
  // haberlo guardado— pero cómo se estaba mirando (pestaña Nodos/Texto, tarjeta
  // abierta, nodo elegido en el diagrama, dry run desplegado) se conserva.
  const previo = abierto && abierto.nombre === nombre ? abierto : null;
  abierto = {
    ...(previo || {}),
    nombre,
    wf,
    // El grafo se edita en memoria; el texto es la otra cara del mismo objeto.
    grafo: grafo.graph || grafo,
    diagnosticos: (grafo.graph || grafo).diagnostics || grafo.diagnostics || [],
    texto: wf.content || "",
    modo: previo ? previo.modo : "tarjetas",
    // Quién manda al guardar: el grafo o el texto — no necesariamente el
    // mismo que `modo` está mostrando. Cambian juntos casi siempre, pero la
    // tarjeta flotante del diagrama edita el grafo sin tocar `modo` (no
    // cambia de pestaña), así que tienen que ser dos cosas separadas o un
    // cambio ahí se perdería en silencio si `modo` seguía en "texto".
    fuenteDeVerdad: "grafo",
    seleccionado: previo ? previo.seleccionado : null,
    sucio: false,
    dryRun: previo ? previo.dryRun : null,
    // Nunca se hereda: una corrida que estaba en vuelo al salir se descarta
    // al volver (`abierto !== a`), y con un `true` copiado el botón quedaría
    // en "Corriendo…" para siempre.
    dryCorriendo: false,
    dryAbierto: previo ? previo.dryAbierto : false,
    diagnosticoAbierto: false,
  };
  dibujar();
}

function dibujar() {
  if (!vigente()) return;
  const a = abierto;
  // El encuadre del diagrama sobrevive al redibujo: agregar un nodo desde la
  // pila o desde el lienzo rearma el SVG, y sin esto volvía al origen.
  if (a.diagramaEl && a.diagramaEl.lienzo) a.vista = a.diagramaEl.lienzo.obtenerVista();
  const errores = a.diagnosticos.filter((d) => d.severity === "error");
  const avisos = a.diagnosticos.filter((d) => d.severity === "warning");
  // La caja que scrollea la arma `panelTarjetas`, y sólo si la pestaña es
  // Tarjetas: se limpia antes para no volver a poner el scroll sobre la del
  // dibujado anterior, que ya no está en el documento.
  a.cajaTarjetas = null;

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

  // Acá y no adentro de `panelTarjetas`: `scrollTop` sobre un elemento que
  // todavía no está en el documento no se guarda.
  if (a.cajaTarjetas) a.cajaTarjetas.scrollTop = a.scrollTarjetas || 0;
}

/**
 * Las dos columnas (Nodos/Texto y Diagrama), con un divisor de por medio para
 * correr el límite entre una y otra.
 */
function filaDeColumnas(a) {
  // Con "Solo diagrama" la izquierda ni se arma —así `a.cajaTarjetas` queda en
  // null y nadie le pone scroll a una caja fuera del documento—: el diagrama
  // se queda con la fila entera, y el reparto del divisor vuelve intacto al
  // mostrarla.
  if (soloDiagrama()) {
    return h("div", { style: { display: "flex", flex: "1", minHeight: "0" } }, [
      h("div", { style: { flex: "1 1 auto", minWidth: "0", minHeight: "0", display: "flex" } }, [panelRender(a)]),
    ]);
  }
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
        // La fuente declarada (core#31). Si esta instalación no la tiene —el
        // flujo vino de otro Bot— se ve en ámbar: el flujo corre igual contra
        // la que se elija, pero las columnas de la fila no van a estar.
        a.wf.source
          ? h("span", {
              class: "chip-id",
              style: fuenteExiste(a.wf.source) ? null : { color: "var(--ambar)" },
              title: fuenteExiste(a.wf.source)
                ? "Fuente para la que está pensado este flujo. Se cambia en Propiedades."
                : `Este flujo está pensado para la fuente "${a.wf.source}", que no existe en esta instalación.`,
              text: `fuente: ${a.wf.source}`,
            })
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

/**
 * Tarjetas ↔ texto ↔ sólo el diagrama. Un toggle porque es el mismo artefacto
 * visto de varias formas. "Solo diagrama" no es un `modo`: esconde la columna
 * izquierda y deja `a.modo` como estaba, así volver con Tarjetas o Texto
 * encuentra lo mismo que había, y lo que decide qué se guarda
 * (`fuenteDeVerdad`) no se entera.
 */
function toggle(a) {
  const oculta = soloDiagrama();
  const boton = (modo, etiqueta) => h("button", {
    class: "btn" + (!oculta && a.modo === modo ? " btn--activo" : ""),
    text: etiqueta,
    onClick: () => {
      if (!oculta && a.modo === modo) return;
      guardarSoloDiagrama(false);
      a.modo = modo;
      dibujar();
    },
  });
  return h("div", { class: "grupo-botones" }, [
    boton("tarjetas", "Tarjetas"),
    boton("texto", "Texto"),
    h("button", {
      class: "btn" + (oculta ? " btn--activo" : ""),
      text: "Solo diagrama",
      title: "Esconde la columna de Tarjetas/Texto: el lienzo agrega, conecta y edita los nodos ahí mismo",
      onClick: () => {
        if (oculta) return;
        guardarSoloDiagrama(true);
        dibujar();
      },
    }),
  ]);
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
      " es parte del archivo: carpeta, estado, descripción y fuente. Se editan también en Propiedades.",
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
    columnasDeLaFila: () => columnasDeLaFila(a),
    seleccionado: a.abierta,
    // Sin `dibujar()`: abrir y cerrar lo resuelve la propia pila sobre las
    // tarjetas que ya están (#2). Acá sólo se anota cuál quedó abierta, para
    // que un redibujo de verdad la vuelva a abrir. `agregar` y `quitar` llaman
    // a esto y después a `alCambiar({redibujar: true})`, que sí redibuja.
    alSeleccionar: (id) => { a.abierta = id; },
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

  // El que scrollea. `dibujar()` rehace la vista entera, así que es un elemento
  // nuevo en cada dibujado y nace en el tope: sin recordar la posición, elegir
  // un tool o quitar un nodo con la pila scrolleada mandaba la vista arriba
  // (#2, la otra mitad — abrir una tarjeta ya no pasa por acá).
  a.cajaTarjetas = h("div", {
    style: { flex: "1", minHeight: "0", overflow: "auto" },
    onScroll: (e) => { a.scrollTarjetas = e.target.scrollTop; },
  }, [pila]);

  return h("div", { style: { display: "flex", flexDirection: "column", flex: "1", width: "100%", height: "100%", minHeight: "0", minWidth: "0" } }, [
    h("div", { class: "seccion", style: { flexShrink: "0", margin: "0 0 8px" } }, [
      h("span", { style: { whiteSpace: "nowrap" } }, ["Nodos", contador]),
      filtroDeTarjetas(a, pila, contador),
    ]),
    a.cajaTarjetas,
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

/**
 * Lo que el lienzo pinta de un dry run, sacado del trace: el estado de cada
 * nodo, su paso (para la tarjeta y el tooltip) y las aristas por las que pasó
 * el recorrido — los pares consecutivos del trace, que es un camino lineal.
 */
function pinturaDry(a) {
  const trace = (a.dryRun && a.dryRun.run && a.dryRun.run.trace) || [];
  const estados = {};
  const pasos = {};
  const recorridas = new Set();
  trace.forEach((paso, i) => {
    const id = paso.node_id || paso.node;
    estados[id] = paso.status === "err" ? "err" : "ok";
    pasos[id] = paso;
    if (i > 0) recorridas.add(`${trace[i - 1].node_id || trace[i - 1].node}→${id}`);
  });
  const fallo = trace.find((p) => p.status === "err");
  return {
    estados, pasos, recorridas,
    dry: {
      corriendo: Boolean(a.dryCorriendo),
      hayResultado: Boolean(a.dryRun),
      resumen: a.dryCorriendo ? "" : a.dryRun ? resumenDry(a) : "",
      tono: !a.dryRun || a.dryCorriendo ? null : (fallo || a.dryRun.error || a.dryRun.runnable === false) ? "err" : "ok",
    },
  };
}

function panelRender(a) {
  const pintura = pinturaDry(a);

  /**
   * El editor del nodo elegido, para que el lienzo lo dibuje **adentro** de su
   * caja (el nodo se agranda; ver workflows-node-panel.js). Antes era una
   * tarjeta flotante anclada abajo del visor.
   *
   * Que el nodo se abra cambia el layout —su fila se agranda y el resto se
   * corre—, así que elegir un nodo sí pasa por `dibujar()`. Eso no devuelve el
   * lienzo al origen: el encuadre se guarda y se repone (`a.vista`).
   */
  let diagramaEl;
  const armarPanel = (id) => panelDeNodo(id, a.grafo, catalogo, {
    paso: pinturaDry(a).pasos[id] || null,
    hayCorrida: Boolean(a.dryRun),
    columnasDeLaFila: () => columnasDeLaFila(a),
    alCambiar: ({ redibujar }) => {
      a.sucio = true;
      // El grafo manda al guardar aunque `a.modo` siga en "texto": esto
      // edita el grafo, no el texto, sin cambiar de pestaña.
      a.fuenteDeVerdad = "grafo";
      marcarSucio(a);
      // Sólo si cambió la estructura (tool, aristas) se rearma el panel: un
      // simple tipeo no lo necesita, y hacerlo igual le haría perder el foco
      // al input a la primera tecla. Se rearma el panel solo, no el dibujo:
      // las medidas del nodo abierto son fijas, así que el layout no cambia.
      if (redibujar) diagramaEl.actualizarPanel();
    },
    alCerrar: () => { a.seleccionado = null; dibujar(); },
    alAbrirCompleta: () => {
      // Pasa a la pila y cierra el nodo: un solo editor a la vista. Con la
      // columna escondida no habría pila a la que pasar, así que se muestra.
      a.abierta = id;
      a.seleccionado = null;
      a.modo = "tarjetas";
      guardarSoloDiagrama(false);
      dibujar();
      const tarjeta = shell.vista.querySelector(`.tarjeta[data-nodo="${a.abierta}"]`);
      if (tarjeta) tarjeta.scrollIntoView({ block: "nearest" });
    },
  });

  diagramaEl = dibujarGrafo(a.grafo, {
    seleccionado: a.seleccionado,
    ...pintura,
    panelDeNodo: armarPanel,
    // Un segundo clic sobre el mismo nodo lo cierra, igual que en la pila de
    // Tarjetas.
    alClic: (id) => {
      a.seleccionado = a.seleccionado === id ? null : id;
      dibujar();
    },
    // Clic en el lienzo vacío: el nodo abierto vuelve a su tamaño.
    alClicFondo: () => {
      if (!a.seleccionado) return;
      a.seleccionado = null;
      dibujar();
    },
    // El dry run se dispara desde el lienzo, como el "Test workflow" de n8n,
    // y su resultado se pinta ahí mismo sin rearmar el diagrama. Al lado, con
    // qué registro de qué fuente se corre.
    alCorrer: () => correrDry(a),
    extras: selectorDeRegistro(a),
    edicion: edicionDesdeElLienzo(a),
    vista: a.vista || null,
    aristaSeleccionada: a.aristaSel || null,
  });
  // El buscador de la cabecera y el dry run viven en otras funciones y no
  // tienen forma de ver este cierre: se cuelgan del propio estado del flujo
  // para llegar al mismo diagrama sin recrearlo.
  a.diagramaEl = diagramaEl;

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
          : " · clic en un nodo para abrirlo y editarlo acá mismo",
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
    }, render === "mermaid" ? [visorMermaid(a)] : [diagramaEl]),
  ]);
}

/**
 * Lo que el lienzo puede pedir sobre el grafo: agregar un nodo colgado de
 * otro (el "+" del nodo, o soltar un cable en el vacío), meterlo en el medio
 * de una arista (el "+" de la arista), conectar dos nodos arrastrando, y
 * quitar una arista. El lienzo no toca el grafo: describe el gesto y acá se
 * decide, con las mismas reglas que la pila de Tarjetas (`crearNodo`).
 *
 * Todo pasa por `dibujar()` porque cambia la estructura y el layout se
 * recalcula; el encuadre se conserva (`a.vista`). Una arista nueva no lleva
 * condición: se le pone en la tarjeta del nodo, que se abre sola al agregar.
 */
function edicionDesdeElLienzo(a) {
  const cambio = (seleccionar) => {
    a.sucio = true;
    a.fuenteDeVerdad = "grafo";
    if (seleccionar !== undefined) a.seleccionado = seleccionar;
    dibujar();
  };
  return {
    // El catálogo entero: el menú de alta ofrece los tools instalados,
    // agrupados por plugin, desde el manifest. El lienzo no conoce ninguno por
    // nombre — sólo dibuja lo que hay acá.
    tools: (catalogo && catalogo.tools) || [],
    alAgregar: (tipo, { desde = null, arista = null, fn = null } = {}) => {
      const id = crearNodo(a.grafo, tipo);
      // El tool elegido en el propio menú: agregar un paso es un gesto, no
      // "crear la caja" y después "buscarle el tool" en otra pantalla. El
      // nombre visible arranca con el del tool —igual que en n8n, donde el
      // nodo se llama como la integración— así la caja no queda mostrando dos
      // veces el mismo id; se renombra en su tarjeta.
      if (fn) {
        const manifest = ((catalogo && catalogo.tools) || []).find((t) => t.id === fn);
        a.grafo.nodes[id].fn = fn;
        a.grafo.nodes[id].display = (manifest && manifest.label) || "";
      }
      if (arista) {
        // En el medio: la arista existente pasa a terminar en el nuevo, que
        // sigue hacia donde iba aquélla. La condición se queda en el primer
        // tramo, que es el que sale del nodo que la evalúa.
        a.grafo.edges.push({ from: id, to: arista.to, condition: null });
        arista.to = id;
      } else if (desde) {
        a.grafo.edges.push({ from: desde, to: id, condition: null });
      }
      cambio(id);
    },
    alConectar: (from, to) => {
      if (from === to) return;
      // La misma arista dos veces no agrega nada; el parser lo marcaría raro.
      if (a.grafo.edges.some((e) => e.from === from && e.to === to)) return;
      a.grafo.edges.push({ from, to, condition: null });
      cambio(from);
    },
    alQuitarArista: (arista) => {
      const i = a.grafo.edges.indexOf(arista);
      if (i < 0) return;
      a.grafo.edges.splice(i, 1);
      cambio();
    },
    // La condición, editada en la propia línea. Redibuja porque cambia el
    // rótulo y, si pasa a `loop`, también el punteado y el orden con que se
    // recorren las salidas al romper ciclos.
    alCambiarCondicion: (arista, valor) => {
      const nuevo = valor || null;
      if (arista.condition === nuevo) return;
      arista.condition = nuevo;
      cambio();
    },
    // Eliminar un nodo se confirma: no hay deshacer, y el re-cosido de las
    // aristas que lo atravesaban no es obvio de reconstruir a mano.
    alQuitarNodo: (id) => {
      const nodo = a.grafo.nodes[id];
      if (!nodo) return;
      const entran = a.grafo.edges.filter((e) => e.to === id).length;
      const salen = a.grafo.edges.filter((e) => e.from === id).length;
      confirmar({
        titulo: `Eliminar "${nodo.display || nodo.label || nodo.variable || nodo.fn || id}"`,
        texto: entran && salen
          ? `Se borra el nodo ${id}. Lo que le entraba (${entran}) se engancha con lo que salía `
            + `(${salen}) para no partir el flujo en dos, heredando la condición de la arista de entrada.`
          : `Se borra el nodo ${id} y sus ${entran + salen} arista${entran + salen === 1 ? "" : "s"}.`,
        alConfirmar: () => {
          quitarNodo(a.grafo, id);
          if (a.abierta === id) a.abierta = null;
          cambio(a.seleccionado === id ? null : a.seleccionado);
        },
      });
    },
    // Cuál arista quedó seleccionada, para que sobreviva al redibujo que hace
    // falta después de editar su condición.
    alSeleccionarArista: (clave) => { a.aristaSel = clave; },
  };
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

/**
 * La barra del pie: el detalle completo del dry run (tabla nodo por nodo, lo
 * que falta configurar). El disparador principal ahora está en el lienzo; el
 * botón de acá queda porque la tabla es lo que se mira cuando el lienzo no
 * alcanza, y desde la tabla uno quiere volver a correr sin subir.
 *
 * Se guarda el elemento (`a.barraDryEl`) para poder rellenarlo en el lugar:
 * el resultado de una corrida no pasa por `dibujar()`, que reconstruye el
 * diagrama y tira el paneo/zoom que uno tenía justo cuando más lo mira.
 */
function barraDryRun(a) {
  const barra = h("div", {
    style: {
      flexShrink: "0", marginTop: "12px", borderTop: "1px solid var(--borde)",
      background: "var(--fondo-panel)",
    },
  });
  a.barraDryEl = barra;
  rellenarBarraDry(a);
  return barra;
}

function rellenarBarraDry(a) {
  if (!a.barraDryEl) return;
  poner(a.barraDryEl,
    h("div", {
      style: { display: "flex", alignItems: "center", gap: "10px", height: "42px", padding: "0 4px" },
    }, [
      h("button", {
        class: "btn btn--chico",
        text: a.dryAbierto ? "▾ Dry run" : "▸ Dry run",
        onClick: () => { a.dryAbierto = !a.dryAbierto; rellenarBarraDry(a); },
      }),
      h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)", flex: "1" } },
        [a.dryCorriendo ? "Corriendo…" : resumenDry(a)]),
      h("button", { class: "btn btn--chico", text: a.dryCorriendo ? "Corriendo…" : "Correr en seco",
                    disabled: Boolean(a.dryCorriendo), onClick: () => correrDry(a) }),
    ]),
    a.dryAbierto ? detalleDry(a) : null,
  );
}

function resumenDry(a) {
  if (!a.dryRun) return "Resuelve todas las variables y no toca nada. Es lo que hay que mirar antes de ejecutar de verdad.";
  const d = a.dryRun;
  if (d.error) return `No se pudo correr: ${d.error}`;
  if (!d.runnable && !d.run) return "El flujo tiene errores: no se llegó a resolver nada.";
  const pasos = (d.run && d.run.trace) || [];
  const fallo = pasos.find((p) => p.status === "err");
  return `${pasos.length} nodo${pasos.length === 1 ? "" : "s"} recorrido${pasos.length === 1 ? "" : "s"} · ` +
         (fallo ? `se detuvo en ${fallo.node_id || fallo.node}` : d.runnable ? "sin problemas" : "se detuvo antes del final");
}

/**
 * Corre en seco y pinta el resultado **donde ya está**: el lienzo
 * (`actualizarDryRun`), la tarjeta flotante del nodo elegido y la barra del
 * pie. Nada de esto pasa por `dibujar()` a propósito — ver `barraDryRun`.
 */
async function correrDry(a) {
  if (a.dryCorriendo) return;
  a.dryCorriendo = true;
  refrescarDry(a);
  try {
    // Con un registro elegido, las variables `{row.*}` resuelven a valores de
    // verdad, que es lo que hace que el dry run muestre algo útil. Sin él, la
    // fila vacía sigue sirviendo para ver el recorrido y qué tool corre.
    const r = a.registro;
    a.dryRun = await api.validar({
      flow: a.nombre,
      case_id: r ? r.clave : "dry-run",
      row: r ? r.fila : {},
      source: r ? r.fuente : "",
    });
  } catch (e) {
    a.dryRun = { runnable: false, diagnostics: [], missing_config: {}, run: null, error: e.message };
  }
  a.dryCorriendo = false;
  a.dryAbierto = true;
  // Si mientras corría el usuario se fue a otra pantalla, no hay nada que
  // pintar: los elementos ya no están y `abierto` puede ser otro flujo.
  if (!vigente() || abierto !== a) return;
  refrescarDry(a);
}

function refrescarDry(a) {
  if (a.diagramaEl && a.diagramaEl.actualizarDryRun) a.diagramaEl.actualizarDryRun(pinturaDry(a));
  // El nodo que esté abierto suma la sección con sus params ya resueltos.
  if (a.diagramaEl && a.diagramaEl.actualizarPanel) a.diagramaEl.actualizarPanel();
  rellenarBarraDry(a);
}

// ── Con qué registro se corre en seco ───────────────────────────────────

const FILAS_SELECTOR = 50;

/**
 * El botón "Registro: …" al lado de "Correr en seco", con su desplegable para
 * elegir una fila de una fuente. Sin esto el dry run corría siempre con la
 * fila vacía y las variables `{row.*}` quedaban sin resolver — se veía el
 * recorrido pero no los parámetros de verdad, que es lo que justifica correr
 * en seco.
 *
 * Las fuentes y sus filas salen de lo mismo que usa la pantalla Sources
 * (`api.fuentes`, `api.filasDeFuente`): no hay un endpoint nuevo. La fuente
 * propuesta es la que tiene a este flujo como `default_flow`; si ninguna,
 * la primera. La elección vive en `a.registro` y sobrevive a un redibujo.
 */
function selectorDeRegistro(a) {
  const valor = h("span", { class: "lienzo__registro-valor" });
  const contenedor = h("div", { style: { position: "relative", display: "flex" } });
  let menu = null;

  const pintarBoton = () => {
    poner(valor, a.registro
      ? `${a.registro.fuente} · ${a.registro.clave}`
      : h("span", { class: "lienzo__registro-suave", text: "fila vacía" }));
  };

  const cerrar = () => {
    if (menu) { menu.remove(); menu = null; }
    document.removeEventListener("click", alClicAfuera, true);
  };
  const alClicAfuera = (e) => { if (!contenedor.contains(e.target)) cerrar(); };

  const abrir = async () => {
    if (menu) return cerrar();
    menu = h("div", { class: "lienzo__registro-menu" }, [
      h("div", { class: "lienzo__registro-pie", text: "Leyendo las fuentes…" }),
    ]);
    contenedor.appendChild(menu);
    document.addEventListener("click", alClicAfuera, true);
    let fuentes;
    try {
      fuentes = await api.fuentes();
    } catch (e) {
      if (menu) poner(menu, h("div", { class: "lienzo__registro-pie", text: `No se pudieron leer las fuentes: ${e.message}` }));
      return;
    }
    if (!menu) return;
    if (!fuentes.length) {
      poner(menu, h("div", { class: "lienzo__registro-pie", text: "No hay ninguna fuente. Se crean en Sources; mientras, el dry run corre con la fila vacía." }));
      return;
    }
    const propuesta = (a.registro && fuentes.find((f) => f.name === a.registro.fuente))
      || fuentes.find((f) => f.default_flow === a.nombre) || fuentes[0];
    armarMenu(fuentes, propuesta);
  };

  const armarMenu = (fuentes, fuente) => {
    const lista = h("div", { class: "lienzo__registro-lista" });
    const pie = h("div", { class: "lienzo__registro-pie" });
    const busqueda = h("input", { type: "text", placeholder: "Buscar en la fuente…" });
    const selFuente = h("select", {
      onChange: (e) => armarMenu(fuentes, fuentes.find((f) => f.name === e.target.value)),
    }, fuentes.map((f) => h("option", { value: f.name, text: f.name, selected: f.name === fuente.name })));

    let temporizador = null;
    busqueda.addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => cargarFilas(fuente, busqueda.value, lista, pie), 300);
    });

    poner(menu,
      h("div", { class: "lienzo__registro-cab" }, [selFuente, busqueda]),
      lista,
      pie,
    );
    cargarFilas(fuente, "", lista, pie);
    busqueda.focus();
  };

  const cargarFilas = async (fuente, texto, lista, pie) => {
    poner(lista, h("div", { class: "lienzo__registro-pie", text: "Leyendo filas…" }));
    poner(pie, "");
    let filas = [];
    let total = 0;
    try {
      const resp = await api.filasDeFuente(fuente, { search: texto, limit: FILAS_SELECTOR });
      if (resp.result.status !== "ok") throw new Error(resp.result.message || "no se pudo leer la fuente");
      filas = resp.result.outputs.rows || [];
      total = resp.result.outputs.total ?? filas.length;
    } catch (e) {
      poner(lista, h("div", { class: "lienzo__registro-pie", text: `No se pudo leer "${fuente.name}": ${e.message}` }));
      return;
    }
    if (!lista.isConnected) return;

    const sinRegistro = h("div", {
      class: "lienzo__registro-fila" + (a.registro ? "" : " lienzo__registro-fila--activa"),
      onClick: () => { a.registro = null; pintarBoton(); cerrar(); },
    }, [
      h("span", { class: "clave", text: "—" }),
      h("span", { class: "resto", text: "Sin registro: correr con la fila vacía" }),
    ]);

    poner(lista, sinRegistro, ...filas.map((fila) => {
      const clave = String(fila[fuente.key_field] ?? "");
      // Las dos primeras columnas que no son la clave, para reconocer la fila
      // sin tener que abrirla — la fuente decide cuáles son, no esta pantalla.
      const resto = Object.entries(fila)
        .filter(([k]) => k !== fuente.key_field)
        .slice(0, 3).map(([, v]) => String(v ?? "")).filter(Boolean).join(" · ");
      const activa = a.registro && a.registro.fuente === fuente.name && a.registro.clave === clave;
      return h("div", {
        class: "lienzo__registro-fila" + (activa ? " lienzo__registro-fila--activa" : ""),
        onClick: () => {
          a.registro = { fuente: fuente.name, clave, fila };
          pintarBoton();
          cerrar();
        },
      }, [h("span", { class: "clave", text: clave || "(sin clave)" }), h("span", { class: "resto", text: resto })]);
    }));
    poner(pie, filas.length < total
      ? `${filas.length} de ${total} filas · buscá para acotar`
      : `${filas.length} fila${filas.length === 1 ? "" : "s"}`);
  };

  const boton = h("button", { class: "lienzo__registro", title: "Con qué registro de la fuente correr en seco", onClick: (e) => { e.stopPropagation(); abrir(); } }, [
    h("span", { text: "Registro:" }),
    valor,
    h("span", { class: "lienzo__registro-suave", text: "▴" }),
  ]);
  pintarBoton();
  contenedor.appendChild(boton);
  return contenedor;
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
      source: a.wf.source || "",
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
  const fuente = selectorDeFuente(a.wf.source || "");

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
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Fuente" })]),
        h("div", { class: "campo__control" }, [fuente.elemento, h("div", { class: "campo__ayuda", text:
          "Para qué fuente está pensado el flujo. Con esto las tarjetas ofrecen " +
          "las columnas de la fila al tipear {, y la grilla de esa fuente lo " +
          "propone al elegir flujo. No obliga: correrlo contra otra fuente sigue valiendo." })]),
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
        a.wf.source = fuente.valor();
        // La cabecera es parte del texto, así que el grafo se lleva la metadata
        // y el serializador la escribe.
        a.grafo.meta = { folder: a.wf.folder, state: a.wf.state, description: a.wf.description, source: a.wf.source };
        a.sucio = true;
        cerrar();
        dibujar();
      }}),
    ],
  });
}

/**
 * El selector de fuente de Propiedades y del alta: las fuentes de la
 * instalación, más "ninguna". Se vuelven a leer al abrirlo, porque se pueden
 * haber creado en Sources mientras esta pantalla estaba abierta. Una declarada
 * que no existe acá se ofrece igual, marcada, para no perderla al aplicar.
 */
function selectorDeFuente(actual) {
  const selector = h("select", { class: "selector" }, [h("option", { value: "", text: "— ninguna —" })]);
  const pintar = (lista) => {
    const nombres = lista.map((f) => f.name);
    poner(selector,
      h("option", { value: "", text: "— ninguna —" }),
      ...nombres.map((n) => h("option", { value: n, text: n })),
      actual && !nombres.includes(actual)
        ? h("option", { value: actual, text: `${actual} (no existe en esta instalación)` })
        : null);
    selector.value = actual;
  };
  pintar(fuentes || []);
  cargarFuentes().then(pintar);
  return { elemento: selector, valor: () => selector.value };
}

function nuevoFlujo() {
  const nombre = h("input", { class: "entrada", type: "text", placeholder: "mi-flujo" });
  const carpeta = h("input", { class: "entrada entrada--mono", type: "text", placeholder: "FORM/CNC4" });
  // La fuente se pide al crear porque es cuando más se escriben tarjetas, y sin
  // ella el autocompletado no tiene columnas que ofrecer hasta la primera corrida.
  const fuente = selectorDeFuente("");
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
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Fuente" })]),
        h("div", { class: "campo__control" }, [fuente.elemento, h("div", { class: "campo__ayuda", text:
          "Opcional. Para qué fuente está pensado: las tarjetas ofrecen sus columnas al tipear {." })]),
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
            meta: { folder: carpeta.value.trim(), state: "enabled", description: "", source: fuente.valor() },
          });
          await api.guardarWorkflow(valor, {
            content, folder: carpeta.value.trim(), state: "enabled", description: "", source: fuente.valor(),
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

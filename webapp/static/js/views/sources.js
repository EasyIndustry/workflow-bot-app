/**
 * Sources: las fuentes de datos conectadas y la grilla de la elegida.
 *
 * Una fuente de datos es de dónde salen las filas a procesar. Ya no es un
 * subsistema propio (`SourceKind`, `Instance.sources`) — eso se fue entero con
 * el núcleo que lo traía. Lo que hay ahora es el resource `sources` del
 * plugin `connections` (`webapp/connections/plugin.py`): un ABM genérico más
 * una Action `preview` que trae filas. Esta pantalla es la vista de uso
 * diario sobre ese mismo resource — crear/editar la conexión sigue siendo la
 * pantalla genérica del plugin (Plugins → connections → sources).
 *
 * Lo que se mantiene del diseño anterior, porque seguía siendo lo correcto:
 *
 * 1. **Se mandan de a `page_size` filas.** Renderizar una fuente entera de una
 *    sentada deja el navegador inservible.
 * 2. **Buscar corre en el backend**, sobre la fuente entera — cuando la fuente
 *    no pagina contra una API externa. Con paginación externa (`page_param`),
 *    sólo puede buscar en la página que ya se trajo: no se promete lo que el
 *    núcleo no puede cumplir (ver `_fetch_page` en el plugin).
 * 3. **El flujo se elige por fila** y se pueden marcar varias para una tanda,
 *    de a una y con corte, nunca en paralelo.
 * 4. **La tabla no se mueve nunca sola.** Los controles de selección viven
 *    arriba a la derecha, no en una barra sobre la grilla.
 *
 * Lo que se dejó afuera a propósito: el filtro por columna (el `preview` del
 * plugin no lo resuelve, sólo `search` libre) y el conteo de líneas de log por
 * fila (el modal ya funciona sólo con el `case_id`, no hace falta precalcular
 * nada para abrirlo).
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api } from "../api.js";
import { irA, rutaActual } from "../router.js";
import { tabla } from "../components/tabla.js";
import { confirmar } from "../components/modal.js";
import { aviso } from "../components/aviso.js";
import { abrirLog } from "./log-modal.js";

let shell = null;
let fuentes = [];
let flujos = [];
let confirmacion = null;

/**
 * Lo que está abierto. Vive fuera de `montar` para que volver a Sources desde
 * otra pestaña no vuelva a leer la fuente.
 */
let abierto = null;

// Las columnas del bot. No son datos: son el control del bot sobre esa fila, y
// por eso son angostas y van fijas contra el borde derecho.
const COLUMNAS_BOT = [
  { clave: "_marca", label: "", ancho: "32px" },
  { clave: "_estado", label: "Estado", ancho: "78px" },
  { clave: "_log", label: "Log", ancho: "72px" },
  { clave: "_ejec", label: "Últ. ejec.", ancho: "88px" },
  { clave: "_flujo", label: "Flujo", ancho: "150px" },
  { clave: "_correr", label: "", ancho: "86px" },
];

export async function montar(elShell, partes) {
  shell = elShell;
  shell.ponerRotulo("FUENTES DE DATOS");

  fuentes = await api.fuentes();
  if (!flujos.length) flujos = await api.workflows();
  if (!vigente()) return;

  const nombre = partes[0] ? decodeURIComponent(partes[0]) : null;
  const elegida = fuentes.find((f) => f.name === nombre) || fuentes[0] || null;

  dibujarLateral(elegida);
  if (!elegida) return dibujarVacio();

  // La misma fuente que ya estaba abierta se redibuja con lo que hay en memoria.
  if (abierto && abierto.nombre === elegida.name && abierto.filas) return dibujar();
  await cargar(elegida.name, { reiniciar: true });
}

/**
 * Igual que en workflows.js: un `await` de red puede resolver después de que
 * el usuario ya se fue a otra pantalla, y sin este chequeo `dibujar()` pisaba
 * lo que esa otra pantalla ya había dibujado.
 */
function vigente() {
  return rutaActual().vista === "sources";
}

function dibujarLateral(elegida) {
  shell.limpiarLateral();
  poner(shell.cuerpoLateral,
    ...fuentes.map((f) => h("div", {
      class: "item" + (elegida && f.name === elegida.name ? " item--activo" : ""),
      onClick: () => irA("sources", f.name),
    }, [
      h("span", { class: "item__punto item__punto--ok" }),
      h("span", { class: "item__texto", text: f.name }),
      h("span", { class: "item__meta", text: f.kind || "http" }),
    ])),
    h("div", { class: "item item--dashed", onClick: () => irA("plugins", "connections", "sources", "_nuevo") }, [
      h("span", { style: { fontSize: "13px", lineHeight: "1" }, text: "+" }),
      h("span", { text: "Conectar una fuente" }),
    ]),
  );
}

// ── Instalación sin ninguna fuente ──────────────────────────────────────

function dibujarVacio() {
  poner(shell.vista, h("div", { class: "columna" }, [
    h("div", { style: { marginBottom: "16px" } }, [
      h("div", { class: "titulo", text: "Todavía no hay ninguna fuente de datos" }),
      h("div", { class: "subtitulo", text:
        "Una fuente de datos es de dónde salen las filas que el bot procesa una por una: " +
        "una API, por ahora. Sin una fuente conectada no hay nada que ejecutar." }),
    ]),
    h("div", { class: "tarjeta" }, [
      h("div", { class: "tabla__vacia", style: { padding: "34px 22px" } }, [
        h("div", { style: { marginBottom: "14px" } }, [
          "El formulario prueba la lectura con datos reales antes de guardar.",
        ]),
        h("button", { class: "btn btn--primario", text: "Conectar una fuente de datos",
                      onClick: () => irA("plugins", "connections", "sources", "_nuevo") }),
      ]),
    ]),
  ]));
}

// ── Cargar y redibujar ────────────────────────────────────────────────────

/**
 * Trae la página de filas y, aparte, los runs recientes de esta fuente para
 * saber el estado de cada una — una sola lectura para todas las filas de la
 * página, no una por fila.
 *
 * `reiniciar` limpia búsqueda, página y selección: lo que corresponde al abrir
 * otra fuente, y lo que **no** corresponde a cambiar de página.
 */
async function cargar(nombre, { reiniciar = false } = {}) {
  const previo = abierto && abierto.nombre === nombre && !reiniciar ? abierto : null;
  const cfg = fuentes.find((f) => f.name === nombre);
  const estado = previo || {
    nombre,
    cfg,
    search: "",
    filtros: {},
    facets: {},
    offset: 0,
    limite: (cfg && cfg.page_size) || 100,
    seleccion: new Set(),
    flujoPorFila: {},
    filas: null,
    total: 0,
    ultimosRuns: new Map(),
    // case_id → lo que está corriendo ahora (GET /runs/en-vuelo). Se
    // refresca por sondeo mientras haya algo en vuelo; ver vigilarEnVuelo.
    enVuelo: new Map(),
    vigilancia: null,
    tanda: null,
    error: null,
  };
  abierto = estado;

  if (!previo) poner(shell.vista, h("div", { class: "cargando", text: "Leyendo la fuente…" }));
  else atenuar(true);

  try {
    const [resp, runs] = await Promise.all([
      api.filasDeFuente(cfg, {
        search: estado.search, filters: estado.filtros, limit: estado.limite, offset: estado.offset,
      }),
      api.runs({ source: nombre, limit: 200 }).catch(() => []),
    ]);
    if (resp.result.status !== "ok") {
      estado.error = resp.result.message || "no se pudo leer la fuente";
    } else {
      estado.filas = resp.result.outputs.rows || [];
      estado.total = resp.result.outputs.total ?? estado.filas.length;
      estado.facets = resp.result.outputs.facets || {};
      estado.error = null;
      // El historial viene del más reciente al más viejo: la primera vez que
      // aparece un case_id es su run más nuevo, y es la única que importa acá.
      estado.ultimosRuns = new Map();
      for (const run of runs) {
        if (!estado.ultimosRuns.has(run.case_id)) estado.ultimosRuns.set(run.case_id, run);
      }
    }
  } catch (e) {
    estado.error = e.message;
  }
  if (!vigente()) return;
  dibujar();
  // Puede haber runs en vuelo que arrancó otro (un agente por MCP, otra
  // pestaña): una mirada al abrir, y el sondeo sigue solo si hay algo.
  vigilarEnVuelo(estado);
}

// ── Runs en vuelo: la barra de la columna Log ─────────────────────────────

// Cada cuánto se mira `runs/en-vuelo`: seguido mientras hay algo corriendo,
// despacio cuando no. Antes el sondeo se detenía al quedar vacío, y un run
// que disparaba otro (otro Bot, un agente remoto, otra pestaña) no se veía
// hasta recargar la página. Dos consultas livianas cada diez segundos es un
// precio chico por ver siempre lo que pasa.
const SONDEO_ACTIVO_MS = 1500;
const SONDEO_QUIETO_MS = 5000;

/**
 * Sondea `GET /runs/en-vuelo` mientras la fuente esté abierta: cada 1.5 s si
 * hay algo corriendo, cada 5 s si no. Actualiza las celdas Log **en su
 * lugar** (por `data-log-celda`), sin redibujar la grilla: redibujar cerraría
 * un desplegable abierto o perdería el scroll en cada tick.
 */
function vigilarEnVuelo(a) {
  if (a.vigilancia) return;
  const tick = async () => {
    if (!vigente() || abierto !== a) return detenerVigilancia(a);
    let vivos = [];
    try {
      vivos = await api.enVuelo();
    } catch {
      // Sin servidor no hay nada que mostrar; el próximo tick vuelve a probar.
    }
    if (abierto !== a) return;
    const antes = new Set(a.enVuelo.keys());
    a.enVuelo = new Map(vivos.map((v) => [String(v.case_id), v]));
    refrescarCeldasLog(a);
    // Una fila que acaba de terminar: su badge de Estado y "Últ. ejec." tienen
    // que reflejar el run nuevo, y eso sí necesita releer el historial.
    const terminadas = [...antes].filter((c) => !a.enVuelo.has(c));
    if (terminadas.length && !a.tanda) {
      const fuente = a.cfg || { name: a.nombre };
      await Promise.all(terminadas.map((c) => refrescarRun(a, fuente.name, c)));
      if (abierto === a && vigente()) redibujarQuieto();
    }
    if (abierto !== a) return;
    a.vigilancia = setTimeout(tick, a.enVuelo.size || a.tanda ? SONDEO_ACTIVO_MS : SONDEO_QUIETO_MS);
  };
  a.vigilancia = setTimeout(tick, 0);
}

function detenerVigilancia(a) {
  if (a.vigilancia) clearTimeout(a.vigilancia);
  a.vigilancia = null;
}

function refrescarCeldasLog(a) {
  for (const celda of shell.vista.querySelectorAll("[data-log-celda]")) {
    poner(celda, contenidoCeldaLog(a, celda.dataset.logCelda));
  }
}

function contenidoCeldaLog(a, caseId) {
  const vivo = a.enVuelo.get(caseId);
  const abrir = () => abrirLog(caseId, {
    alLimpiar: async () => { await refrescarRun(a, a.nombre, caseId); dibujar(); },
  });
  if (!vivo) return h("button", { class: "btn btn--chico", text: "Log", onClick: abrir });
  return barraProgreso(vivo, abrir);
}

/**
 * La barra de un run en vuelo. Con `total` y `hechos` del núcleo es "3/10" y
 * el nombre del paso; sin ellos —el núcleo de hoy no avisa por nodo— va y
 * viene y dice cuánto lleva. El log completo sigue estando en el click.
 */
function barraProgreso(vivo, alClick) {
  const conEscala = vivo.total > 0 && vivo.hechos > 0;
  const porcentaje = conEscala ? Math.min(100, Math.round((vivo.hechos / vivo.total) * 100)) : 0;
  const segundos = Math.round(vivo.elapsed || 0);
  const texto = conEscala ? `${vivo.hechos}/${vivo.total} · ${segundos}s` : `${segundos}s`;
  const detalle = [vivo.flow, vivo.paso ? `paso: ${vivo.paso}` : "en curso", `${segundos} s`]
    .filter(Boolean).join(" · ");
  return h("div", {
    class: "progreso" + (conEscala ? "" : " progreso--sin-escala"),
    title: `${detalle}\nClick para ver el registro`,
    onClick: alClick,
  }, [
    h("div", { class: "progreso__pista" }, [
      h("div", { class: "progreso__relleno", style: conEscala ? { width: `${porcentaje}%` } : {} }),
    ]),
    h("div", { class: "progreso__texto", text: vivo.paso ? `${texto} ${vivo.paso}` : texto }),
  ]);
}

/** Atenúa la tabla mientras se pide otra página, sin desarmarla. */
function atenuar(activo) {
  const grilla = shell.vista.querySelector(".grilla");
  if (grilla) grilla.style.opacity = activo ? "0.45" : "";
}

function dibujar() {
  if (!vigente()) return;
  const a = abierto;
  if (!a) return;

  const fuente = a.cfg || fuentes.find((f) => f.name === a.nombre) || { name: a.nombre };
  const partes = [cabecera(a, fuente)];
  if (confirmacion) {
    partes.push(aviso("ok", confirmacion, null));
    confirmacion = null;
  }

  if (a.error) {
    partes.push(aviso("error", "La fuente no se pudo leer", h("div", {}, [
      h("div", { class: "mono", style: { fontSize: "11.5px" }, text: a.error }),
      h("div", { style: { marginTop: "7px" } }, [
        "La fuente sigue guardada. ",
        h("a", {
          href: "#", text: "Editar su configuración",
          onClick: (e) => { e.preventDefault(); irA("plugins", "connections", "sources", fuente.name); },
        }),
        " y volver a probar.",
      ]),
    ])));
    return poner(shell.vista, ...partes);
  }

  const filas = a.filas || [];
  partes.push(barraDeFiltros(a, fuente));
  partes.push(grilla(a, fuente, filas));
  partes.push(paginador(a));
  poner(shell.vista, ...partes);
}

function cabecera(a, fuente) {
  return h("div", { class: "cabecera", style: { marginBottom: "11px" } }, [
    h("div", { style: { minWidth: "0" } }, [
      h("div", { style: { display: "flex", alignItems: "center", gap: "9px" } }, [
        h("div", { class: "titulo", text: fuente.name }),
      ]),
      h("div", { class: "subtitulo" }, [resumenDe(a, fuente)]),
    ]),
    h("div", { style: { display: "flex", alignItems: "center", gap: "7px", flexShrink: "0" } }, [
      // La selección vive acá y no arriba de la tabla: marcar un checkbox no
      // puede mover la tabla que estás por seguir marcando.
      h("div", { dataset: { barraSeleccion: "1" },
                 style: { display: "flex", alignItems: "center", gap: "7px" } },
        a.seleccion.size ? [barraDeSeleccion(a, fuente, a.filas || [])] : []),
      h("button", { class: "btn", text: "Editar fuente",
                    onClick: () => irA("plugins", "connections", "sources", fuente.name) }),
      h("button", { class: "btn", title: "Eliminar la fuente", style: { color: "var(--rojo)" },
                    onClick: () => borrarFuente(fuente) }, [icono(ICONOS.basura, 12, 2)]),
      h("button", { class: "btn btn--primario", text: "Actualizar",
                    onClick: () => cargar(a.nombre) }),
    ]),
  ]);
}

function resumenDe(a, fuente) {
  const trozos = [fuente.kind || "http"];
  if (fuente.key_field) trozos.push(`clave ${fuente.key_field}`);
  trozos.push(`${a.total} fila${a.total === 1 ? "" : "s"}`);
  if (fuente.default_flow) trozos.push(`flujo ${fuente.default_flow}`);
  return trozos.join(" · ");
}

// ── Buscar ─────────────────────────────────────────────────────────────

/**
 * La búsqueda se dispara con Enter o al soltar el foco, **no en cada tecla**:
 * cada pedido relee la fuente entera.
 */
function barraDeFiltros(a, fuente) {
  const buscador = h("input", {
    class: "entrada", type: "search", value: a.search,
    placeholder: "Buscar en todas las columnas…",
    style: { maxWidth: "290px" },
  });
  const buscar = () => aplicarBusqueda(a, buscador.value);
  buscador.addEventListener("keydown", (e) => { if (e.key === "Enter") buscar(); });
  buscador.addEventListener("blur", buscar);
  buscador.addEventListener("search", buscar);

  const selectorLimite = h("select", {
    class: "selector", style: { width: "auto" },
    title: "Cuántas filas trae de una vez",
    onChange: (e) => { a.limite = Number(e.target.value); a.offset = 0; cargar(a.nombre); },
  }, [10, 25, 50, 100, 200].map((n) => h("option", { value: String(n), text: `${n} filas` })));
  selectorLimite.value = String(a.limite);

  // Con paginación externa el buscador sólo mira la página que ya se trajo:
  // no hay forma honesta de decir "busca en toda la fuente" ahí — ver
  // `_fetch_page` en el plugin. Se avisa en vez de fingir que es lo mismo.
  const notaBusqueda = fuente.page_param
    ? "Esta fuente pagina contra la API externa: busca y filtra sólo en la página que ves, no en toda la fuente."
    : `Buscar y filtrar miran las ${a.total} filas de la fuente, no las que se ven.`;

  const activos = Object.keys(a.filtros).length + (a.search ? 1 : 0);

  return h("div", {
    style: { display: "flex", alignItems: "center", gap: "9px", marginBottom: "10px", flexWrap: "wrap" },
  }, [
    buscador,
    selectorLimite,
    activos
      ? h("button", { class: "btn", text: `Limpiar filtros (${activos})`,
                      onClick: () => { a.search = ""; a.filtros = {}; a.offset = 0; cargar(a.nombre); } })
      : null,
    h("div", { style: { flex: "1" } }),
    h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)" }, text: notaBusqueda }),
  ]);
}

/**
 * El desplegable de filtro de una columna: valores únicos, no texto libre —
 * como en la maqueta (UI-DESING/Bot Console.dc.html). Las opciones salen de
 * `facets`, que ya vienen sin achicarse por el propio filtro activo (ver el
 * docstring de `_fetch_page`), así que elegir "AR" acá no le borra "CL" a la
 * lista la próxima vez que se abre.
 */
function filtroDeColumna(a, columna) {
  const valores = a.facets[columna];
  if (!valores) return null;  // demasiados valores únicos: no es para un desplegable

  const select = h("select", {
    class: "selector selector--chico", style: { width: "100%" },
    onChange: (e) => {
      const valor = e.target.value;
      if (valor) a.filtros[columna] = valor; else delete a.filtros[columna];
      a.offset = 0;
      cargar(a.nombre);
    },
  }, [
    h("option", { value: "", text: "(todas)" }),
    ...valores.map((v) => h("option", { value: v, text: v })),
  ]);
  select.value = a.filtros[columna] || "";
  return select;
}

function aplicarBusqueda(a, valor) {
  const nuevo = valor.trim();
  if (nuevo === a.search) return;
  a.search = nuevo;
  a.offset = 0;
  cargar(a.nombre);
}

// ── Selección y ejecución en tanda ──────────────────────────────────────

function barraDeSeleccion(a, fuente, filas) {
  const cuantas = a.seleccion.size;
  const corriendo = a.tanda;
  const separador = h("div", {
    style: { width: "1px", alignSelf: "stretch", background: "var(--borde)" } });

  if (corriendo) {
    return [
      h("span", { style: { fontSize: "12.5px", fontWeight: "500", whiteSpace: "nowrap" },
                  text: `Ejecutando ${corriendo.hechas + 1} de ${corriendo.total}` }),
      h("button", {
        class: "btn", text: corriendo.cortado ? "Cortando…" : "Cortar",
        disabled: !!corriendo.cortado, style: { color: "var(--rojo)" },
        onClick: () => { corriendo.cortado = true; refrescarBarraSeleccion(a, fuente, filas); },
      }),
      separador,
    ];
  }

  return [
    h("span", { style: { fontSize: "12.5px", color: "var(--texto-2)", whiteSpace: "nowrap" },
                text: `${cuantas} seleccionada${cuantas === 1 ? "" : "s"}` }),
    h("button", { class: "btn", text: "Deseleccionar",
                  onClick: () => { a.seleccion.clear(); dibujar(); } }),
    h("button", {
      class: "btn btn--primario", text: `Ejecutar ${cuantas}`,
      title: "Se ejecutan de una en una, en orden, y se puede cortar en el medio.",
      onClick: () => ejecutarTanda(a, fuente, filas),
    }),
    separador,
  ];
}

/**
 * La tanda: una fila a la vez, y el resultado en la fila misma. De una en una
 * y no en paralelo a propósito — el bot llama a APIs de terceros, y diez runs
 * en paralelo sobre la misma fuente es la forma de corromper algo.
 */
async function ejecutarTanda(a, fuente, filas) {
  const claves = new Set(a.seleccion);
  const seleccionadas = filas.filter((f) => claves.has(claveDe(fuente, f)));
  if (!seleccionadas.length) return;

  a.tanda = { hechas: 0, total: seleccionadas.length, cortado: false };
  refrescarBarraSeleccion(a, fuente, filas);
  vigilarEnVuelo(a);

  const sinFlujo = [];
  const sinRed = [];

  for (const [i, fila] of seleccionadas.entries()) {
    if (a.tanda.cortado) break;
    a.tanda.hechas = i;
    refrescarBarraSeleccion(a, fuente, filas);

    const caseId = claveDe(fuente, fila);
    const flujo = flujoDe(a, fuente, fila);
    if (!flujo) {
      sinFlujo.push(caseId);
      continue;
    }
    try {
      await api.ejecutar({ flow: flujo, case_id: caseId, source: fuente.name, row: fila });
    } catch (e) {
      sinRed.push(`${caseId} (${e.message})`);
      continue;
    }
    await refrescarRun(a, fuente.name, caseId);
    redibujarQuieto();
  }

  a.tanda = null;
  a.seleccion.clear();
  if (sinFlujo.length) {
    confirmacion = `Sin ejecutar por falta de flujo: ${sinFlujo.join(", ")}.`;
  } else if (sinRed.length) {
    confirmacion = `No se pudo ejecutar: ${sinRed.join(", ")}.`;
  }
  redibujarQuieto();
}

/** Redibuja dejando el scroll donde estaba: la tanda redibuja tras cada fila. */
function redibujarQuieto() {
  const y = window.scrollY;
  const previa = shell.vista.querySelector(".grilla");
  const x = previa ? previa.scrollLeft : 0;
  dibujar();
  window.scrollTo(window.scrollX, y);
  const nueva = shell.vista.querySelector(".grilla");
  if (nueva) nueva.scrollLeft = x;
}

// ── La grilla ─────────────────────────────────────────────────────────────

/** La clave de caso de una fila: el campo que la fuente declaró como tal. */
function claveDe(fuente, fila) {
  return String(fila[fuente.key_field]);
}

function grilla(a, fuente, filas) {
  // Ninguna columna está declarada aparte: son las que trajo la fuente, sea
  // cual sea el nombre — igual que "elijas 5 columnas o 100" del diseño
  // anterior, sólo que acá siempre son todas.
  const elegidas = filas.length ? Object.keys(filas[0]) : [];

  const columnas = [
    ...elegidas.map((nombre) => ({
      clave: nombre, label: nombre, ancho: "150px",
      filtro: filtroDeColumna(a, nombre),
      render: (fila) => {
        const valor = fila[nombre];
        if (valor === undefined || valor === null || valor === "") return "—";
        return typeof valor === "object" ? JSON.stringify(valor) : String(valor);
      },
    })),
  ];

  const todasMarcadas = filas.length > 0 && filas.every((f) => a.seleccion.has(claveDe(fuente, f)));
  const marcaTodo = h("input", {
    type: "checkbox", checked: todasMarcadas, dataset: { marcaTodo: "1" },
    title: "Marcar o desmarcar las filas de esta página",
    onChange: (e) => {
      for (const f of filas) {
        const caseId = claveDe(fuente, f);
        if (e.target.checked) a.seleccion.add(caseId); else a.seleccion.delete(caseId);
      }
      dibujar();
    },
  });

  // `fijas` las agrupa en un solo contenedor sticky del lado de tabla.js — acá
  // sólo hace falta describirlas, sin calcular ningún offset a mano. La
  // marca de selección va con ellas, no a la izquierda: es control del bot
  // sobre la fila, igual que Estado o Ejecutar.
  const bot = COLUMNAS_BOT.map((col) => ({
    ...col,
    label: col.clave === "_marca" ? marcaTodo : col.label,
    render: (fila) => celdaBot(col.clave, fila, fuente, a, filas),
  }));

  return h("div", {}, [
    tabla([...columnas, ...bot], filas, {
      clase: "grilla",
      conFiltros: true,
      fijas: COLUMNAS_BOT.length,
      vacio: (a.search || Object.keys(a.filtros).length)
        ? "Ninguna fila coincide con la búsqueda o los filtros."
        : "La fuente se leyó bien pero no devolvió ninguna fila.",
    }),
  ]);
}

function refrescarBarraSeleccion(a, fuente, filas) {
  const contenedor = shell.vista.querySelector("[data-barra-seleccion]");
  if (!contenedor) return dibujar();
  poner(contenedor, ...(a.seleccion.size ? barraDeSeleccion(a, fuente, filas) : []));

  const marca = shell.vista.querySelector("[data-marca-todo]");
  if (marca) marca.checked = filas.length > 0 && filas.every((f) => a.seleccion.has(claveDe(fuente, f)));
}

const ESTADO = {
  ok: { clase: "badge badge--ok", texto: "ok" },
  err: { clase: "badge badge--error", texto: "err" },
};

/** El flujo de una fila: el elegido a mano, o el de la fuente. */
function flujoDe(a, fuente, fila) {
  const caseId = claveDe(fuente, fila);
  if (a.flujoPorFila[caseId] !== undefined) return a.flujoPorFila[caseId];
  return fuente.default_flow || "";
}

function celdaBot(clave, fila, fuente, a, filas) {
  const caseId = claveDe(fuente, fila);

  if (clave === "_marca") {
    return h("input", {
      type: "checkbox", checked: a.seleccion.has(caseId),
      onChange: (e) => {
        if (e.target.checked) a.seleccion.add(caseId); else a.seleccion.delete(caseId);
        // Redibujar la tabla entera por cada tilde perdería el scroll.
        refrescarBarraSeleccion(a, fuente, filas);
      },
    });
  }

  const run = a.ultimosRuns.get(caseId);

  if (clave === "_estado") {
    if (!run) return h("span", { style: { color: "var(--texto-4)" }, text: "—" });
    const e = ESTADO[run.status] || { clase: "badge", texto: run.status || "?" };
    return h("span", { class: e.clase, text: e.texto });
  }

  if (clave === "_log") {
    // Un contenedor fijo por fila: el sondeo de runs en vuelo cambia su
    // contenido (botón ↔ barra de progreso) sin redibujar la grilla.
    return h("div", { dataset: { logCelda: caseId } }, [contenidoCeldaLog(a, caseId)]);
  }

  if (clave === "_ejec") {
    if (!run) return "—";
    return h("span", { style: { fontSize: "11.5px" }, text: hace(run.finished_at || run.started_at) });
  }

  if (clave === "_flujo") {
    if (!flujos.length) {
      return h("span", { style: { color: "var(--texto-4)" },
                         title: "No hay ningún flujo guardado", text: "—" });
    }
    const selector = h("select", {
      class: "selector selector--chico",
      // No redibuja: cambiar el flujo de una fila no cambia nada más en la
      // pantalla, y redibujar cerraría el desplegable.
      onChange: (e) => { a.flujoPorFila[caseId] = e.target.value; },
    }, [
      h("option", { value: "", text: "—" }),
      ...flujos.map((w) => h("option", { value: w.name, text: w.name })),
    ]);
    selector.value = flujoDe(a, fuente, fila);
    return selector;
  }

  return h("button", {
    class: "btn btn--chico", text: "Ejecutar",
    onClick: (e) => ejecutarUna(a, fuente, fila, e.currentTarget),
  });
}

/**
 * Ejecuta una fila y actualiza **sólo esa fila**: no se vuelve a leer toda la
 * fuente para cambiar un badge.
 */
async function ejecutarUna(a, fuente, fila, boton) {
  const caseId = claveDe(fuente, fila);
  const flujo = flujoDe(a, fuente, fila);
  if (!flujo) {
    confirmacion = `${caseId}: elegí un flujo en la columna Flujo, o poné uno por defecto en la fuente.`;
    return dibujar();
  }
  boton.disabled = true;
  const original = boton.textContent;
  boton.textContent = "…";
  vigilarEnVuelo(a);
  try {
    const r = await api.ejecutar({ flow: flujo, case_id: caseId, source: fuente.name, row: fila });
    if (r.status !== "ok") {
      confirmacion = `${caseId}: el flujo "${flujo}" falló — ${r.message || r.status}.`;
    }
  } catch (e) {
    confirmacion = `${caseId}: no se pudo ejecutar — ${e.message}`;
  }
  await refrescarRun(a, fuente.name, caseId);
  if (!vigente()) return;
  boton.textContent = original;
  boton.disabled = false;
  dibujar();
}

/** Pide el run más reciente de una fila y lo mete en el mapa que ya está en memoria. */
async function refrescarRun(a, nombreFuente, caseId) {
  try {
    const runs = await api.runs({ source: nombreFuente, case_id: caseId, limit: 1 });
    if (runs[0]) a.ultimosRuns.set(caseId, runs[0]);
  } catch {
    // Queda con el estado viejo hasta el próximo Actualizar. No vale molestar
    // por esto: el resultado de la ejecución ya se reportó.
  }
}

// ── Paginador ───────────────────────────────────────────────────────────

function paginador(a) {
  const total = a.total || 0;
  const tope = a.limite || 100;
  const desde = total ? a.offset + 1 : 0;
  const hasta = Math.min(a.offset + tope, total);

  const ir = (nuevoOffset) => {
    a.offset = Math.max(0, nuevoOffset);
    a.seleccion.clear();
    cargar(a.nombre);
  };

  return h("div", {
    style: { display: "flex", alignItems: "center", gap: "9px", marginTop: "10px" },
  }, [
    h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)" },
                text: total ? `${desde}–${hasta} de ${total}` : "sin filas" }),
    h("div", { style: { flex: "1" } }),
    h("button", { class: "btn btn--chico", text: "◂ Anterior", disabled: a.offset === 0,
                  onClick: () => ir(a.offset - tope) }),
    h("button", { class: "btn btn--chico", text: "Siguiente ▸", disabled: hasta >= total,
                  onClick: () => ir(a.offset + tope) }),
  ]);
}

// ── Borrar ────────────────────────────────────────────────────────────────

function borrarFuente(fuente) {
  confirmar({
    titulo: `Eliminar la fuente "${fuente.name}"`,
    texto: "Se borra la configuración de la fuente. Los runs que ya se " +
           "ejecutaron quedan en el historial, con este nombre guardado.",
    alConfirmar: async () => {
      await api.borrarFuente(fuente.name);
      fuentes = await api.fuentes();
      confirmacion = `Se eliminó la fuente "${fuente.name}".`;
      abierto = null;
      dibujarLateral(fuentes[0] || null);
      if (fuentes.length) await cargar(fuentes[0].name, { reiniciar: true });
      else dibujarVacio();
    },
  });
}

/** "hace 2 min", que es lo que alguien mirando la grilla quiere saber. */
export function hace(epoch) {
  if (!epoch) return "—";
  const segundos = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (segundos < 60) return "recién";
  const minutos = Math.floor(segundos / 60);
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  return `hace ${Math.floor(horas / 24)} d`;
}

/**
 * Config: lo que es del núcleo y de ningún plugin.
 *
 * Los settings de cada plugin se editan en la pantalla de su plugin, no acá.
 * Es la razón por la que esta pantalla no crece cuando se instala un plugin —
 * que es cómo el front viejo terminó con nueve secciones escritas a mano.
 *
 * Seis secciones tienen backend y funcionan; General está diseñada y todavía
 * no. Las que no, lo dicen y nombran lo que falta, en vez de mostrar controles
 * que no hacen nada.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api } from "../api.js";
import { irA } from "../router.js";
import { crearCampo } from "../components/campo.js";
import { tabla } from "../components/tabla.js";
import { abrirModal, confirmar } from "../components/modal.js";
import { aviso } from "../components/aviso.js";

let shell = null;
let confirmacion = null;

const SECCIONES = [
  { id: "secretos", label: "Secretos y variables", dibujar: dibujarSecretos },
  { id: "almacenamiento", label: "Almacenamiento", dibujar: dibujarAlmacenamiento },
  { id: "diagnostico", label: "Diagnóstico", dibujar: dibujarDiagnostico },
  { id: "base", label: "Base de datos", dibujar: dibujarBase },
  { id: "seguridad", label: "Seguridad", dibujar: dibujarSeguridad },
  { id: "actualizaciones", label: "Actualizaciones", dibujar: dibujarActualizaciones },
  { id: "general", label: "General", falta: "el puerto, la retención de runs y el arranque con Windows. La retención del registro de eventos ya existe y, como el núcleo la declara igual que cualquier plugin, se edita en Plug ins → Núcleo" },
];

export async function montar(elShell, partes) {
  shell = elShell;
  shell.ponerRotulo("CONFIGURACIÓN");

  const elegida = SECCIONES.find((s) => s.id === partes[0]) || SECCIONES[0];
  dibujarLateral(elegida);
  await dibujarSeccion(elegida, partes.slice(1));
}

function dibujarLateral(elegida) {
  shell.limpiarLateral();
  poner(shell.cuerpoLateral,
    ...SECCIONES.map((s) => h("div", {
      class: "item" + (s.id === elegida.id ? " item--activo" : ""),
      onClick: () => irA("config", s.id),
    }, [
      h("span", { class: "item__punto " + (s.falta ? "" : "item__punto--ok") }),
      h("span", { class: "item__texto", text: s.label }),
    ])),
  );
  poner(shell.extraLateral,
    h("div", { class: "lateral__nota" }, [
      "Los settings de cada plugin se editan en ",
      h("a", { href: "#/plugins", text: "Plug ins" }),
      ", no acá.",
    ]),
  );
}

async function dibujarSeccion(seccion, partes = []) {
  if (!seccion.dibujar) return poner(shell.vista, h("div", { class: "columna" }, [
    encabezado(seccion.label, "Diseñada, todavía sin backend."),
    aviso("info", "Falta escribir el backend", `Esta sección espera ${seccion.falta}.`),
    h("div", { class: "tabla__pie", text: "El diseño está en UI-DESING/development/Config canvas/." }),
  ]));

  poner(shell.vista, h("div", { class: "cargando", text: "Cargando…" }));
  const bloques = await seccion.dibujar(partes);
  poner(shell.vista, h("div", { class: "columna" }, [
    ...bloques.filter(Boolean),
  ]));
}

function encabezado(titulo, sub) {
  return h("div", { style: { marginBottom: "16px" } }, [
    typeof titulo === "string" ? h("div", { class: "titulo", text: titulo }) : h("div", { class: "titulo" }, [titulo]),
    sub ? h("div", { class: "subtitulo" }, typeof sub === "string" ? [sub] : sub) : null,
  ]);
}

function consumirConfirmacion() {
  if (!confirmacion) return null;
  const texto = confirmacion;
  confirmacion = null;
  return aviso("ok", texto, null);
}

// ── Secretos y variables ────────────────────────────────────────────────

async function dibujarSecretos() {
  const datos = await api.env();
  const items = datos.items || [];
  const secretos = items.filter((i) => i.secret);
  const variables = items.filter((i) => !i.secret);

  return [
    encabezado("Secretos y variables", [
      "Lo que los flujos interpolan como ",
      h("span", { class: "mono", text: "{env.CLAVE}" }),
      ". Las variables se ven y se editan; los secretos se cargan y no se vuelven a mostrar, ni siquiera a quien los cargó.",
    ]),
    consumirConfirmacion(),
    aviso("info", "Los secretos se referencian, nunca se embeben", h("div", {}, [
      "Una conexión guarda ",
      h("span", { class: "mono", text: "Authorization: Bearer {env.API_TOKEN}" }),
      ", no el token. Así la fila de esa conexión no contiene ningún secreto y " +
      "puede viajar a una base compartida, a un backup o a un release sin " +
      "problema. El valor se resuelve en el servidor al ejecutar: nunca llega " +
      "al navegador.",
    ])),

    h("div", { class: "seccion" }, [
      h("span", {}, ["SECRETOS", h("span", { class: "seccion__suave", text: " · se escriben, no se leen" })]),
      h("button", { class: "btn btn--primario", text: "+ Nuevo secreto",
                    onClick: () => abrirEnv({ secret: true }) }),
    ]),
    tablaEnv(secretos, true),

    h("div", { class: "seccion" }, [
      h("span", {}, ["VARIABLES", h("span", { class: "seccion__suave", text: " · visibles" })]),
      h("button", { class: "btn btn--primario", text: "+ Nueva variable",
                    onClick: () => abrirEnv({ secret: false }) }),
    ]),
    tablaEnv(variables, false),

    h("div", { class: "tabla__pie", style: { lineHeight: "1.55" } }, [
      "La columna de usos sale de cruzar los flujos, las conexiones y las " +
      "fuentes guardadas contra estos nombres. Un nombre en 0 usos sobra; uno " +
      "referenciado y sin valor va a fallar en medio de una ejecución.",
      datos.key_exists
        ? null
        : h("div", { style: { marginTop: "6px" } }, [
            "Todavía no hay llave de cifrado: se genera sola cuando se cargue el primer secreto.",
          ]),
    ]),
  ];
}

function tablaEnv(filas, esSecreto) {
  const columnas = [
    {
      clave: "name", label: "Nombre", ancho: "270px", mono: true,
      render: (f) => h("span", {}, [
        h("span", { text: `{env.${f.name}}` }),
        f.undeclared
          ? h("span", { class: "badge badge--falta", style: { marginLeft: "7px" }, text: "sin cargar" })
          : null,
      ]),
    },
    {
      clave: "value", label: esSecreto ? "Estado" : "Valor",
      render: (f) => {
        if (f.unreadable) {
          return h("span", { style: { color: "var(--rojo)" } },
                   ["ilegible — se guardó con otra llave"]);
        }
        if (f.undeclared) {
          return h("span", { style: { color: "var(--ambar)" } },
                   ["un flujo lo referencia y va a fallar"]);
        }
        if (esSecreto) return h("span", { class: "mono", text: "••••••••••••" });
        return h("span", { class: "mono", text: f.value || "—" });
      },
    },
    {
      clave: "uses", label: "Usos", ancho: "72px", mono: true,
      render: (f) => h("span", { style: f.uses ? null : { color: "var(--texto-4)" } },
                       [String(f.uses)]),
    },
    {
      clave: "updated_at", label: "Cambiado", ancho: "150px",
      render: (f) => f.updated_at ? cuando(f.updated_at, f.updated_by) : "—",
    },
    {
      clave: "_acciones", label: "", ancho: "150px",
      render: (f) => h("div", { style: { display: "flex", gap: "6px" } }, [
        h("button", {
          class: "btn btn--chico",
          text: f.has_value ? (esSecreto ? "Reemplazar" : "Editar") : "Cargar",
          onClick: () => abrirEnv(f),
        }),
        f.has_value || !f.undeclared
          ? h("button", { class: "btn btn--chico", title: "Eliminar",
                          style: { color: "var(--rojo)" },
                          onClick: () => borrarEnv(f) }, [icono(ICONOS.basura, 12, 2)])
          : null,
      ]),
    },
  ];

  return tabla(columnas, filas, {
    vacio: esSecreto
      ? "Todavía no hay secretos cargados."
      : "Todavía no hay variables cargadas.",
  });
}

function cuando(epoch, quien) {
  const fecha = new Date(epoch * 1000);
  const hoy = new Date();
  const mismoDia = fecha.toDateString() === hoy.toDateString();
  const cuandoTexto = mismoDia
    ? `hoy, ${String(fecha.getHours()).padStart(2, "0")}:${String(fecha.getMinutes()).padStart(2, "0")}`
    : `${fecha.getDate()}/${fecha.getMonth() + 1}, ${String(fecha.getHours()).padStart(2, "0")}:${String(fecha.getMinutes()).padStart(2, "0")}`;
  return h("span", { style: { fontSize: "11.5px" } }, [`${cuandoTexto}${quien ? ` · ${quien}` : ""}`]);
}

/**
 * El alta y el reemplazo. No hay "editar un secreto": reemplazar es la única
 * operación posible sobre algo que no se puede leer para mostrarlo.
 */
function abrirEnv(item) {
  const esNuevo = !item.name;
  const esSecreto = !!item.secret;

  // Los dos campos se arman con el mismo `crearCampo` que usa la pantalla de
  // Plug ins, pasándole un esquema a mano. `secret: true` es lo que hace que el
  // control sea un password que arranca vacío: la regla de no mostrar nunca un
  // secreto ya está en el componente, no se reimplementa acá.
  const campoNombre = crearCampo({
    name: "name", type: "str", label: "Nombre", required: esNuevo,
    doc: esNuevo
      ? "Los flujos lo referencian como {env.NOMBRE}. Letras, números y guión bajo."
      : "El nombre no se edita: renombrarlo rompería lo que ya lo usa.",
  }, item.name || "");
  if (!esNuevo) campoNombre.elemento.querySelector(".entrada").disabled = true;

  const campoValor = crearCampo({
    name: "value", type: "str", label: "Valor", required: true,
    secret: esSecreto,
    multiline: !esSecreto,
    doc: esSecreto
      ? "Se escribe una sola vez y se guarda cifrado. Si se pierde, se carga de nuevo: no hay forma de leerlo."
      : "Se guarda en claro; se puede volver a leer y editar.",
  }, esSecreto ? "" : (item.value || ""));

  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });

  const { cerrar } = abrirModal({
    titulo: esNuevo
      ? (esSecreto ? "Nuevo secreto" : "Nueva variable")
      : (esSecreto ? `Reemplazar ${item.name}` : `Editar ${item.name}`),
    sub: esSecreto
      ? "Se guarda cifrado y no se vuelve a mostrar, ni siquiera a quien lo carga."
      : "Se guarda en claro y se puede leer.",
    cuerpo: h("div", {}, [error, campoNombre.elemento, campoValor.elemento]),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Guardar", onClick: async () => {
        const nombre = (esNuevo ? campoNombre.leer() : item.name).trim();
        try {
          if (!nombre) throw new Error("El nombre es obligatorio.");
          await api.guardarEnv(nombre, campoValor.leer(), esSecreto);
          cerrar();
          confirmacion = esNuevo
            ? `Se cargó {env.${nombre}}.`
            : `Se reemplazó el valor de {env.${nombre}}.`;
          await dibujarSeccion(SECCIONES[0]);
        } catch (e) {
          error.style.display = "";
          poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
        }
      }}),
    ],
  });

  (esNuevo ? campoNombre : campoValor).elemento.querySelector(".entrada, textarea")?.focus();
}


function borrarEnv(item) {
  confirmar({
    titulo: `Eliminar {env.${item.name}}`,
    texto: item.uses
      ? `Se referencia en ${item.uses} lugar${item.uses === 1 ? "" : "es"}. ` +
        "Al borrarlo, esas referencias van a fallar al interpolar en medio de una ejecución."
      : "No se referencia en ningún lado, así que se puede borrar sin consecuencias.",
    alConfirmar: async () => {
      await api.borrarEnv(item.name);
      confirmacion = `Se eliminó {env.${item.name}}.`;
      await dibujarSeccion(SECCIONES[0]);
    },
  });
}

// ── Almacenamiento ──────────────────────────────────────────────────────

async function dibujarAlmacenamiento() {
  const info = await api.almacenamiento();
  const cuentas = info.counts || {};
  const resumen = Object.entries(cuentas)
    .map(([tabla, n]) => `${n === null ? "?" : n} ${tabla}`)
    .join(", ");

  return [
    encabezado("Almacenamiento",
      "Dónde viven los flujos, las fuentes, el historial de runs y las variables. " +
      "Se elige una vez, al instalar."),
    consumirConfirmacion(),

    h("div", { class: "seccion" }, [h("span", { text: "BASE DE DATOS" })]),
    h("div", { class: "tarjeta" }, [
      dato("Dónde", "Local — SQLite en esta máquina",
           "Local es un archivo en el disco: no necesita salida a internet y " +
           "sobrevive a un corte de red. La opción en la nube, con varias " +
           "máquinas compartiendo flujos e historial, todavía no está escrita."),
      dato("Archivo", h("span", { class: "mono", text: info.path })),
      dato("Estado", info.exists
        ? `${(info.bytes / 1024).toFixed(0)} KB · ${resumen}`
        : "todavía no se creó"),
    ]),

    h("div", { class: "seccion" }, [h("span", { text: "CIFRADO DE SECRETOS" })]),
    h("div", { class: "tarjeta" }, [
      dato("Estado",
        info.key_exists
          ? h("span", { class: "badge badge--ok", text: "activo" })
          : h("span", { class: "badge", text: "sin usar todavía" }),
        info.key_exists
          ? "Los valores de los secretos se guardan cifrados. Quien lea la base, un backup o un dump no ve ningún token."
          : "La llave se genera sola cuando se cargue el primer secreto: una instalación que no carga ninguno no deja un archivo de llave dando vueltas."),
      dato("Llave", h("span", {}, [
        h("span", { class: "mono", text: info.key_path }),
        h("span", { class: info.key_exists ? "badge badge--ok" : "badge",
                    style: { marginLeft: "8px" },
                    text: info.key_exists ? "presente" : "ausente" }),
      ]), "Vive fuera de la base: una llave adentro de lo que cifra no cifra nada."),
    ]),

    aviso("falta", "Lo único que hay que cuidar en un backup", h("div", {}, [
      "Un backup de la base ",
      h("b", { text: "sin la llave no restaura los secretos" }),
      ", y esa es exactamente la idea. Si se pierde la llave, los secretos se " +
      "vuelven a cargar a mano: como no se pueden leer, tampoco se " +
      "\"recuperan\".",
    ])),
    h("div", { class: "tabla__pie", text:
      "Si varias máquinas usaran la misma base, o comparten la llave o cada una " +
      "tiene sus propios secretos. Sin definir todavía." }),
  ];
}

/** Una fila etiqueta/valor dentro de una tarjeta. El mismo alto que un campo. */
function dato(rotulo, valor, ayuda) {
  return h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: rotulo })]),
    h("div", { class: "campo__control" }, [
      h("div", { style: { fontSize: "12.5px", padding: "5px 0" } }, [valor]),
      ayuda ? h("div", { class: "campo__ayuda", text: ayuda }) : null,
    ]),
  ]);
}

// ── Base de datos ───────────────────────────────────────────────────────

// Cuántas filas por página en el visor. Es una preferencia de mirar, no del
// dato: vive acá y no en la URL.
let filasPorPagina = 50;

/**
 * El visor de sólo lectura: `#/config/base` lista las tablas, y
 * `#/config/base/<tabla>` pagina sus filas. Los secretos ya vienen tapados del
 * servidor (webapp/db_view.py): acá no hay nada que ocultar, sólo mostrar.
 */
async function dibujarBase([tablaElegida, offsetTexto] = []) {
  if (!tablaElegida) return dibujarTablas();
  return dibujarFilas(tablaElegida, parseInt(offsetTexto, 10) || 0);
}

async function dibujarTablas() {
  const datos = await api.tablas();
  const tablas = datos.tables || [];
  const columnas = [
    { clave: "name", label: "Tabla", ancho: "180px", mono: true, peso: "600" },
    {
      clave: "count", label: "Filas", ancho: "90px",
      render: (t) => t.count === null ? h("span", { class: "badge badge--falta", text: "?" }) : String(t.count),
    },
    { clave: "version", label: "Esquema", ancho: "80px", render: (t) => `v${t.version}` },
    { clave: "que", label: "", envuelve: true, render: (t) => QUE_GUARDA[t.name] || "" },
  ];
  return [
    encabezado("Base de datos", [
      "Lo que el núcleo guarda, tabla por tabla, tal cual está. Sólo lectura: ",
      "para cambiar algo se usa la pantalla que corresponde, no el visor.",
    ]),
    aviso("info", "Los secretos no se muestran",
      "Los valores marcados como secreto se ven como •••, estén cifrados o no. Un token que se " +
      "cuida en la pantalla de su plugin no puede aparecer acá."),
    h("div", { class: "seccion" }, [h("span", { text: "TABLAS" })]),
    tabla(columnas, tablas, {
      vacio: "El esquema no declara ninguna tabla.",
      alClic: (t) => irA("config", "base", t.name),
    }),
    h("div", { class: "tabla__pie", text: "Clic en una tabla para ver sus filas, de la más nueva a la más vieja." }),
  ];
}

const QUE_GUARDA = {
  users: "Los actores: quién puede ejecutar qué (humanos, agentes, agendas, el sistema).",
  workflows: "Los flujos, con su .mmd tal cual se guardó.",
  runs: "Una fila por ejecución, con el estado final y el nodo donde falló.",
  run_logs: "Una fila por línea de log, para armar el historial de un caso sin abrir cada run.",
  env: "Variables y secretos que los flujos interpolan como {env.CLAVE}.",
  settings: "Los settings de cada plugin y del núcleo, por instalación.",
  plugin_items: "Los items de las colecciones que declara cada plugin (fuentes, acciones, cuentas…).",
};

async function dibujarFilas(nombre, offset) {
  let pagina;
  try {
    pagina = await api.filasDeTabla(nombre, { limit: filasPorPagina, offset });
  } catch (e) {
    return [
      encabezado(nombre, null),
      aviso("error", "No se pudo leer la tabla", e.message),
      volverATablas(),
    ];
  }

  const columnas = pagina.columns.map((c) => ({
    clave: c, label: c, mono: true, envuelve: false,
    render: (f) => celdaDeValor(f[c]),
  }));

  const total = pagina.total || 0;
  const desde = total ? offset + 1 : 0;
  const hasta = Math.min(offset + pagina.limit, total);
  const ir = (nuevo) => irA("config", "base", nombre, String(Math.max(0, nuevo)));

  const selectorTamano = h("select", {
    class: "selector selector--chico", style: { width: "auto" },
    onChange: (e) => { filasPorPagina = parseInt(e.target.value, 10) || 50; ir(0); },
  }, [25, 50, 100, 250].map((n) => h("option", { value: String(n), text: `${n} por página`, selected: n === filasPorPagina })));

  return [
    encabezado(h("span", {}, [
      h("a", { href: "#/config/base", text: "Base de datos", style: { color: "var(--texto-3)", textDecoration: "none" } }),
      h("span", { text: " / " }),
      h("span", { class: "mono", text: nombre }),
    ]), QUE_GUARDA[nombre] || null),
    h("div", { class: "seccion" }, [
      h("span", { text: total ? `${desde}–${hasta} de ${total}` : "sin filas" }),
      h("div", { style: { display: "flex", gap: "6px", alignItems: "center" } }, [
        selectorTamano,
        h("button", { class: "btn btn--chico", text: "◂ Anterior", disabled: offset === 0, onClick: () => ir(offset - pagina.limit) }),
        h("button", { class: "btn btn--chico", text: "Siguiente ▸", disabled: hasta >= total, onClick: () => ir(offset + pagina.limit) }),
      ]),
    ]),
    tabla(columnas, pagina.rows, { vacio: "La tabla está vacía.", alClic: (f) => abrirFila(nombre, f) }),
    h("div", { class: "tabla__pie", text: "Los valores largos se cortan en la grilla: clic en una fila para verla entera." }),
    volverATablas(),
  ];
}

/** La fila entera, campo por campo, con el JSON indentado si lo es. */
function abrirFila(tabla, fila) {
  const filas = Object.entries(fila).map(([k, v]) => h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre mono", text: k })]),
    h("div", { class: "campo__control" }, [
      h("pre", {
        class: "mono",
        style: { margin: "0", padding: "5px 0", fontSize: "11.5px", whiteSpace: "pre-wrap", wordBreak: "break-all" },
        text: valorLegible(v),
      }),
    ]),
  ]));
  const { cerrar } = abrirModal({
    titulo: tabla,
    sub: "Sólo lectura.",
    cuerpo: h("div", {}, filas),
    acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() })],
  });
}

function valorLegible(v) {
  if (v === null || v === undefined) return "∅";
  if (typeof v !== "string") return String(v);
  const t = v.trim();
  if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
    try { return JSON.stringify(JSON.parse(t), null, 2); } catch { /* no era JSON: se muestra tal cual */ }
  }
  return v;
}

function volverATablas() {
  return h("div", {}, [h("button", { class: "btn", text: "◂ Todas las tablas", onClick: () => irA("config", "base") })]);
}

const LARGO_CELDA = 160;

/** Un valor de la base, en una celda: nulos visibles, largos cortados con el entero en el title. */
function celdaDeValor(v) {
  if (v === null || v === undefined) return h("span", { style: { color: "var(--texto-4)" }, text: "∅" });
  const texto = typeof v === "string" ? v : String(v);
  if (texto.length <= LARGO_CELDA) return h("span", { text: texto });
  return h("span", { title: texto, text: texto.slice(0, LARGO_CELDA) + "…" });
}

// ── Seguridad: actores ──────────────────────────────────────────────────
//
// Lo que hay es lo que el núcleo hace cumplir: actores con una política
// (peligrosos sí/no, qué ports). Lo que no hay —iniciar sesión, la cookie,
// los roles del diseño— se dice tal cual, sin dibujar controles que no hagan
// nada. Ver el docstring de backend/core/users.py: identidad, no autenticación.

const KIND_LABEL = {
  human: "persona", agent: "agente", schedule: "agenda", system: "sistema",
};
const KIND_DOC = {
  human: "Alguien operando desde la pantalla o la CLI. Nace pudiendo todo.",
  agent: "Un agente autónomo, por MCP. Nace sin lo peligroso y sin el port process: lo que actúa sin nadie mirando arranca conservador.",
  schedule: "Una tarea programada. Corre lo mismo que una persona, a su hora.",
  system: "El núcleo actuando por su cuenta. Sólo puede esperar.",
};
const PORT_DOC = {
  http: "salir a la red",
  fs: "leer y escribir en workspace/",
  process: "correr programas de la máquina",
  clock: "esperar y leer la hora",
  browser: "manejar un navegador (Playwright): abrir páginas, clicks, leer y escribir en pantalla",
};

async function dibujarSeguridad() {
  const datos = await api.usuarios();
  const items = datos.items || [];
  const habilitados = items.filter((u) => u.enabled);
  const deshabilitados = items.filter((u) => !u.enabled);

  const columnas = [
    {
      clave: "name", label: "Actor", ancho: "190px",
      render: (u) => h("div", {}, [
        h("div", { style: { display: "flex", gap: "6px", alignItems: "center" } }, [
          h("span", { class: "mono", style: { fontWeight: "600" }, text: u.name }),
          u.name === datos.default_actor
            ? h("span", { class: "badge badge--ok", title: "Lo usa toda ejecución que no nombre un actor (boot.env)", text: "por defecto" })
            : null,
        ]),
        u.label && u.label !== u.name
          ? h("div", { style: { fontSize: "11px", color: "var(--texto-3)" }, text: u.label })
          : null,
      ]),
    },
    { clave: "kind", label: "Tipo", ancho: "90px", render: (u) => h("span", { class: "badge", text: KIND_LABEL[u.kind] || u.kind }) },
    {
      clave: "can_run_dangerous", label: "Peligrosos", ancho: "100px",
      render: (u) => u.can_run_dangerous
        ? h("span", { class: "badge badge--falta", text: "puede" })
        : h("span", { class: "badge", text: "no" }),
    },
    {
      clave: "allowed_ports", label: "Ports", envuelve: true,
      render: (u) => u.allowed_ports === null
        ? h("span", { text: "todos" })
        : u.allowed_ports.length
          ? h("span", { class: "mono", style: { fontSize: "11.5px" }, text: u.allowed_ports.join(", ") })
          : h("span", { style: { color: "var(--texto-4)" }, text: "ninguno" }),
    },
    {
      clave: "acciones", label: "", ancho: "110px",
      render: (u) => h("button", {
        class: "btn btn--chico", text: u.enabled ? "Permisos" : "Habilitar",
        onClick: (e) => { e.stopPropagation(); u.enabled ? abrirPermisos(u, datos) : habilitar(u); },
      }),
    },
  ];

  return [
    encabezado("Seguridad",
      "Quién ejecuta y qué tiene permitido. Es lo que el núcleo hace cumplir antes de correr " +
      "un flujo: un actor sin permiso falla antes de tocar nada."),
    consumirConfirmacion(),

    h("div", { class: "seccion" }, [h("span", { text: "ACCESO" })]),
    h("div", { class: "tarjeta" }, [
      dato("Iniciar sesión", h("span", { class: "badge", text: "no existe todavía" }),
        "Cualquiera que llegue al servidor entra, y ejecuta como el actor por defecto. Sobre 127.0.0.1 " +
        "eso es \"quien ya está sentado en esta máquina\". Antes de que la instancia escuche en la red " +
        "hace falta la sesión con cookie y los dos roles del diseño; no están escritos y esta pantalla " +
        "no los finge."),
      dato("Actor por defecto", h("span", { class: "mono", text: datos.default_actor }),
        "Se elige en boot.env (default_actor). Lo usa toda ejecución que no nombre a otro."),
    ]),

    h("div", { class: "seccion" }, [
      h("span", {}, [`ACTORES · ${habilitados.length}`]),
      h("div", { style: { display: "flex", gap: "6px" } }, [
        h("button", { class: "btn", text: "+ Dar de alta", onClick: () => abrirAltaGuiada(datos) }),
        h("button", { class: "btn", text: "Avanzado", title: "Todos los campos a la vez, sin guía", onClick: () => abrirAltaAvanzada(datos) }),
      ]),
    ]),
    tabla(columnas, habilitados, {
      vacio: "No hay ningún actor habilitado.",
      alClic: (u) => abrirPermisos(u, datos),
    }),
    h("div", { class: "tabla__pie", text:
      "Un agente que use el MCP también es un actor: se le da su propio nombre y queda en el registro de cada run. " +
      "Lo que un actor puede se decide por lo que declara cada plugin: un tool marcado peligroso, un plugin que pide un port." }),

    deshabilitados.length ? h("div", { class: "seccion" }, [h("span", { text: `DESHABILITADOS · ${deshabilitados.length}` })]) : null,
    deshabilitados.length ? tabla(columnas, deshabilitados, {}) : null,
    deshabilitados.length ? h("div", { class: "tabla__pie", text:
      "No se borran: los runs que ya corrieron apuntan al actor por nombre, y borrarlo dejaría evidencia apuntando a la nada." }) : null,

    h("div", { class: "seccion" }, [h("span", { text: "QUÉ SIGNIFICA CADA TIPO" })]),
    h("div", { class: "tarjeta" }, (datos.kinds || []).map((k) => {
      const d = datos.defaults[k] || {};
      return dato(KIND_LABEL[k] || k, h("span", { style: { fontSize: "12px" } }, [
        d.can_run_dangerous ? "peligrosos: puede" : "peligrosos: no",
        " · ports: ",
        d.allowed_ports === null ? "todos" : (d.allowed_ports.length ? d.allowed_ports.join(", ") : "ninguno"),
      ]), KIND_DOC[k] || "");
    })),
  ];
}

/** El alta guiada: primero qué tipo de actor, y con eso ya se sabe qué va a poder. */
function abrirAltaGuiada(datos) {
  let kind = "agent";
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });

  const campoNombre = crearCampo({
    name: "name", type: "str", label: "Nombre", required: true,
    doc: "Con este nombre queda cada run. Letras, números, guiones y puntos; empieza con una letra.",
  }, "");
  const campoEtiqueta = crearCampo({
    name: "label", type: "str", label: "Etiqueta", doc: "Cómo se lo muestra. Opcional.",
  }, "");

  const resumen = h("div", { class: "campo__ayuda", style: { padding: "0 13px 11px" } });
  const pintarResumen = () => {
    const d = datos.defaults[kind] || {};
    poner(resumen,
      h("b", { text: "Va a poder: " }),
      d.can_run_dangerous ? "ejecutar tools peligrosos" : "sólo tools no peligrosos",
      "; ports ",
      d.allowed_ports === null ? "todos" : (d.allowed_ports.length ? d.allowed_ports.join(", ") : "ninguno"),
      ". Se puede cambiar después desde Permisos.",
    );
  };

  const opciones = h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", padding: "11px 13px" } });
  const pintarOpciones = () => {
    poner(opciones, ...(datos.kinds || []).map((k) => h("div", {
      class: "tarjeta",
      style: {
        margin: "0", padding: "10px 12px", cursor: "pointer",
        borderColor: k === kind ? "var(--azul)" : "var(--borde)",
        background: k === kind ? "var(--azul-fondo)" : "var(--fondo)",
      },
      onClick: () => { kind = k; pintarOpciones(); pintarResumen(); },
    }, [
      h("div", { style: { fontWeight: "600", fontSize: "12.5px" }, text: KIND_LABEL[k] || k }),
      h("div", { style: { fontSize: "11.5px", color: "var(--texto-3)", marginTop: "3px" }, text: KIND_DOC[k] || "" }),
    ])));
  };
  pintarOpciones();
  pintarResumen();

  const { cerrar } = abrirModal({
    titulo: "Dar de alta un actor",
    sub: "Elegí qué es, y con eso ya se sabe qué va a poder.",
    cuerpo: h("div", {}, [error, opciones, resumen, campoNombre.elemento, campoEtiqueta.elemento]),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Dar de alta", onClick: async () => {
        try {
          const creado = await api.crearUsuario({ name: campoNombre.leer().trim(), kind, label: campoEtiqueta.leer().trim() });
          cerrar();
          confirmacion = `Se dio de alta "${creado.user.name}" como ${KIND_LABEL[kind] || kind}.`;
          await dibujarSeccion(seccionPorId("seguridad"));
        } catch (e) {
          error.style.display = "";
          poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
        }
      }}),
    ],
  });
  campoNombre.elemento.querySelector(".entrada")?.focus();
}

/** El alta avanzada: todo a la vez, pisando los defaults del tipo. */
function abrirAltaAvanzada(datos) {
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });
  const campoNombre = crearCampo({ name: "name", type: "str", label: "Nombre", required: true,
    doc: "Letras, números, guiones y puntos; empieza con una letra." }, "");
  const campoEtiqueta = crearCampo({ name: "label", type: "str", label: "Etiqueta" }, "");
  const campoKind = crearCampo({ name: "kind", type: "enum", label: "Tipo", required: true, choices: datos.kinds,
    doc: "Sólo clasifica: los permisos de abajo mandan." }, "agent");
  const politica = controlesDePolitica(datos, { can_run_dangerous: false, allowed_ports: ["http", "fs", "clock"] });

  const { cerrar } = abrirModal({
    titulo: "Dar de alta un actor (avanzado)",
    sub: "Los permisos se fijan acá, no salen del tipo.",
    cuerpo: h("div", {}, [error, campoNombre.elemento, campoEtiqueta.elemento, campoKind.elemento, politica.elemento]),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Dar de alta", onClick: async () => {
        try {
          const p = politica.leer();
          const creado = await api.crearUsuario({
            name: campoNombre.leer().trim(), kind: campoKind.leer(), label: campoEtiqueta.leer().trim(),
            can_run_dangerous: p.can_run_dangerous,
            // null = todos: el backend lo toma como "el default del tipo", así
            // que "todos" se manda como la lista completa.
            allowed_ports: p.allowed_ports === null ? datos.ports : p.allowed_ports,
          });
          cerrar();
          confirmacion = `Se dio de alta "${creado.user.name}".`;
          await dibujarSeccion(seccionPorId("seguridad"));
        } catch (e) {
          error.style.display = "";
          poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
        }
      }}),
    ],
  });
  campoNombre.elemento.querySelector(".entrada")?.focus();
}

/** Permisos de un actor existente, y la baja lógica. */
function abrirPermisos(u, datos) {
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });
  const politica = controlesDePolitica(datos, u);
  const esDefault = u.name === datos.default_actor;

  const { cerrar } = abrirModal({
    titulo: `Permisos de ${u.name}`,
    sub: `${KIND_LABEL[u.kind] || u.kind}${u.label && u.label !== u.name ? ` · ${u.label}` : ""}. Un cambio acá vale desde el próximo run; el que está corriendo no se amplía.`,
    cuerpo: h("div", {}, [error, politica.elemento]),
    izquierda: h("button", {
      class: "btn", text: "Deshabilitar", disabled: esDefault,
      title: esDefault ? "Es el actor por defecto del arranque: no se puede deshabilitar." : "Baja lógica: deja de poder ejecutar, y sus runs siguen apuntando a su nombre.",
      onClick: () => {
        cerrar();
        confirmar({
          titulo: `Deshabilitar a "${u.name}"`,
          texto: "Deja de poder ejecutar nada, desde ya. No se borra: sus runs siguen apuntando a su nombre, y se puede volver a habilitar.",
          alConfirmar: async () => {
            await api.actualizarUsuario(u.name, { enabled: false });
            confirmacion = `Se deshabilitó a "${u.name}".`;
            await dibujarSeccion(seccionPorId("seguridad"));
          },
        });
      },
    }),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Guardar", onClick: async () => {
        try {
          const p = politica.leer();
          await api.actualizarUsuario(u.name, {
            can_run_dangerous: p.can_run_dangerous,
            allowed_ports: p.allowed_ports === null ? undefined : p.allowed_ports,
            clear_ports: p.allowed_ports === null,
          });
          cerrar();
          confirmacion = `Se guardaron los permisos de "${u.name}".`;
          await dibujarSeccion(seccionPorId("seguridad"));
        } catch (e) {
          error.style.display = "";
          poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
        }
      }}),
    ],
  });
}

async function habilitar(u) {
  await api.actualizarUsuario(u.name, { enabled: true });
  confirmacion = `Se volvió a habilitar a "${u.name}".`;
  await dibujarSeccion(seccionPorId("seguridad"));
}

/**
 * Los dos controles de una política: peligrosos sí/no, y qué ports. "Todos los
 * ports" es un estado propio (null en el núcleo), distinto de marcar los cuatro
 * que existen hoy: si mañana aparece un quinto, "todos" lo incluye y la lista no.
 */
function controlesDePolitica(datos, actual) {
  const chkPeligroso = h("input", { type: "checkbox", checked: !!actual.can_run_dangerous });
  const chkTodos = h("input", { type: "checkbox", checked: actual.allowed_ports === null });
  const porPort = {};
  const lista = h("div", { style: { display: "flex", flexDirection: "column", gap: "4px", marginTop: "6px" } },
    (datos.ports || []).map((p) => {
      porPort[p] = h("input", { type: "checkbox", checked: actual.allowed_ports === null || (actual.allowed_ports || []).includes(p) });
      return h("label", { class: "fila-control", style: { cursor: "pointer" } }, [
        porPort[p],
        h("span", { class: "mono", style: { fontSize: "12px", width: "70px" }, text: p }),
        h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)" }, text: PORT_DOC[p] || "" }),
      ]);
    }));
  const refrescar = () => { lista.style.opacity = chkTodos.checked ? "0.45" : "1"; lista.style.pointerEvents = chkTodos.checked ? "none" : ""; };
  chkTodos.addEventListener("change", refrescar);
  refrescar();

  const elemento = h("div", {}, [
    h("div", { class: "campo" }, [
      h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Tools peligrosos" })]),
      h("div", { class: "campo__control" }, [
        h("label", { class: "fila-control", style: { cursor: "pointer" } }, [chkPeligroso, h("span", { style: { fontSize: "12.5px" }, text: "Puede ejecutar tools marcados dangerous" })]),
        h("div", { class: "campo__ayuda", text: "Borrar carpetas, mover archivos, correr comandos: lo que cada plugin marcó como irreversible." }),
      ]),
    ]),
    h("div", { class: "campo" }, [
      h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Ports" })]),
      h("div", { class: "campo__control" }, [
        h("label", { class: "fila-control", style: { cursor: "pointer" } }, [chkTodos, h("span", { style: { fontSize: "12.5px" }, text: "Todos, incluso los que se agreguen después" })]),
        lista,
        h("div", { class: "campo__ayuda", text: "Se decide por plugin, no por tool: si un plugin declara un port que el actor no tiene, ninguno de sus tools corre." }),
      ]),
    ]),
  ]);

  return {
    elemento,
    leer: () => ({
      can_run_dangerous: chkPeligroso.checked,
      allowed_ports: chkTodos.checked ? null : Object.entries(porPort).filter(([, c]) => c.checked).map(([p]) => p),
    }),
  };
}

function seccionPorId(id) {
  return SECCIONES.find((s) => s.id === id);
}

// ── Actualizaciones del núcleo y de la web app ──────────────────────────
//
// backend/ se trae de los releases del core y webapp/ de los del repo de
// este programa; cada uno se reemplaza entero (webapp/updates.py). Acá: de
// qué repos (editables, guardados por instalación), qué corre de cada uno,
// qué releases hay —los de prueba incluidos, con su badge—, instalar uno o
// subir el archivo si no hay internet, volver al anterior, y reiniciar. Los
// dos componentes se dibujan con el mismo bloque: cambia el dato, no la UI.

let incluirPrueba = true;

const COMPONENTES_UPDATE = [
  { id: "core", titulo: "NÚCLEO", carpeta: "backend/", que: "el núcleo", de: "del núcleo" },
  { id: "webapp", titulo: "WEB APP", carpeta: "webapp/", que: "la web app", de: "de la web app" },
];

async function dibujarActualizaciones() {
  const estado = await api.actualizaciones();
  return [
    encabezado("Actualizaciones", [
      "El núcleo (", h("span", { class: "mono", text: "backend/" }), ") y la web app (",
      h("span", { class: "mono", text: "webapp/" }),
      ") se traen cada uno de los releases de su repo de GitHub y se reemplazan enteros. " +
      "No se editan acá: lo que haya que cambiar se cambia en el repo y se publica un release.",
    ]),
    consumirConfirmacion(),
    estado.can_restart
      ? null
      : aviso("info", "Este servidor no se reinicia desde acá",
        "Lo arrancó uvicorn o un supervisor ajeno, no python -m webapp. Después de actualizar hay que reiniciar el proceso a mano."),

    h("div", { class: "seccion" }, [h("span", { text: "REPOSITORIOS" })]),
    tarjetaRepos(estado),

    ...COMPONENTES_UPDATE.flatMap((c) => bloqueComponente(c, estado)),

    h("div", { class: "tabla__pie", text:
      "Antes de aplicar, el núcleo nuevo se arranca en otro proceso contra una base vacía, y la web app nueva se compila entera: si algo falla, no se toca nada. " +
      "Una dependencia nueva en su requirements.txt no se instala sola; se avisa." }),
  ];
}

/** Los repos de los dos componentes, editables; vacío vuelve al por defecto. */
function tarjetaRepos(estado) {
  const campos = {};
  const campo = (c) => {
    const comp = estado.components[c.id];
    campos[c.id] = h("input", { class: "entrada", value: estado.repos[c.id] || "", placeholder: comp.default_repo, style: { maxWidth: "380px" } });
    return dato(`Repo ${c.de}`, campos[c.id],
      `owner/nombre en GitHub. Por defecto ${comp.default_repo}. Vacío vuelve al por defecto.`);
  };
  const resultado = h("div", { style: { fontSize: "12px", color: "var(--texto-3)" } });
  return h("div", { class: "tarjeta" }, [
    ...COMPONENTES_UPDATE.map(campo),
    dato("Token", estado.has_token
      ? h("span", { class: "badge badge--ok", text: "cargado" })
      : h("span", { class: "badge", text: "sin token" }),
      `Un repo privado necesita un token de GitHub como variable secreta en Config → Variables: ${estado.token_variables.join(" o ")}. Un repo público no.`),
    h("div", { style: { display: "flex", gap: "8px", alignItems: "center", padding: "10px 13px" } }, [
      h("button", { class: "btn btn--primario", text: "Guardar repos", onClick: async (e) => {
        e.target.disabled = true;
        try {
          await api.configurarActualizaciones({ core: campos.core.value.trim(), webapp: campos.webapp.value.trim() });
          confirmacion = "Repos guardados.";
          await dibujarSeccion(seccionPorId("actualizaciones"));
        } catch (err) {
          resultado.textContent = err.message;
          e.target.disabled = false;
        }
      } }),
      resultado,
    ]),
  ]);
}

/** Lo instalado, los releases y la subida sin internet de un componente. */
function bloqueComponente(c, estado) {
  const comp = estado.components[c.id];
  const listaReleases = h("div");
  poner(listaReleases, h("div", { class: "tabla__vacia", text: "Buscando releases en GitHub…" }));
  cargarReleases(c, listaReleases, comp);

  return [
    h("div", { class: "seccion" }, [
      h("span", {}, [c.titulo, h("span", { class: "seccion__suave" }, [" · ", h("a", { href: `https://github.com/${comp.repo}/releases`, target: "_blank", rel: "noopener", text: comp.repo })])]),
    ]),
    h("div", { class: "tarjeta" }, [
      dato("Instalado", comp.tag
        ? h("span", { class: "mono", text: comp.tag })
        : h("span", { class: "badge", text: "anterior al actualizador" }),
        comp.tag
          ? `Aplicado ${cuandoTexto(comp.applied_at)} desde ${comp.source || "?"}.`
          : `Este ${c.carpeta} se trajo a mano, antes de que existiera esta pantalla: no hay tag anotado. La primera actualización lo deja anotado.`),
      c.id === "core"
        ? dato("Versión del núcleo",
            (comp.version || "").startsWith("0.0.0")
              ? h("span", { class: "badge", text: "sin metadatos de pip" })
              : h("span", { class: "mono", text: comp.version || "?" }),
            (comp.version || "").startsWith("0.0.0")
              ? "El núcleo lee su versión de los metadatos que deja pip install; un backend/ traído de un release no los tiene. La referencia acá es el tag de arriba."
              : "Lo que declara el plugin builtin core en el catálogo.")
        : dato("Carpeta del programa", h("span", { class: "mono", text: estado.program_dir })),
      comp.has_previous
        ? dato("Anterior", h("span", {}, [
            h("span", { class: "mono", text: (comp.previous && comp.previous.tag) || "sin tag" }),
            h("button", { class: "btn btn--chico", style: { marginLeft: "8px" }, text: "Volver a este", onClick: () => revertirComponente(c) }),
            h("button", { class: "btn btn--chico", style: { marginLeft: "4px" }, text: "Descartar", onClick: () => descartarAnterior(c) }),
          ]), `Quedó guardado al lado (${c.carpeta.replace("/", "")}.anterior/) por si la app no levantaba con el nuevo. Volver también pide reiniciar.`)
        : null,
    ]),

    h("div", { class: "seccion" }, [
      h("span", { text: "RELEASES PUBLICADOS" }),
      h("div", { style: { display: "flex", gap: "10px", alignItems: "center" } }, [
        h("label", { class: "fila-control", style: { cursor: "pointer", fontSize: "12px", fontWeight: "400" } }, [
          h("input", { type: "checkbox", checked: incluirPrueba, onChange: (e) => { incluirPrueba = e.target.checked; cargarReleases(c, listaReleases, comp); } }),
          h("span", { text: "incluir releases de prueba" }),
        ]),
        h("button", { class: "btn btn--chico", text: "Volver a buscar", onClick: () => cargarReleases(c, listaReleases, comp) }),
      ]),
    ]),
    listaReleases,

    h("div", { class: "tarjeta", style: { marginTop: "8px" } }, [
      dato("Sin internet", (() => {
        const input = h("input", { type: "file", accept: ".tar.gz,.tgz,.zip", class: "entrada", style: { maxWidth: "380px" } });
        const campoTag = h("input", { class: "entrada", placeholder: "tag (opcional, ej. v0.2.1)", style: { maxWidth: "200px", marginLeft: "6px" } });
        return h("div", { style: { display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" } }, [
          input, campoTag,
          h("button", { class: "btn", text: "Instalar", onClick: (e) => {
            const archivo = input.files && input.files[0];
            if (!archivo) return;
            instalarRelease(c, { archivo, tag: campoTag.value.trim() }, e.target);
          } }),
        ]);
      })(),
        "El .tar.gz o .zip del tag, bajado en otra máquina desde la página de releases (Source code). Se valida igual que si viniera de GitHub."),
    ]),
  ];
}

async function cargarReleases(c, contenedor, comp) {
  poner(contenedor, h("div", { class: "tabla__vacia", text: "Buscando releases en GitHub…" }));
  let releases;
  try {
    releases = (await api.releases(c.id, incluirPrueba)).releases || [];
  } catch (e) {
    poner(contenedor, aviso("falta", e.message, (e.errores || []).join(" · ") || null));
    return;
  }
  if (!releases.length) {
    poner(contenedor, h("div", { class: "tabla__vacia", text: incluirPrueba ? `No hay ningún release publicado en ${comp.repo}.` : "No hay releases finales; sólo de prueba." }));
    return;
  }
  const columnas = [
    {
      clave: "tag", label: "Release", ancho: "170px",
      render: (r) => h("div", {}, [
        h("div", { style: { display: "flex", gap: "6px", alignItems: "center" } }, [
          h("span", { class: "mono", style: { fontWeight: "600" }, text: r.tag }),
          r.tag === comp.tag ? h("span", { class: "badge badge--ok", text: "instalado" }) : null,
        ]),
        r.prerelease ? h("span", { class: "badge badge--falta", text: "prueba" }) : h("span", { class: "badge", text: "final" }),
      ]),
    },
    { clave: "published_at", label: "Publicado", ancho: "110px", render: (r) => cuandoTexto(r.published_at ? Date.parse(r.published_at) / 1000 : 0) },
    {
      clave: "body", label: "Notas", envuelve: true,
      render: (r) => h("div", { style: { fontSize: "12px", whiteSpace: "pre-wrap", maxHeight: "72px", overflow: "hidden" }, title: r.body, text: r.body || "—" }),
    },
    {
      clave: "acciones", label: "", ancho: "100px",
      render: (r) => h("button", {
        class: "btn btn--chico", text: r.tag === comp.tag ? "Reinstalar" : "Instalar",
        onClick: (e) => instalarRelease(c, { tag: r.tag }, e.target),
      }),
    },
  ];
  poner(contenedor, tabla(columnas, releases, {}));
}

async function instalarRelease(c, { tag, archivo }, boton) {
  const etiqueta = tag || (archivo && archivo.name);
  confirmar({
    titulo: `Actualizar ${c.que} a ${etiqueta}`,
    texto: `Se reemplaza ${c.carpeta} entero; el actual queda guardado al lado para poder volver. Ningún run puede estar corriendo mientras se aplica, y después hay que reiniciar la app.`,
    alConfirmar: async () => {
      if (boton) { boton.disabled = true; boton.textContent = "Validando…"; }
      try {
        const r = archivo ? await api.instalarReleaseArchivo(c.id, archivo, tag || "") : await api.instalarRelease(c.id, tag);
        mostrarResultadoUpdate(c, r);
      } catch (e) {
        abrirModal({
          titulo: "No se aplicó",
          sub: e.message,
          cuerpo: h("pre", { class: "mono", style: { margin: "12px 16px", whiteSpace: "pre-wrap", fontSize: "11.5px" }, text: (e.errores || []).join("\n") || "Sin más detalle." }),
          acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => { document.querySelector(".velo")?.remove(); } })],
        });
        if (boton) { boton.disabled = false; boton.textContent = "Instalar"; }
      }
    },
  });
}

function mostrarResultadoUpdate(c, r) {
  const que = c.que.charAt(0).toUpperCase() + c.que.slice(1);
  const cuerpo = h("div", { style: { padding: "12px 16px", fontSize: "12.5px", lineHeight: "1.55" } }, [
    h("div", {}, [`${que} `, h("span", { class: "mono", text: r.applied.tag }), r.core_version ? ` (versión ${r.core_version})` : "", ` copiado en ${c.carpeta}. El anterior quedó guardado al lado.`]),
    r.new_requirements && r.new_requirements.length
      ? aviso("falta", "Pide dependencias que el actual no tenía", h("div", { class: "mono", style: { fontSize: "11.5px" }, text: r.new_requirements.join("\n") }))
      : null,
    h("div", { style: { marginTop: "8px" } }, [
      r.can_restart
        ? "Python ya tiene cargado el código viejo: hasta reiniciar sigue corriendo ese. Reiniciar corta la app unos segundos."
        : "Python ya tiene cargado el código viejo: hay que reiniciar el proceso a mano para que corra el nuevo.",
    ]),
  ]);
  const { cerrar } = abrirModal({
    titulo: "Actualización aplicada",
    sub: "Falta reiniciar.",
    cuerpo,
    acciones: [
      h("button", { class: "btn", text: "Más tarde", onClick: () => { cerrar(); dibujarSeccion(seccionPorId("actualizaciones")); } }),
      r.can_restart ? h("button", { class: "btn btn--primario", text: "Reiniciar ahora", onClick: () => { cerrar(); reiniciarApp(); } }) : null,
    ].filter(Boolean),
  });
}

/** Pide el reinicio y espera a que el servidor vuelva; después recarga la página entera. */
async function reiniciarApp() {
  poner(shell.vista, h("div", { class: "cargando", text: "Reiniciando… la app vuelve sola en unos segundos." }));
  try { await api.reiniciar(); } catch (e) { /* la conexión se corta justo al reiniciar: es lo esperado */ }
  const espera = (ms) => new Promise((r) => setTimeout(r, ms));
  await espera(1500);
  for (let i = 0; i < 40; i++) {
    try {
      await api.actualizaciones();
      location.hash = "#/config/actualizaciones";
      location.reload();
      return;
    } catch { await espera(1000); }
  }
  poner(shell.vista, aviso("error", "La app no volvió",
    "Si no levanta con lo nuevo, desde una consola en la carpeta del programa: python -m webapp --revertir-nucleo (o --revertir-webapp), y arrancarla de nuevo."));
}

function revertirComponente(c) {
  const carpeta = c.carpeta.replace("/", "");
  confirmar({
    titulo: `Volver a ${c.que} anterior`,
    texto: `Se intercambian ${carpeta}/ y ${carpeta}.anterior/. Lo que corre ahora queda guardado como anterior. Después hay que reiniciar.`,
    alConfirmar: async () => {
      try {
        const r = await api.revertirComponente(c.id);
        mostrarResultadoUpdate(c, { applied: { tag: r.tag || "anterior al actualizador" }, new_requirements: [], can_restart: r.can_restart });
      } catch (e) {
        confirmacion = null;
        poner(shell.vista, aviso("error", "No se pudo volver", e.message));
      }
    },
  });
}

async function descartarAnterior(c) {
  await api.descartarAnterior(c.id);
  confirmacion = `Se descartó ${c.que} anterior.`;
  await dibujarSeccion(seccionPorId("actualizaciones"));
}

function cuandoTexto(epoch) {
  if (!epoch) return "—";
  const f = new Date(epoch * 1000);
  return `${f.getDate()}/${f.getMonth() + 1}/${f.getFullYear()} ${String(f.getHours()).padStart(2, "0")}:${String(f.getMinutes()).padStart(2, "0")}`;
}

// ── Diagnóstico ─────────────────────────────────────────────────────────

const TONO = { ok: "ok", warn: "falta", error: "error" };

async function dibujarDiagnostico() {
  const reporte = await api.doctor();
  const checks = reporte.checks || [];

  const columnas = [
    {
      clave: "level", label: "", ancho: "76px",
      render: (c) => h("span", { class: `badge badge--${TONO[c.level] || "falta"}`,
                                 text: c.level === "warn" ? "aviso" : c.level }),
    },
    { clave: "name", label: "Chequeo", ancho: "180px", peso: "600" },
    {
      clave: "detail", label: "", envuelve: true,
      render: (c) => h("div", {}, [
        h("div", { text: c.message || "—" }),
        (c.detail || []).length
          ? h("div", { class: "mono", style: { fontSize: "11px", color: "var(--texto-3)", marginTop: "3px" },
                       text: c.detail.join(" · ") })
          : null,
      ]),
    },
    {
      clave: "fix", label: "", ancho: "150px", envuelve: true,
      render: (c) => c.fix
        ? h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)" }, text: c.fix })
        : "—",
    },
  ];

  const problemas = checks.filter((c) => c.level !== "ok").length;

  return [
    encabezado("Diagnóstico", [
      "Los mismos chequeos que ",
      h("span", { class: "mono", text: "python -m core.doctor" }),
      ", que corre sin levantar el servidor.",
    ]),
    consumirConfirmacion(),
    problemas
      ? aviso("falta", `${problemas} chequeo${problemas === 1 ? "" : "s"} con algo que mirar`,
              "Nada de esto impide arrancar; sí puede hacer fallar una ejecución.")
      : aviso("ok", "Todo en orden", null),
    h("div", { class: "seccion" }, [
      h("span", { text: "CHEQUEOS" }),
      h("button", { class: "btn", text: "Volver a chequear",
                    onClick: () => dibujarSeccion(SECCIONES[2]) }),
    ]),
    tabla(columnas, checks, { vacio: "El diagnóstico no devolvió ningún chequeo." }),
  ];
}


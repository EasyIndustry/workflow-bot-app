/**
 * La pila de tarjetas: un nodo por tarjeta.
 *
 * Tarjetas y texto son **el mismo artefacto**, no dos paneles: por eso son un
 * toggle y no una pantalla partida. Editar una tarjeta cambia el grafo en
 * memoria; guardar lo manda a `POST /flow/serialize` y el backend escribe el
 * Mermaid. El front no arma texto del DSL en ningún lado — es lo que hacía el
 * ayudante viejo y por eso guardaba flujos partidos.
 *
 * Ninguna tarjeta conoce un tool por nombre. El selector, los params, sus ayudas
 * y las salidas salen de `GET /tools`. Las variables disponibles se calculan del
 * grafo: los campos de la fila más las salidas de los nodos aguas arriba.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api } from "../api.js";
import { crearCampo } from "../components/campo.js";
import { autocompletar } from "../components/autocompletar.js";
import { resaltarVariables } from "../components/resaltar-variables.js";

/**
 * @param {object} grafo      el grafo mutable que edita la vista
 * @param {object} catalogo   GET /tools
 * @param {object} opts       {alCambiar, seleccionado, alSeleccionar}
 */
export function pilaDeTarjetas(grafo, catalogo, { alCambiar, seleccionado, alSeleccionar, alUbicar } = {}) {
  const orden = ordenTopologico(grafo);
  const porId = new Map((catalogo.tools || []).map((t) => [t.id, t]));

  // Abrir una tarjeta cuelga el cuerpo sobre la caja que ya está en pantalla,
  // sin redibujar. Cuando el click terminaba en `dibujar()`, la vista se rehacía
  // entera y con ella el div que scrollea, que nace en el tope: abrir una
  // tarjeta de abajo de una pila scrolleada la mandaba fuera de la vista (#2).
  // Es el mismo camino que ya se había elegido para el filtro — tocar las
  // tarjetas que están, no reconstruirlas.
  const cajas = orden.map((id, i) => tarjeta(id, grafo, porId, catalogo, {
    alCambiar, abierta: seleccionado === id, alSeleccionar, alUbicar, indice: i + 1,
    alAlternar: (quien) => {
      const caja = cajas.find((c) => c.dataset.nodo === quien);
      const abriendo = !caja.estaAbierta();
      // Una sola abierta a la vez, como antes: la pila con todo desplegado no
      // se puede recorrer.
      for (const c of cajas) c.abrir(abriendo && c === caja);
      // El estado sigue viviendo en la vista, para que sobreviva a un redibujo
      // de verdad — cambiar de tool, agregar o quitar un nodo.
      if (alSeleccionar) alSeleccionar(abriendo ? quien : null);
    },
  }));

  return h("div", {}, [
    ...cajas,
    h("div", { style: { marginTop: "12px", display: "flex", gap: "7px" } }, [
      h("button", { class: "btn", text: "+ Acción",
                    onClick: () => agregar(grafo, "action", alCambiar, alSeleccionar) }),
      h("button", { class: "btn", text: "+ Decisión",
                    onClick: () => agregar(grafo, "decision", alCambiar, alSeleccionar) }),
    ]),
  ]);
}

/**
 * El orden de la pila: el del recorrido, no el del archivo.
 *
 * Una pila ordenada por línea muestra los nodos como quedaron escritos; ordenada
 * por recorrido muestra el flujo como se ejecuta, que es lo que alguien tiene en
 * la cabeza cuando lo edita.
 */
function ordenTopologico(grafo) {
  const ids = Object.keys(grafo.nodes || {});
  const salientes = new Map(ids.map((id) => [id, []]));
  for (const a of grafo.edges || []) {
    if (salientes.has(a.from)) salientes.get(a.from).push(a.to);
  }
  const raiz = grafo.start_node && grafo.nodes[grafo.start_node]
    ? grafo.start_node
    : ids.find((id) => grafo.nodes[id].type === "start") || ids[0];

  const visto = new Set();
  const salida = [];
  const pila = raiz ? [raiz] : [];
  while (pila.length) {
    const id = pila.shift();
    if (visto.has(id)) continue;
    visto.add(id);
    salida.push(id);
    pila.push(...(salientes.get(id) || []));
  }
  // Los inalcanzables van al final: existen y hay que poder arreglarlos.
  return [...salida, ...ids.filter((id) => !visto.has(id))];
}

export const TIPO_ROTULO = { start: "inicio", action: "acción", decision: "decisión", unknown: "sin definir" };

/**
 * El cuerpo de una tarjeta, suelto de la pila — para el panel compacto que
 * abre el diagrama (`workflows-node-panel.js`) sin duplicar el selector de
 * tool, los params ni la edición de aristas.
 */
export function contenidoDeNodo(id, grafo, catalogo, alCambiar) {
  const nodo = grafo.nodes[id];
  const porId = new Map((catalogo.tools || []).map((t) => [t.id, t]));
  const manifest = nodo.type === "action" ? porId.get(nodo.fn) : null;
  return contenido(id, grafo, manifest, catalogo, alCambiar);
}

function tarjeta(id, grafo, porId, catalogo, { alCambiar, abierta, alSeleccionar, alAlternar, alUbicar, indice }) {
  const nodo = grafo.nodes[id];
  const manifest = nodo.type === "action" ? porId.get(nodo.fn) : null;
  const desconocido = nodo.type === "action" && !manifest;

  const cabecera = h("div", {
    style: {
      display: "flex", alignItems: "center", gap: "9px", padding: "9px 12px",
      cursor: "pointer", background: abierta ? "var(--fondo-cabecera)" : "var(--fondo)",
    },
    onClick: () => alAlternar(id),
  }, [
    h("span", {
      style: {
        flex: "0 0 20px", width: "20px", height: "20px", borderRadius: "3px",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "var(--fondo-cabecera)", border: "1px solid var(--borde)",
        fontSize: "10px", fontFamily: "var(--mono)", color: "var(--texto-3)",
      },
      text: String(indice),
    }),
    h("div", { style: { minWidth: "0", flex: "1" } }, [
      h("div", { style: { fontSize: "12.5px", fontWeight: "500" },
                 text: nodo.display || nodo.label || nodo.variable || nodo.fn || id }),
      h("div", { class: "mono", style: { fontSize: "10.5px", color: "var(--texto-4)" },
                 text: `${id} · ${nodo.type === "action" ? (nodo.fn || "sin tool") : TIPO_ROTULO[nodo.type] || nodo.type}` }),
    ]),
    desconocido
      ? h("span", { class: "badge badge--error", text: "no instalado" })
      : null,
    // "Ubicar": centrar el diagrama en este nodo, sin abrirlo ahí. Abrir la
    // tarjeta ya no abre el panel flotante del diagrama —eran dos editores del
    // mismo nodo a la vista, y se leía mal—; esto es el puente que queda.
    alUbicar
      ? h("button", {
          class: "btn btn--chico", title: "Ubicar el nodo en el diagrama", text: "Ubicar",
          onClick: (e) => { e.stopPropagation(); alUbicar(id); },
        })
      : null,
    nodo.type !== "start"
      ? h("button", {
          class: "btn btn--chico", title: "Quitar el nodo", style: { color: "var(--rojo)" },
          onClick: (e) => { e.stopPropagation(); quitar(grafo, id, alCambiar, alSeleccionar); },
        }, [icono(ICONOS.basura, 11, 2)])
      : null,
  ]);

  // `data-nodo`: el filtro de la pila (workflows.js) esconde tarjetas por id
  // sin reconstruirlas — reconstruir haría perder el foco del campo de filtro.
  const caja = h("div", { class: "tarjeta", style: { marginBottom: "7px" }, dataset: { nodo: id } },
    [cabecera]);

  // `abrir`/`estaAbierta` colgados del elemento, como `dibujarGrafo` con
  // `actualizarSeleccion`: la pila tiene que poder cerrar la otra tarjeta sin
  // pasar por la vista, que es lo que hacía perder el scroll.
  caja.estaAbierta = () => caja.children.length > 1;
  caja.abrir = (si) => {
    if (si === caja.estaAbierta()) return;
    // El cuerpo se arma recién al abrir, como antes: son cuarenta tarjetas y
    // cada cuerpo pregunta sus params al catálogo.
    if (si) caja.appendChild(contenido(id, grafo, manifest, catalogo, alCambiar));
    else caja.removeChild(caja.lastChild);
    cabecera.style.background = si ? "var(--fondo-cabecera)" : "var(--fondo)";
  };
  if (abierta) caja.abrir(true);
  return caja;
}

/**
 * Lo que se puede buscar de un nodo, en una sola cadena en minúsculas: id,
 * nombre visible, variable, tool y params (claves y valores). Es lo mismo
 * que alguien recuerda de un paso cuando el flujo tiene cuarenta.
 */
export function textoBuscable(id, nodo) {
  const params = Object.entries(nodo.params || {}).flatMap(([k, v]) => [k, v]);
  return [id, nodo.display, nodo.label, nodo.variable, nodo.fn, TIPO_ROTULO[nodo.type], ...params]
    .filter(Boolean).map((v) => String(v).toLowerCase()).join(" ");
}

function contenido(id, grafo, manifest, catalogo, alCambiar) {
  const nodo = grafo.nodes[id];
  const partes = [];
  // El bloque de params extra, si el tool acepta: necesita la tarjeta ya
  // armada para escuchar los cambios de los params de arriba.
  let extra = null;

  if (nodo.type === "start") {
    partes.push(nota("El nodo de arranque. No hace nada: marca por dónde empieza el recorrido."));
    partes.push(...aristas(id, grafo, alCambiar));
    return h("div", { style: { borderTop: "1px solid var(--borde)" } }, partes);
  }

  // Nombre visible: es lo que se ve en la traza y en el render, así que va
  // primero y no escondido entre los params.
  partes.push(campoTexto("Nombre visible", nodo.display || "",
    "Lo que se ve en el render y en la traza. Vacío, se muestra el id del tool.",
    (valor) => { nodo.display = valor; alCambiar({ redibujar: false }); }));

  if (nodo.type === "decision") {
    partes.push(campoTexto("Variable", nodo.variable || "",
      "El valor que se compara en las condiciones de las aristas que salen de acá.",
      (valor) => { nodo.variable = valor; alCambiar({ redibujar: false }); }));
    partes.push(...aristas(id, grafo, alCambiar));
    return h("div", { style: { borderTop: "1px solid var(--borde)" } }, partes);
  }

  // El selector de tool: la lista completa del catálogo, agrupada por categoría.
  const categorias = new Map();
  for (const t of catalogo.tools || []) {
    const c = t.category || "otros";
    if (!categorias.has(c)) categorias.set(c, []);
    categorias.get(c).push(t);
  }
  const selector = h("select", {
    class: "selector",
    onChange: (e) => {
      nodo.fn = e.target.value;
      // Los params del tool anterior no aplican al nuevo: dejarlos manda claves
      // que el tool no declara, y el diagnóstico las reporta como ignoradas.
      nodo.params = {};
      alCambiar({ redibujar: true });
    },
  }, [
    h("option", { value: "", text: "— elegir un tool —" }),
    ...[...categorias].map(([categoria, tools]) =>
      h("optgroup", { label: categoria }, tools.map((t) =>
        h("option", { value: t.id, text: `${t.label || t.id} · ${t.id}` })))),
  ]);
  selector.value = nodo.fn || "";

  partes.push(h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [
      h("div", { class: "campo__nombre" }, ["Tool", h("span", { class: "requerido", text: " *" })]),
    ]),
    h("div", { class: "campo__control" }, [
      selector,
      h("div", { class: "campo__ayuda" }, [
        manifest ? (manifest.doc || "Sin documentación.") : "",
        !manifest && nodo.fn
          ? h("span", { style: { color: "var(--rojo)" },
                        text: `"${nodo.fn}" no está instalado en esta máquina. El flujo se puede editar y ver, pero no ejecutar.` })
          : null,
      ]),
    ]),
  ]));

  // Lo que este nodo puede interpolar, para el autocompletado de cada campo. Se
  // calcula al abrir la lista y no acá, así refleja el grafo del momento. El
  // resaltado además sabe qué nombres son nodos, para dibujar `{NODO.salida}`
  // como la relación que es.
  const variables = () => opcionesDeVariables(id, grafo, catalogo);
  variables.esNodo = (nombre) => Object.prototype.hasOwnProperty.call(grafo.nodes, nombre);

  if (manifest) {
    partes.push(subtitulo("Parámetros", "salen del manifest del tool"));
    // De qué plugin es el tool: lo dice el catálogo, y hace falta para que un
    // param que declara su colección pueda ofrecerla.
    const plugin = (catalogo.plugins || []).find((p) => (p.tools || []).includes(manifest.id));
    for (const p of manifest.params || []) {
      partes.push(paramDelCatalogo(nodo, p, alCambiar, plugin && plugin.name, variables));
    }
    if (!(manifest.params || []).length) {
      partes.push(nota("Este tool no declara parámetros."));
    }
    if (manifest.extra_params) {
      partes.push(nota(manifest.extra_params_doc
        || "Acepta parámetros extra además de los declarados."));
      // Cuáles son depende de lo elegido en el propio nodo, así que se
      // preguntan y se dibujan aparte; ese bloque también se hace cargo de los
      // sobrantes, para no dibujar dos veces el mismo param.
      extra = bloqueParamsExtra(nodo, manifest, alCambiar, plugin && plugin.name, variables);
      partes.push(extra.elemento);
    } else {
      // Params que están en el nodo y el tool no declara. El diagnóstico los
      // reporta como ignorados; acá se pueden ver y borrar.
      for (const parte of sobrantesDelNodo(nodo, manifest, [], alCambiar, variables)) {
        partes.push(parte);
      }
    }

    if ((manifest.outputs || []).length) {
      partes.push(subtitulo("Deja disponible", "para los nodos que vienen después"));
      partes.push(h("div", { style: { padding: "0 13px 11px" } }, [
        h("div", { class: "fichas" }, manifest.outputs.map((o) =>
          h("span", { class: "ficha", title: o.doc || "" }, [`{${o.name}}`]))),
      ]));
    }
  }

  partes.push(subtitulo("Variables que puede usar", "de la fila y de los nodos anteriores"));
  partes.push(variablesDisponibles(id, grafo, catalogo));
  partes.push(...aristas(id, grafo, alCambiar));

  const caja = h("div", { style: { borderTop: "1px solid var(--borde)" } }, partes);
  if (extra) extra.escuchar(caja);
  return caja;
}

// ── Piezas ──────────────────────────────────────────────────────────────

function subtitulo(texto, suave) {
  return h("div", {
    style: {
      padding: "7px 13px", background: "var(--fondo-panel)",
      borderTop: "1px solid var(--borde-2)", borderBottom: "1px solid var(--borde-2)",
      fontSize: "10.5px", fontWeight: "600", color: "var(--texto-2)", letterSpacing: ".03em",
    },
  }, [texto.toUpperCase(), suave ? h("span", { style: { fontWeight: "400", color: "var(--texto-4)" }, text: ` · ${suave}` }) : null]);
}

function nota(texto) {
  return h("div", { style: { padding: "10px 13px", fontSize: "11.5px", color: "var(--texto-3)", lineHeight: "1.5" }, text: texto });
}

function campoTexto(rotulo, valor, ayuda, alEscribir) {
  const entrada = h("input", { class: "entrada", type: "text", value: valor,
                               onInput: (e) => alEscribir(e.target.value) });
  return h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: rotulo })]),
    h("div", { class: "campo__control" }, [entrada, h("div", { class: "campo__ayuda", text: ayuda })]),
  ]);
}

/**
 * Un param declarado por el tool.
 *
 * Se dibuja con `crearCampo`, el mismo componente que usan Plug ins y el
 * asistente de fuentes — pero **todo se guarda como texto**: el DSL no tiene
 * tipos, y el valor puede ser `{una.interpolación}` en lugar de un número.
 */
function paramDelCatalogo(nodo, p, alCambiar, plugin, variables) {
  const actual = (nodo.params || {})[p.name]
    ?? (p.aliases || []).map((a) => (nodo.params || {})[a]).find((v) => v !== undefined);

  const campo = crearCampo({
    name: p.name,
    // Un int declarado se edita como texto: `{intentos}` es un valor válido y un
    // input numérico no lo dejaría escribir.
    type: p.type === "json" || p.type === "bool" || p.type === "enum" ? p.type : "str",
    label: p.name, required: p.required, choices: p.choices, default: p.default,
    placeholder: p.placeholder,
    // El param dice de qué colección salen sus valores y el campo la ofrece
    // como buscador: la tarjeta no sabe cuál es, la trae del manifest.
    options_from: plugin ? p.options_from : "",
    opciones: plugin && p.options_from
      ? () => api.clavesDeColeccion(plugin, p.options_from)
      : null,
    doc: [p.doc, p.config_key ? `Si se deja vacío, sale de la configuración (${p.config_key}).` : ""]
      .filter(Boolean).join(" "),
  }, actual);

  const escribir = () => {
    let valor;
    try {
      valor = campo.leer();
    } catch {
      return;  // JSON a medio escribir: se ignora hasta que sea válido
    }
    const texto = typeof valor === "object" ? JSON.stringify(valor) : String(valor ?? "");
    nodo.params = nodo.params || {};
    if (texto === "" && !p.required) delete nodo.params[p.name];
    else nodo.params[p.name] = texto;
    alCambiar({ redibujar: false });
  };
  campo.elemento.querySelectorAll("input, textarea, select").forEach((el) => {
    el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", escribir);
  });
  conVariables(campo.elemento, variables);
  return campo.elemento;
}

/**
 * Los campos de texto de un param saben de variables: tipear `{` abre la lista
 * (también en el textarea del JSON), y las `{variables}` escritas se ven
 * marcadas dentro del campo (sólo en los de una línea). Un campo con
 * `<datalist>` —el que ofrece los items de una colección— no abre la lista:
 * el navegador ya le pone su propio desplegable y serían dos encimados.
 */
function conVariables(raiz, variables) {
  raiz.querySelectorAll('input[type="text"]').forEach((el) => resaltarVariables(el, opcionesDeResaltado(variables)));
  if (!variables) return;
  raiz.querySelectorAll('input[type="text"]:not([list]), textarea').forEach((el) => autocompletar(el, variables));
}

/**
 * Los params extra que el tool acepta, según lo que el nodo ya tiene elegido.
 *
 * El manifest dice `extra_params: true` —"acepto más de los declarados"— pero
 * no cuáles: dependen del propio nodo. Una Action de Connections define sus
 * `{variables}` en la URL y el payload, así que hasta no elegirla no hay lista;
 * antes de esto había que abrir la otra pantalla, anotar los nombres y
 * escribirlos a mano en el .mmd. Se le preguntan al backend y se dibujan con el
 * mismo campo que los declarados.
 *
 * Esta tarjeta sigue sin conocer un tool por nombre: le pregunta a cualquiera
 * que acepte extras y dibuja lo que venga, que para casi todos es nada.
 */
function bloqueParamsExtra(nodo, manifest, alCambiar, plugin, variables) {
  const caja = h("div", {});
  let pedido = 0;
  let ultima = null;
  let descubiertos = [];

  // Lo que puede cambiar la lista es el valor de los params declarados; no hace
  // falta volver a preguntar mientras se escribe en uno de los descubiertos.
  const huella = () => JSON.stringify((manifest.params || []).map((p) => (nodo.params || {})[p.name] ?? ""));

  function pintar() {
    poner(caja,
      descubiertos.length ? subtitulo("Parámetros de lo elegido", "los declara la conexión") : null,
      ...descubiertos.map((p) => paramDelCatalogo(nodo, p, alCambiar, plugin, variables)),
      ...sobrantesDelNodo(nodo, manifest, descubiertos.map((p) => p.name), alCambiar, variables));
  }

  async function refrescar() {
    const actual = huella();
    if (actual === ultima) return;
    ultima = actual;
    const mio = ++pedido;
    let extras = [];
    try {
      extras = await api.paramsExtra(manifest.id, nodo.params || {});
    } catch {
      // Que no se pueda describir no puede romper la edición del flujo: la
      // tarjeta sigue andando como antes, con los sobrantes a mano.
      extras = [];
    }
    if (mio !== pedido) return;  // llegó tarde: ya hay una respuesta más nueva
    const declarados = new Set((manifest.params || []).flatMap((p) => [p.name, ...(p.aliases || [])]));
    descubiertos = extras.filter((p) => !declarados.has(p.name));
    pintar();
  }

  pintar();
  refrescar();

  return {
    elemento: caja,
    /** Escucha los params de arriba; cambiar la conexión cambia la lista entera. */
    escuchar(raiz) {
      let timer = null;
      const alTocar = () => {
        clearTimeout(timer);
        timer = setTimeout(refrescar, 250);
      };
      raiz.addEventListener("input", alTocar);
      raiz.addEventListener("change", alTocar);
    },
  };
}

/**
 * Params que están en el nodo y no los cubre nadie: ni el manifest ni lo que se
 * descubrió. El diagnóstico los reporta como ignorados; acá se ven y se borran.
 */
function sobrantesDelNodo(nodo, manifest, descubiertos, alCambiar, variables) {
  const cubiertos = new Set([
    ...(manifest.params || []).flatMap((p) => [p.name, ...(p.aliases || [])]),
    ...descubiertos,
  ]);
  const sobrantes = Object.keys(nodo.params || {}).filter((k) => !cubiertos.has(k));
  if (!sobrantes.length) return [];
  return [
    subtitulo("Parámetros no declarados",
      manifest.extra_params ? "los acepta este tool" : "el tool los ignora al ejecutar"),
    ...sobrantes.map((clave) => paramLibre(nodo, clave, alCambiar, manifest.extra_params, variables)),
  ];
}

function paramLibre(nodo, clave, alCambiar, aceptado, variables) {
  const entrada = h("input", { class: "entrada entrada--mono", type: "text",
                               value: nodo.params[clave] ?? "",
                               onInput: (e) => { nodo.params[clave] = e.target.value; alCambiar({ redibujar: false }); } });
  if (variables) autocompletar(entrada, variables);
  const elemento = h("div", { class: "campo" + (aceptado ? "" : " campo--falta") }, [
    h("div", { class: "campo__etiqueta" }, [
      h("div", { class: "campo__nombre mono", style: { fontSize: "11.5px" }, text: clave }),
    ]),
    h("div", { class: "campo__control" }, [
      h("div", { style: { display: "flex", gap: "6px" } }, [
        entrada,
        h("button", { class: "btn btn--chico", title: "Quitar el parámetro",
                      onClick: () => { delete nodo.params[clave]; alCambiar({ redibujar: true }); } },
          [icono(ICONOS.basura, 11, 2)]),
      ]),
      aceptado ? null : h("div", { class: "campo__error", text: "El tool no declara este parámetro: al ejecutar se ignora." }),
    ]),
  ]);
  resaltarVariables(entrada, opcionesDeResaltado(variables));
  return elemento;
}

// El núcleo todavía no resuelve `{NODO.salida}`: es core#30. Cuando llegue
// vendorizado, esto pasa a true y la marca deja de ser ámbar.
const NODO_CALIFICADO_SOPORTADO = false;

function opcionesDeResaltado(variables) {
  return { esNodo: (variables && variables.esNodo) || (() => false), nodoSoportado: NODO_CALIFICADO_SOPORTADO };
}

/**
 * Las salidas que dejan los nodos aguas arriba de `id`, agrupadas por nombre.
 *
 * Se calcula del grafo, no de una lista escrita a mano. Agrupadas porque el
 * núcleo mezcla las salidas en un único diccionario por nombre: si dos nodos
 * anteriores dejan `ruta`, `{ruta}` vale la del último que corrió, y quien
 * escribe la tarjeta tiene que saberlo. Elegir el nodo (`{NODO.ruta}`) es
 * core#30; hasta que llegue, lo único honesto es mostrar quiénes la dejan.
 *
 * @returns {Array<{nombre: string, de: string[]}>}  `de` son los nombres visibles (o ids) de los nodos
 */
function salidasAguasArriba(id, grafo, catalogo) {
  const porId = new Map((catalogo.tools || []).map((t) => [t.id, t]));
  const entrantes = new Map();
  for (const a of grafo.edges || []) {
    if (!entrantes.has(a.to)) entrantes.set(a.to, []);
    entrantes.get(a.to).push(a.from);
  }

  const arriba = new Set();
  const pila = [...(entrantes.get(id) || [])];
  while (pila.length) {
    const actual = pila.pop();
    if (arriba.has(actual)) continue;
    arriba.add(actual);
    pila.push(...(entrantes.get(actual) || []));
  }

  const porNombre = new Map();
  for (const nid of arriba) {
    const nodo = grafo.nodes[nid];
    if (!nodo || nodo.type !== "action") continue;
    const manifest = porId.get(nodo.fn);
    for (const o of (manifest && manifest.outputs) || []) {
      if (!porNombre.has(o.name)) porNombre.set(o.name, { nombre: o.name, de: [] });
      porNombre.get(o.name).de.push(nodo.display || nid);
    }
  }
  return [...porNombre.values()];
}

/** "la deja Mover PDF", o "la dejan Mover PDF y Mover DXF · vale la del último que corra". */
function quienLaDeja(salida) {
  if (salida.de.length === 1) return `la deja ${salida.de[0]}`;
  const lista = salida.de.slice(0, -1).join(", ") + " y " + salida.de[salida.de.length - 1];
  return `la dejan ${lista} · vale la del último que corra`;
}

// Los nombres de Config cambian poco y la lista se abre con cada tecla: se
// piden una vez por rato, no por tecla.
let _envCache = { cuando: 0, promesa: null };
function nombresDeEnv() {
  const ahora = Date.now();
  if (!_envCache.promesa || ahora - _envCache.cuando > 30_000) {
    _envCache = {
      cuando: ahora,
      promesa: api.env().then((r) => (r.items || []).map((i) => ({
        nombre: `env.${i.name}`,
        detalle: i.secret ? "secreto de Config" : "variable de Config",
      }))).catch(() => []),
    };
  }
  return _envCache.promesa;
}

/**
 * Las opciones del autocompletado de un campo de este nodo: las salidas de
 * arriba, con quién las deja, y los nombres de Config. Las columnas de la fila
 * no están: un flujo corre contra cualquier fuente y no las conoce.
 */
async function opcionesDeVariables(id, grafo, catalogo) {
  const salidas = salidasAguasArriba(id, grafo, catalogo).map((s) => ({ nombre: s.nombre, detalle: quienLaDeja(s) }));
  return [...salidas, ...(await nombresDeEnv())];
}

/**
 * Lo que este nodo puede interpolar: campos de la fila más salidas de los nodos
 * aguas arriba. La misma lista que ofrece el autocompletado al tipear `{`.
 */
function variablesDisponibles(id, grafo, catalogo) {
  const salidas = salidasAguasArriba(id, grafo, catalogo);
  const repetidas = salidas.filter((s) => s.de.length > 1);

  return h("div", { style: { padding: "0 13px 11px" } }, [
    h("div", { class: "fichas" }, [
      h("span", { class: "ficha", title: "Cualquier columna de la fila de la fuente" }, ["{columna de la fila}"]),
      h("span", { class: "ficha", title: "Variables y secretos de Config" }, ["{env.CLAVE}"]),
      ...salidas.map((s) => h("span", { class: "ficha", title: quienLaDeja(s) }, [
        `{${s.nombre}}`,
        s.de.length > 1 ? h("span", { style: { color: "var(--ambar)" }, text: ` ×${s.de.length}` }) : null,
      ])),
    ]),
    h("div", { class: "campo__ayuda", text: salidas.length
      ? "Tipeá { en cualquier parámetro para elegirlas de una lista, con quién deja cada una."
      : "Ningún nodo anterior deja salidas. Las que aparecen son las que siempre están." }),
    ...repetidas.map((s) => h("div", { class: "campo__ayuda", style: { color: "var(--ambar)" }, text:
      `{${s.nombre}} la dejan ${s.de.join(" y ")}: vale la del último que corra. Elegir de cuál todavía no se puede (núcleo, core#30).` })),
  ]);
}

/** Las aristas que salen del nodo: a dónde va y con qué condición. */
function aristas(id, grafo, alCambiar) {
  const salientes = (grafo.edges || []).filter((a) => a.from === id);
  const otros = Object.keys(grafo.nodes).filter((n) => n !== id);

  const fila = (arista) => {
    const destino = h("select", {
      class: "selector",
      onChange: (e) => { arista.to = e.target.value; alCambiar({ redibujar: true }); },
    }, otros.map((n) => h("option", { value: n, text: etiquetaCorta(n, grafo) })));
    destino.value = arista.to;

    // Tipear no puede redibujar: reconstruir la tarjeta con cada tecla le sacaba
    // el foco al input y había que volver a hacer click por cada caracter. El
    // valor se guarda en el grafo igual; el redibujo —que es lo que actualiza
    // el rótulo de la arista en el diagrama— se hace al salir del campo.
    const condicion = h("input", {
      class: "entrada entrada--mono", type: "text", value: arista.condition || "",
      placeholder: "sin condición",
      onInput: (e) => { arista.condition = e.target.value || null; alCambiar({ redibujar: false }); },
      onChange: () => alCambiar({ redibujar: true }),
    });

    return h("div", { class: "campo", style: { gap: "8px", alignItems: "center" } }, [
      h("div", { style: { flex: "0 0 40px", fontSize: "11px", color: "var(--texto-4)" }, text: "va a" }),
      h("div", { style: { flex: "1", minWidth: "0" } }, [destino]),
      h("div", { style: { flex: "0 0 30px", fontSize: "11px", color: "var(--texto-4)", textAlign: "center" }, text: "si" }),
      h("div", { style: { flex: "1", minWidth: "0" } }, [condicion]),
      h("button", { class: "btn btn--chico", title: "Quitar la arista",
                    onClick: () => {
                      grafo.edges.splice(grafo.edges.indexOf(arista), 1);
                      alCambiar({ redibujar: true });
                    } }, [icono(ICONOS.basura, 11, 2)]),
    ]);
  };

  return [
    subtitulo("A dónde sigue", "vacío = siempre"),
    ...salientes.map(fila),
    salientes.length ? null : nota("El flujo termina acá: no hay ninguna arista saliente."),
    h("div", { style: { padding: "0 13px 11px" } }, [
      h("button", {
        class: "btn btn--chico", text: "+ Arista",
        disabled: !otros.length,
        onClick: () => {
          grafo.edges.push({ from: id, to: otros[0], condition: null });
          alCambiar({ redibujar: true });
        },
      }),
      h("div", { class: "campo__ayuda" }, [
        "Desde una acción, las condiciones son ",
        h("span", { class: "mono", text: "ok" }), ", ",
        h("span", { class: "mono", text: "err" }), " o ",
        h("span", { class: "mono", text: "loop" }),
        ". Desde una decisión, es el **valor** que tiene que tener la variable, " +
        "sin el nombre: ",
        h("span", { class: "mono", text: "Produccion" }),
        ". Una coma arma una lista — ",
        h("span", { class: "mono", text: "Impresion,Terminado" }),
        " entra si el valor es alguno de los dos.",
      ]),
    ]),
  ].filter(Boolean);
}

function etiquetaCorta(id, grafo) {
  const nodo = grafo.nodes[id] || {};
  const nombre = nodo.display || nodo.label || nodo.variable || nodo.fn || "";
  return nombre ? `${id} — ${nombre}` : id;
}

// ── Alta y baja de nodos ────────────────────────────────────────────────

function agregar(grafo, tipo, alCambiar, alSeleccionar) {
  // Ids numerados como los del archivo, para que un flujo editado desde acá se
  // lea igual que uno escrito a mano.
  let n = Object.keys(grafo.nodes).length + 1;
  while (grafo.nodes[`N${n}`]) n++;
  const id = `N${n}`;

  grafo.nodes[id] = tipo === "decision"
    ? { type: "decision", variable: "", display: "", line: null }
    : { type: "action", fn: "", params: {}, display: "", line: null };

  // Se engancha al final del recorrido: un nodo suelto es un error del parser,
  // y agregarlo desconectado obligaría a acordarse de conectarlo.
  const ultimo = ultimoDelRecorrido(grafo, id);
  if (ultimo) grafo.edges.push({ from: ultimo, to: id, condition: null });

  alSeleccionar(id);
  alCambiar({ redibujar: true });
}

function ultimoDelRecorrido(grafo, excepto) {
  const conSalida = new Set((grafo.edges || []).map((a) => a.from));
  const ids = Object.keys(grafo.nodes).filter((n) => n !== excepto);
  return ids.reverse().find((n) => !conSalida.has(n)) || ids[0] || null;
}

function quitar(grafo, id, alCambiar, alSeleccionar) {
  // Las aristas que entraban se re-enganchan a lo que seguía, para no dejar el
  // flujo partido en dos al borrar un nodo del medio.
  const entrantes = grafo.edges.filter((a) => a.to === id);
  const salientes = grafo.edges.filter((a) => a.from === id);
  grafo.edges = grafo.edges.filter((a) => a.from !== id && a.to !== id);
  for (const entrada of entrantes) {
    for (const salida of salientes) {
      grafo.edges.push({ from: entrada.from, to: salida.to, condition: entrada.condition });
    }
  }
  delete grafo.nodes[id];
  alSeleccionar(null);
  alCambiar({ redibujar: true });
}

/**
 * El render del flujo, en SVG dibujado a mano, con la estética de n8n.
 *
 * Sin Mermaid y sin ninguna otra librería. Mermaid pesa unos 3 MB y habría que
 * embarcarla para que la app funcione sin internet — que es un requisito, corre
 * en una máquina de producción. Y no hace falta: el backend ya devuelve el
 * grafo que el motor entiende (`GET /workflows/{n}/graph`), así que dibujarlo
 * es acomodar cajas y líneas. A cambio se gana lo que Mermaid no da: los
 * colores del sistema de diseño, el estado de cada nodo tras un dry run, el
 * dry run disparado desde el propio lienzo, y clic para abrir la tarjeta.
 *
 * **Por qué se parece a n8n.** Quien opera esto ya vio un editor de flujos, y
 * ese editor es n8n: lienzo con grilla de puntos, cada paso una caja cuadrada
 * con su ícono y su nombre adentro, puntos de conexión en los
 * bordes, curvas suaves entre cajas, los controles de zoom abajo a la
 * izquierda y el botón de correr abajo en el medio. Copiar esas convenciones
 * no es decoración: es no tener que explicar dónde se hace clic. La única
 * diferencia deliberada es el sentido: acá el flujo **baja**, como en el
 * archivo Mermaid que se guarda (`flowchart TD`), así el dibujo propio y el de
 * Mermaid se leen en el mismo orden. Lo que n8n tiene y acá no está (agregar
 * un nodo desde el "+" de una arista, arrastrar para reconectar) no se dibuja:
 * la UI no promete lo que el núcleo no cumple.
 *
 * El layout es por capas (Sugiyama, la misma familia que dagre/Mermaid): el
 * camino más largo desde el inicio decide la fila, y adentro de cada fila el
 * orden sale de un barycenter contra la fila de al lado — ver `porCapas`.
 */

import { h } from "../dom.js";

const NS = "http://www.w3.org/2000/svg";

// La caja de un nodo es casi cuadrada como en n8n, y el nombre va **adentro**,
// corto, debajo del ícono. n8n lo pone afuera, pero acá el flujo baja y lo que
// hay debajo de cada caja son los cables que salen de ella: un nombre afuera
// los pisaba, y los rótulos "ok"/"err" de las aristas pisaban al nombre. El
// nombre completo, el tool y los params van en el tooltip (`tooltipDeNodo`).
const NODO_ANCHO = 116;
const NODO_ALTO = 100;

// El nodo abierto: crece en el lugar y muestra adentro sus parámetros, en vez
// de abrir una tarjeta flotante encima del dibujo. El tamaño es fijo y el
// contenido scrollea si no entra — medir el HTML antes de acomodar las cajas
// obligaría a dibujar, medir y volver a dibujar, y el layout dejaría de ser
// una sola pasada.
const NODO_ANCHO_ABIERTO = 400;
const NODO_ALTO_ABIERTO = 420;

const SEP_X = 60;      // entre nodos de la misma fila
const SEP_Y = 78;      // entre filas (el eje del flujo): lugar para el rótulo de la arista
const MARGEN = 40;

const s = (tag, attrs = {}, hijos = []) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, String(v));
  }
  for (const hijo of [].concat(hijos).flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.appendChild(typeof hijo === "string" ? document.createTextNode(hijo) : hijo);
  }
  return el;
};

/**
 * @param {object} grafo   lo que devuelve GET /workflows/{n}/graph
 * @param {object} opts
 *   - alClic: fn(nodeId)
 *   - estados: {nodeId: "ok"|"err"|"skip"}
 *   - pasos: {nodeId: paso del trace} — para el tooltip
 *   - recorridas: Set("from→to") de las aristas por las que pasó el dry run
 *   - seleccionado: nodeId
 *   - alCorrer: fn() — si viene, el lienzo dibuja el botón de dry run
 *   - dry: {corriendo, resumen, tono, hayResultado}
 *   - extras: HTMLElement que va al lado del botón de correr (el selector de
 *     registro, que este módulo no conoce: es cosa de la vista y de la API)
 *   - edicion: si viene, el lienzo se puede editar. Este módulo no muta el
 *     grafo nunca: describe el gesto y la vista decide.
 *       {tools: [manifest de GET /tools], alAgregar(tipo, {desde, arista, fn}),
 *        alConectar(from, to), alQuitarArista(arista), alQuitarNodo(id),
 *        alCambiarCondicion(arista, valor), alSeleccionarArista(clave|null)}
 *   - vista: {escala, panX, panY} con la que arrancar — la que tenía el dibujo
 *     anterior, para que agregar un nodo no devuelva el lienzo al origen.
 *   - aristaSeleccionada: la clave ("from→to") que tenía seleccionada el dibujo
 *     anterior, para no perderla al redibujar después de editar su condición.
 *   - alClicFondo: fn() — un clic en el lienzo vacío (cerrar lo abierto)
 *   - panelDeNodo: fn(id) → HTMLElement con el editor del nodo. Si viene, el
 *     nodo `seleccionado` se dibuja **abierto**, con ese panel adentro. Este
 *     módulo no sabe qué hay en el panel: lo arma la vista, que es la que
 *     conoce el catálogo y los params.
 */
export function dibujarGrafo(grafo, {
  alClic, estados = {}, pasos = {}, recorridas = new Set(),
  seleccionado = null, alCorrer = null, dry = null, extras = null,
  edicion = null, vista = null, aristaSeleccionada = null, panelDeNodo = null,
  alClicFondo = null,
} = {}) {
  const nodos = grafo.nodes || {};
  const aristas = grafo.edges || [];
  const ids = Object.keys(nodos);

  if (!ids.length) {
    const vacio = h("div", { class: "tabla__vacia", text: "El flujo todavía no tiene ningún nodo." });
    vacio.actualizarSeleccion = () => {};
    vacio.enfocarNodo = () => {};
    vacio.actualizarDryRun = () => {};
    return vacio;
  }

  // Cuál nodo está abierto: el seleccionado, si la vista sabe dibujarle un
  // panel. Uno solo a la vez — dos cajas grandes dejan de ser un diagrama.
  const abierto = panelDeNodo && seleccionado && nodos[seleccionado] ? seleccionado : null;
  const anchoDe = (id) => (id === abierto ? NODO_ANCHO_ABIERTO : esDummy(id) ? ANCHO_DUMMY : NODO_ANCHO);
  const altoDe = (id) => (id === abierto ? NODO_ALTO_ABIERTO : NODO_ALTO);

  const { capas, cadenaPorArista, segmentosOrden, haciaAtras } = porCapas(grafo);
  const posicion = new Map();
  // Los nodos fantasma de ruteo (ver `expandirConDummies`) ocupan una franja
  // angosta, no un cajón entero: si pesaran como un nodo real, una arista que
  // salta muchas capas ensancharía el diagrama entero sin necesidad.
  //
  // El alto de cada fila es el del nodo más alto que tiene: con un nodo
  // abierto su fila se agranda y el resto del dibujo se corre, que es lo que
  // hace que el nodo se expanda de verdad en vez de taparles el lugar a sus
  // vecinos. Las medidas de cada uno viajan en `posicion`: las aristas, los
  // puertos y el encuadre las leen de ahí y no de las constantes.
  const altosFila = capas.map((fila) => Math.max(
    NODO_ALTO, ...fila.filter((id) => !esDummy(id)).map(altoDe),
  ));
  let yFila = MARGEN;
  capas.forEach((fila, i) => {
    let acum = 0;
    fila.forEach((id) => {
      posicion.set(id, {
        x: MARGEN + acum, y: yFila, ancho: anchoDe(id),
        // Un fantasma ocupa el alto entero de su fila: su punto medio es por
        // dónde pasa la arista, y tiene que caer en el medio del hueco.
        alto: esDummy(id) ? altosFila[i] : altoDe(id),
      });
      acum += anchoDe(id) + SEP_X;
    });
    yFila += altosFila[i] + SEP_Y;
  });

  // El orden ya decide qué va al lado de qué; esto decide EN QUÉ X exacto,
  // acercando cada nodo al promedio de sus vecinos reales — lo mismo que hace
  // dagre (Brandes-Köpf) para que una arista larga, que ya viene partida en
  // fantasmas por capa, quede lo más derecha posible en vez de zigzaguear:
  // sin este paso cada capa se armaba centrada por su cuenta, sin memoria de
  // por dónde entraba o salía cada fantasma en la capa de al lado, y una
  // arista que atravesaba muchas capas terminaba serpenteando de lado a lado.
  alinearX(capas, posicion, segmentosOrden);

  let minX = Infinity;
  let maxX = -Infinity;
  for (const pos of posicion.values()) {
    minX = Math.min(minX, pos.x);
    maxX = Math.max(maxX, pos.x + pos.ancho);
  }
  const corrimiento = MARGEN - minX;
  for (const pos of posicion.values()) pos.x += corrimiento;

  const ancho = (maxX - minX) + MARGEN * 2;
  const alto = yFila - SEP_Y + MARGEN;

  // Dónde se engancha cada arista en el borde de un nodo real: no siempre el
  // centro. Con varias flechas saliendo o llegando al mismo nodo, todas por el
  // centro es un amontonamiento — acá se reparten a lo ancho del borde según
  // dónde está el próximo punto de la ruta, en el mismo orden en que van a
  // quedar dibujadas. Es también lo que decide dónde va cada puerto.
  const anclas = calcularAnclas(cadenaPorArista, posicion);

  // El tooltip es HTML flotando sobre el lienzo, no un `<title>` del SVG: el
  // nativo tarda un segundo en aparecer, no acepta varias líneas con formato
  // y no se puede pintar con los colores del sistema.
  const tooltip = crearTooltip();
  // Los tres paneles de edición y el arrastre para conectar existen sólo si la
  // vista pasó `edicion`; sin eso el lienzo es de lectura.
  const menu = edicion ? crearMenuDeAlta(edicion.tools || []) : null;
  const destinos = edicion ? crearMenuDeDestinos() : null;
  const editorCond = edicion ? crearEditorDeCondicion() : null;
  const conexion = edicion ? crearConexion(edicion, menu, tooltip) : null;

  // Una arista queda **seleccionada** al hacer clic: sus herramientas siguen a
  // la vista aunque el mouse se vaya. Sin esto, mover el mouse hacia el "+"
  // salía del área de la línea y las herramientas desaparecían justo antes de
  // poder apretarlas.
  let aristaSel = null;
  const avisarSeleccion = (clave) => {
    if (edicion && edicion.alSeleccionarArista) edicion.alSeleccionarArista(clave);
  };
  const soltarArista = () => {
    if (!aristaSel) return;
    aristaSel.marcarSeleccionada(false);
    aristaSel = null;
    avisarSeleccion(null);
  };
  const seleccionarArista = (info) => {
    const mismo = aristaSel === info;
    soltarArista();
    if (mismo) return;   // un segundo clic la suelta, como los nodos
    aristaSel = info;
    info.marcarSeleccionada(true);
    avisarSeleccion(info.clave);
  };

  const aristasInfo = aristas.map((a) => haciaAtras.has(a)
    ? aristaSuelta(a, posicion, { edicion, menu, editorCond, alSeleccionar: seleccionarArista })
    : trazoDeArista(a, cadenaPorArista.get(a), posicion, anclas, { edicion, menu, editorCond, alSeleccionar: seleccionarArista })).filter(Boolean);

  // A dónde puede ir una arista nueva desde un nodo: todos los demás menos los
  // que ya tiene conectados, para que el desplegable no ofrezca un no-op.
  const destinosDe = (id) => {
    const yaEstan = new Set(aristas.filter((e) => e.from === id).map((e) => e.to));
    return ids.filter((otro) => otro !== id && !yaEstan.has(otro)).map((otro) => ({
      id: otro,
      etiqueta: nodos[otro].display || nodos[otro].label || nodos[otro].variable || nodos[otro].fn || otro,
      secundaria: nodos[otro].type === "action" ? (nodos[otro].fn || "sin tool") : (nodos[otro].type || ""),
    }));
  };
  const abrirDestinos = edicion ? (id, e) => destinos.abrir(
    e.clientX, e.clientY, id, destinosDe(id), (to) => edicion.alConectar(id, to),
  ) : null;

  // Clic en un nodo: suelta la arista que estuviera seleccionada, así no
  // quedan dos cosas resaltadas por motivos distintos.
  const alClicNodo = alClic ? (id) => { soltarArista(); alClic(id); } : null;

  const nodosInfo = ids.map((id) => nodo(id, nodos[id], posicion.get(id), {
    alClic: alClicNodo, estado: estados[id], paso: pasos[id], seleccionado: seleccionado === id,
    puertos: puertosDe(id, cadenaPorArista, anclas), tooltip, edicion, menu, conexion, abrirDestinos,
    panel: id === abierto ? panelDeNodo(id) : null,
  })).filter(Boolean);

  const svg = s("svg", {
    width: ancho, height: alto, viewBox: `0 0 ${ancho} ${alto}`,
    style: "display:block; overflow:visible",
  }, [
    defs(),
    ...aristasInfo.map((t) => t.elementos).flat(),
    ...nodosInfo.map((n) => n.grupo),
  ]);

  const { envoltura, lienzo } = envolverEnLienzo(svg, ancho, alto);
  envoltura.appendChild(tooltip.elemento);
  if (menu) envoltura.appendChild(menu.elemento);
  if (destinos) envoltura.appendChild(destinos.elemento);
  if (editorCond) envoltura.appendChild(editorCond.elemento);
  if (conexion) conexion.montar(svg, lienzo, envoltura, new Map(nodosInfo.map((n) => [n.id, n])));
  if (vista) lienzo.aplicarVista(vista);
  // El nodo abierto, entero a la vista. Se hace después de reponer el
  // encuadre y una vez que el visor ya tiene tamaño: en el mismo turno todavía
  // mide 0 y no habría con qué comparar.
  if (abierto && posicion.has(abierto)) {
    const pos = posicion.get(abierto);
    requestAnimationFrame(() => lienzo.asegurarVisible(pos.x, pos.y, pos.ancho, pos.alto));
  }

  if (edicion) {
    // Un clic en el fondo suelta la arista seleccionada y cierra el nodo que
    // estuviera abierto. Mirando el destino: el clic de la propia arista, de
    // un nodo o de un panel no es "en el fondo". Un paneo no cuenta: el
    // arrastre corta su propio `click` antes de llegar acá (ver
    // `hacerPaneable`), así que mover el dibujo no cierra lo que uno estaba
    // mirando.
    envoltura.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest(".lienzo__arista, [data-nodo-id], [data-interactivo], .lienzo__panel")) return;
      soltarArista();
      if (alClicFondo) alClicFondo();
    });
    // Y si venía una arista seleccionada de antes del redibujo, se recupera.
    if (aristaSeleccionada) {
      const previa = aristasInfo.find((x) => x.clave === aristaSeleccionada);
      if (previa) { aristaSel = previa; previa.marcarSeleccionada(true); }
      else avisarSeleccion(null);
    }
  }

  // Resaltar o soltar un nodo muta atributos en el propio SVG, no reconstruye
  // nada: reconstruir tiraría el `transform` de paneo/zoom que ya se acumuló.
  // Quien llama (la pantalla de Workflows) usa esto para abrir la tarjeta
  // flotante de un nodo sin resetear la vista del diagrama.
  const porId = new Map(nodosInfo.map((n) => [n.id, n]));
  let actual = seleccionado;
  envoltura.actualizarSeleccion = (nuevoId) => {
    if (actual && porId.has(actual)) porId.get(actual).marcarSeleccion(false);
    if (nuevoId && porId.has(nuevoId)) porId.get(nuevoId).marcarSeleccion(true);
    actual = nuevoId;
  };

  // El buscador de la cabecera: centra el nodo encontrado con zoom y lo
  // resalta un momento en un color que no se confunda con la selección
  // (azul) — el aviso tiene que notarse aunque el nodo ya esté seleccionado.
  let temporizadorResaltado = null;
  envoltura.enfocarNodo = (id) => {
    const pos = posicion.get(id);
    if (!pos) return;
    lienzo.centrarEn(pos.x + pos.ancho / 2, pos.y + pos.alto / 2, Math.max(1, lienzo.obtenerEscala()));
    if (temporizadorResaltado) clearTimeout(temporizadorResaltado);
    if (!porId.has(id)) return;
    const info = porId.get(id);
    info.marcarBuscado(true);
    temporizadorResaltado = setTimeout(() => info.marcarBuscado(false, actual === id), 1200);
  };

  // El resultado de un dry run se pinta **encima** del dibujo que ya está, sin
  // rearmarlo: correr desde el lienzo y que se pierda el encuadre que uno venía
  // mirando sería justo lo contrario de tenerlo ahí a mano.
  const pill = alCorrer ? botonDeCorrida(alCorrer, dry, extras) : null;
  envoltura.actualizarDryRun = ({ estados: nuevos = {}, pasos: nuevosPasos = {}, recorridas: nuevasAristas, dry: estadoDry } = {}) => {
    for (const info of nodosInfo) info.aplicarEstado(nuevos[info.id], nuevosPasos[info.id]);
    if (nuevasAristas) for (const t of aristasInfo) t.marcarRecorrida(nuevasAristas.has(t.clave));
    if (pill && estadoDry) pill.actualizar(estadoDry);
  };

  // Volver a armar el panel del nodo abierto sin rehacer el dibujo: lo usa el
  // dry run, que le agrega la sección de parámetros resueltos.
  envoltura.actualizarPanel = () => {
    if (!abierto) return;
    const info = porId.get(abierto);
    if (info && info.reemplazarPanel) info.reemplazarPanel(panelDeNodo(abierto));
  };

  if (pill) envoltura.appendChild(pill.elemento);
  for (const t of aristasInfo) t.marcarRecorrida(recorridas.has(t.clave));

  envoltura.lienzo = lienzo;
  return envoltura;
}

/** Los recursos compartidos del SVG: las puntas de flecha y la sombra del nodo. */
function defs() {
  const punta = (id, color) => s("marker", {
    id, viewBox: "0 0 8 8", refX: "7", refY: "4",
    markerWidth: "6", markerHeight: "6", orient: "auto-start-reverse",
  }, [s("path", { d: "M0,0 L8,4 L0,8 z", fill: color })]);
  return s("defs", {}, [
    punta("punta", "var(--grafo-linea)"),
    punta("punta-ok", "var(--verde)"),
    punta("punta-err", "var(--rojo-borde)"),
    punta("punta-cond-ok", "var(--verde-borde)"),
    // La sombra bajita y difusa es lo que hace que la caja se despegue del
    // lienzo gris, como en n8n: sin ella los nodos se leen como recortes.
    s("filter", { id: "sombra-nodo", x: "-30%", y: "-30%", width: "160%", height: "180%" }, [
      s("feDropShadow", { dx: "0", dy: "1", stdDeviation: "2", "flood-color": "#000", "flood-opacity": "0.14" }),
    ]),
  ]);
}

// ── El lienzo ───────────────────────────────────────────────────────────

const ZOOM_MIN = 0.05;
const ZOOM_MAX = 3;
const ZOOM_PASO = 1.25;
const PASO_GRILLA = 20;

/**
 * Mete un SVG ya dibujado en el visor con paneo y zoom. Lo usan los dos
 * renders del diagrama —el propio y el de Mermaid— para que se miren y se
 * muevan igual.
 *
 * El lienzo es "infinito": el contenedor sólo recorta (`overflow:hidden`) y
 * todo el movimiento —paneo y zoom— es un `transform` sobre el propio SVG,
 * no el scroll nativo. Con scroll nativo, arrastrar sólo desplazaba algo si
 * el contenido ya desbordaba el visor: con poco zoom, o un diagrama chico,
 * no había adónde scrollear y panear no hacía nada. Con `transform` se
 * puede correr en cualquier dirección siempre, haya o no algo del otro
 * lado — como un canvas de verdad, no como una página larga.
 *
 * @returns {{envoltura: HTMLElement, lienzo: object}}
 */
export function envolverEnLienzo(svg, ancho, alto) {
  // La grilla de puntos es del contenedor, no del SVG: así se extiende por
  // todo el visor aunque el diagrama sea chico, y al panear se corre con él
  // (`background-position`) en vez de quedarse pegada a la pantalla — que es
  // lo que hace que el gesto se sienta como mover un mapa y no como
  // scrollear una imagen.
  const contenedor = h("div", {
    class: "lienzo",
    style: { overflow: "hidden", padding: "0", width: "100%", height: "100%", position: "relative" },
  }, [svg]);

  const lienzo = crearLienzo(svg, ancho, alto, contenedor);
  hacerPaneable(contenedor, lienzo);
  contenedor.addEventListener("wheel", lienzo.alRueda, { passive: false });
  fijarAlBordeDerecho(contenedor, lienzo);

  // `overflow:hidden` acá también, y no sólo `width/height:100%`: un flex
  // item no encoge por debajo del ancho de su contenido salvo que alguien se
  // lo pida, y esto se corta antes de que ese desborde suba por la cadena de
  // flexbox — la caja que lo aloja queda **siempre** del mismo tamaño, el
  // que decide el layout de la pantalla, y lo único que cambia adentro es
  // cuánto entra.
  const envoltura = h("div", { style: { position: "relative", width: "100%", height: "100%", overflow: "hidden", minWidth: "0" } }, [
    contenedor,
    lienzo.elemento,
  ]);
  return { envoltura, lienzo };
}

/**
 * El lienzo: paneo y zoom sobre un único `transform: translate(...) scale(...)`
 * en vez de scroll nativo — lo que lo hace sentir infinito en cualquier
 * dirección, no sólo cuando el contenido desborda el visor.
 */
function crearLienzo(svg, anchoBase, altoBase, contenedor) {
  let escala = 1;
  let panX = 0;
  let panY = 0;

  svg.style.transformOrigin = "0 0";
  const aplicar = () => {
    svg.style.transform = `translate(${panX}px, ${panY}px) scale(${escala})`;
    // La grilla acompaña al contenido: mismo origen, mismo zoom.
    const paso = PASO_GRILLA * escala;
    contenedor.style.backgroundSize = `${paso}px ${paso}px`;
    contenedor.style.backgroundPosition = `${panX}px ${panY}px`;
  };
  aplicar();

  /** Mueve el lienzo en píxeles de pantalla — el paneo, siempre disponible. */
  const mover = (dx, dy) => { panX += dx; panY += dy; aplicar(); };

  /**
   * Cambia la escala manteniendo fijo en pantalla el punto del diagrama que
   * está bajo (clientX, clientY) — el centro de la ventana si no se pasa
   * ninguno, que es lo que corresponde a los botones. Sin esto la escala
   * siempre crece desde el origen del canvas: acercar con el mouse sobre un
   * nodo de una esquina lo manda derecho fuera de vista.
   */
  const zoomHacia = (nuevaEscala, clientX, clientY) => {
    nuevaEscala = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nuevaEscala));
    const rect = contenedor.getBoundingClientRect();
    const mouseX = (clientX ?? rect.left + rect.width / 2) - rect.left;
    const mouseY = (clientY ?? rect.top + rect.height / 2) - rect.top;
    // El punto del diagrama bajo el mouse, en coordenadas de contenido (sin
    // escalar), tiene que quedar bajo el mismo mouse después de escalar.
    const contenidoX = (mouseX - panX) / escala;
    const contenidoY = (mouseY - panY) / escala;
    escala = nuevaEscala;
    panX = mouseX - contenidoX * escala;
    panY = mouseY - contenidoY * escala;
    aplicar();
  };

  const acercar = (factor = ZOOM_PASO, clientX, clientY) => zoomHacia(escala * factor, clientX, clientY);
  const alejar = (factor = ZOOM_PASO, clientX, clientY) => zoomHacia(escala / factor, clientX, clientY);

  /**
   * Centra un punto del contenido (en sus coordenadas sin escalar) en medio
   * del visor. Lo usa el buscador de nodos: a diferencia de `zoomHacia`, acá
   * el punto de referencia no es el mouse sino el nodo encontrado.
   */
  const centrarEn = (contenidoX, contenidoY, nuevaEscala) => {
    if (nuevaEscala !== undefined) escala = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nuevaEscala));
    panX = contenedor.clientWidth / 2 - contenidoX * escala;
    panY = contenedor.clientHeight / 2 - contenidoY * escala;
    aplicar();
  };

  /** El diagrama entero a la vista. */
  const ajustar = () => {
    // Sólo achica: agrandar un diagrama chico a que llene la ventana lo deja
    // borroso sin ganar nada, cuando ya se lee bien a tamaño real.
    const disponibleX = contenedor.clientWidth - 16;
    const disponibleY = contenedor.clientHeight - 16;
    escala = Math.max(ZOOM_MIN, Math.min(1, disponibleX / anchoBase, disponibleY / altoBase));
    // Centrado, no pegado a la esquina: un diagrama chico dentro de una
    // ventana grande se lee mejor en el medio.
    panX = (contenedor.clientWidth - anchoBase * escala) / 2;
    panY = (contenedor.clientHeight - altoBase * escala) / 2;
    aplicar();
  };

  const alRueda = (e) => {
    e.preventDefault();
    // Exponencial y no lineal: así una rueda de mouse (saltos de ~100) y un
    // trackpad (deltas chicos y continuos) dan la misma sensación de zoom,
    // en vez de que uno salte de a saltos y el otro casi no se mueva.
    if (e.deltaY < 0) acercar(Math.pow(ZOOM_PASO, -e.deltaY / 100), e.clientX, e.clientY);
    else alejar(Math.pow(ZOOM_PASO, e.deltaY / 100), e.clientX, e.clientY);
  };

  // Abajo a la izquierda, como en n8n: arriba a la derecha chocaba con la
  // tarjeta flotante del nodo y con el borde de la sección.
  const boton = (contenido, titulo, onClick) => h("button", {
    class: "lienzo__boton", title: titulo, onClick,
  }, [contenido]);

  const elemento = h("div", { class: "lienzo__controles" }, [
    boton("+", "Acercar", () => acercar()),
    boton("−", "Alejar", () => alejar()),
    boton("⤢", "Ajustar el diagrama entero a la ventana", () => ajustar()),
    boton("1:1", "Volver al tamaño real", () => zoomHacia(1)),
  ]);

  /**
   * De píxeles de pantalla a coordenadas del dibujo (las del SVG sin
   * escalar). Lo usa el arrastre para conectar: el cable provisorio se dibuja
   * adentro del SVG y tiene que seguir al mouse esté como esté el zoom.
   */
  const aPuntoDeContenido = (clientX, clientY) => {
    const rect = contenedor.getBoundingClientRect();
    return { x: (clientX - rect.left - panX) / escala, y: (clientY - rect.top - panY) / escala };
  };

  /**
   * Corre el lienzo lo mínimo necesario para que una caja del contenido entre
   * en el visor. Lo usa el nodo que se abre: al pasar de 116×100 a 380×420
   * puede quedar medio afuera —o empujar fuera de la ventana lo que tenía
   * debajo—, y lo que uno acaba de tocar tiene que estar a la vista. Si no
   * entra ni corriéndolo, queda pegado al borde de arriba y de la izquierda,
   * que es por donde se empieza a leer.
   */
  const asegurarVisible = (x, y, ancho, alto, margen = 16) => {
    const izq = panX + x * escala;
    const arriba = panY + y * escala;
    const der = izq + ancho * escala;
    const abajo = arriba + alto * escala;
    const w = contenedor.clientWidth;
    const h = contenedor.clientHeight;
    let dx = 0;
    let dy = 0;
    if (der > w - margen) dx = (w - margen) - der;
    if (izq + dx < margen) dx = margen - izq;
    if (abajo > h - margen) dy = (h - margen) - abajo;
    if (arriba + dy < margen) dy = margen - arriba;
    if (dx || dy) mover(dx, dy);
  };

  // Guardar y volver a poner el encuadre: agregar un nodo o una arista rearma
  // el dibujo entero (cambia el layout), y sin esto cada alta devolvía el
  // lienzo al origen a escala 1.
  const obtenerVista = () => ({ escala, panX, panY });
  const aplicarVista = (v) => {
    if (!v) return;
    escala = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.escala || 1));
    panX = v.panX || 0;
    panY = v.panY || 0;
    aplicar();
  };

  return {
    elemento, alRueda, mover, centrarEn, ajustar, zoomHacia, aPuntoDeContenido,
    asegurarVisible, obtenerVista, aplicarVista, obtenerEscala: () => escala,
  };
}

/**
 * Arrastrar para mover el lienzo — en píxeles de pantalla, así que el mismo
 * gesto mueve igual de rápido esté como esté el zoom.
 */
function hacerPaneable(contenedor, lienzo) {
  let arrastrando = false;
  let movido = false;
  let ultimoX = 0;
  let ultimoY = 0;

  contenedor.style.cursor = "grab";
  contenedor.style.touchAction = "none";

  contenedor.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    // Un gesto que arranca sobre un nodo es un clic para abrir su tarjeta, no
    // el fondo del canvas para panear: se deja pasar tal cual, sin capturar
    // el puntero. `setPointerCapture` retarget también los eventos de mouse
    // de compatibilidad —el "click" incluido— al propio contenedor mientras
    // dura la captura, así que capturarlo acá es lo que apagaba el clic del
    // nodo entero, no sólo el arrastre.
    // Lo mismo vale para las herramientas de una arista (`data-interactivo`):
    // están fuera del grupo del nodo y sin esto el paneo se quedaba con el
    // clic de la ×.
    if (e.target.closest("[data-nodo], [data-interactivo]")) return;
    // Sin esto, el mismo gesto de arrastre arranca una selección de texto de
    // las etiquetas del SVG (o el "fantasma" de arrastrar una imagen): el
    // botón queda apretado moviendo el mouse y el navegador lo toma como
    // selección en vez de como el paneo que es.
    e.preventDefault();
    arrastrando = true;
    movido = false;
    ultimoX = e.clientX;
    ultimoY = e.clientY;
    contenedor.setPointerCapture(e.pointerId);
    contenedor.style.cursor = "grabbing";
    document.body.style.userSelect = "none";
  });

  contenedor.addEventListener("pointermove", (e) => {
    if (!arrastrando) return;
    const dx = e.clientX - ultimoX;
    const dy = e.clientY - ultimoY;
    // Un clic con la mano un poco temblorosa no debe contar como arrastre.
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) movido = true;
    lienzo.mover(dx, dy);
    ultimoX = e.clientX;
    ultimoY = e.clientY;
  });

  const soltar = () => {
    arrastrando = false;
    contenedor.style.cursor = "grab";
    document.body.style.userSelect = "";
  };
  contenedor.addEventListener("pointerup", soltar);
  contenedor.addEventListener("pointercancel", soltar);

  // Si el gesto fue un arrastre real, el click que sigue no tiene que abrir la
  // tarjeta del nodo que quedó debajo del mouse al soltar: se corta acá, antes
  // de que llegue al `onClick` del propio nodo.
  contenedor.addEventListener("click", (e) => {
    if (movido) { e.stopPropagation(); movido = false; }
  }, true);
}

/**
 * Cuando el divisor entre Nodos/Texto y el Diagrama se arrastra, esta caja
 * cambia de ancho por el lado izquierdo — el derecho no se mueve, es el borde
 * de la pantalla. Como `panX` es relativo a la esquina de **esta** caja,
 * cualquier corrimiento de esa esquina sin compensar hace que el dibujo
 * entero parezca correrse junto con el divisor.
 *
 * Se mide la esquina de verdad (`getBoundingClientRect`) en vez de inferirla
 * del ancho: inferirla asume que el borde derecho nunca se mueve, y aunque acá
 * es cierto, un `Δancho` no distingue "se movió la esquina" de "cambió el
 * padding/border" — medir la posición en pantalla no da lugar a esa duda.
 */
function fijarAlBordeDerecho(contenedor, lienzo) {
  // `contenedor` todavía no está en el documento en este punto — recién lo
  // inserta quien llama a `dibujarGrafo` — así que su posición acá no
  // significa nada. `ResizeObserver` igual dispara una vez apenas se
  // conecta, reportando la posición real: sin este `previa` de por medio, ese
  // primer aviso se leía como un corrimiento real y corría el lienzo de un
  // arranque, dejando el diagrama afuera de la vista antes de que nadie lo
  // tocara. La primera vuelta sólo guarda la posición; recién desde la
  // segunda hay una previa de verdad con la que comparar.
  let previa = null;
  const observador = new ResizeObserver(() => {
    const rect = contenedor.getBoundingClientRect();
    if (previa) {
      const dx = rect.left - previa.left;
      const dy = rect.top - previa.top;
      if (dx || dy) lienzo.mover(-dx, -dy);
    }
    previa = { left: rect.left, top: rect.top };
  });
  observador.observe(contenedor);
}

// ── El botón de correr, adentro del lienzo ──────────────────────────────

/**
 * El dry run se dispara desde el propio diagrama, abajo en el medio — el mismo
 * lugar donde n8n pone "Test workflow".
 *
 * Estaba sólo en la barra del pie, debajo de las dos columnas: correr y mirar
 * el resultado eran dos zonas distintas de la pantalla, y el resultado que más
 * importa —qué nodo pasó, cuál falló y con qué parámetros— se pinta acá
 * arriba. La barra del pie sigue existiendo con la tabla completa y lo que
 * falta configurar; esto es el disparador, al lado de lo que ilumina.
 */
function botonDeCorrida(alCorrer, dry, extras) {
  const rotulo = h("span", { text: "Correr en seco" });
  const glifo = h("span", { class: "lienzo__correr-glifo", text: "▶" });
  const boton = h("button", {
    class: "lienzo__correr",
    onClick: (e) => { e.stopPropagation(); alCorrer(); },
  }, [glifo, rotulo]);

  const resumen = h("div", { class: "lienzo__correr-resumen" });

  const elemento = h("div", { class: "lienzo__pie" }, [
    h("div", { class: "lienzo__pie-fila" }, [extras, boton]),
    resumen,
  ]);

  const actualizar = (estado = {}) => {
    boton.disabled = Boolean(estado.corriendo);
    boton.classList.toggle("lienzo__correr--corriendo", Boolean(estado.corriendo));
    glifo.textContent = estado.corriendo ? "◌" : "▶";
    rotulo.textContent = estado.corriendo
      ? "Corriendo…"
      : estado.hayResultado ? "Volver a correr en seco" : "Correr en seco";
    resumen.textContent = estado.resumen || "";
    resumen.className = "lienzo__correr-resumen"
      + (estado.tono ? ` lienzo__correr-resumen--${estado.tono}` : "");
  };
  actualizar(dry || {});

  return { elemento, actualizar };
}

// ── El layout ───────────────────────────────────────────────────────────

/**
 * Las filas del dibujo: capas por camino **más largo**, y adentro de cada
 * capa el orden que menos cruces deja — lo mismo que hace Mermaid/dagre, sin
 * traerlos.
 *
 * Un flujo con reintentos tiene ciclos (`N30 -->|loop| gate --> esperar -->
 * N30`), y con un ciclo el camino más largo no termina nunca: un flujo legacy
 * de 30 nodos salía de 92.896 px de alto. Antes se sacaban del cálculo las
 * aristas rotuladas `loop`, y eso tenía un agujero: el gate, cuya **única**
 * entrada era esa arista, quedaba sin nada que le entre y subía a la primera
 * fila como si fuera un inicio, arrastrando su tramo del ciclo hacia arriba.
 * Ahora se hace lo que hace dagre: recorrer el grafo desde el inicio con
 * todas las aristas y marcar como "hacia atrás" la que **cierra** cada ciclo
 * (`romperCiclos`) — en el ejemplo, `esperar --> N30`, que es la que de
 * verdad vuelve. Sacando sólo esas, lo que queda es un DAG en el que el gate
 * cae debajo del nodo que reintenta, que es donde uno lo busca. El rótulo
 * `loop` ya no decide el layout: sólo el punteado.
 */
const ANCHO_DUMMY = 4;
const esDummy = (id) => typeof id === "string" && id.startsWith("__ruta_");

function porCapas(grafo) {
  const haciaAtras = romperCiclos(grafo);
  const adelante = (grafo.edges || []).filter((a) => !haciaAtras.has(a));
  const capasBase = capasPorCaminoMasLargo(grafo, adelante);
  const { capas, cadenaPorArista, segmentosOrden } = expandirConDummies(capasBase, adelante);
  return { capas: ordenarCapas(capas, segmentosOrden), cadenaPorArista, segmentosOrden, haciaAtras };
}

/**
 * Qué aristas cierran un ciclo: DFS desde el inicio (y después desde cualquier
 * nodo que quedó sin visitar, por las islas), y una arista que apunta a un nodo
 * que todavía está en la pila del recorrido es la que vuelve. Se arranca por
 * el inicio a propósito, y no por cualquier nodo: así "hacia atrás" quiere
 * decir hacia el inicio, que es como lee el flujo quien lo escribió.
 *
 * Las aristas de un mismo nodo se visitan con las `loop` al final: si el
 * reintento se explora antes que el camino normal, el DFS llega al resto del
 * flujo a través del gate y termina marcando como "vuelta" alguna arista del
 * camino principal.
 */
function romperCiclos(grafo) {
  const ids = Object.keys(grafo.nodes || {});
  const edges = grafo.edges || [];
  const salientes = new Map(ids.map((id) => [id, []]));
  for (const a of edges) if (salientes.has(a.from) && salientes.has(a.to)) salientes.get(a.from).push(a);
  for (const lista of salientes.values()) {
    lista.sort((p, q) => (p.condition === "loop") - (q.condition === "loop"));
  }

  const haciaAtras = new Set();
  const estado = new Map();   // "abierto" mientras está en la pila, "cerrado" al terminar
  const visitar = (raiz) => {
    // Iterativo y no recursivo: un flujo largo no tiene por qué toparse con el
    // límite de la pila de JS.
    const pila = [{ id: raiz, i: 0 }];
    estado.set(raiz, "abierto");
    while (pila.length) {
      const tope = pila[pila.length - 1];
      const lista = salientes.get(tope.id) || [];
      if (tope.i >= lista.length) {
        estado.set(tope.id, "cerrado");
        pila.pop();
        continue;
      }
      const a = lista[tope.i++];
      const e = estado.get(a.to);
      if (e === "abierto") haciaAtras.add(a);
      else if (!e) {
        estado.set(a.to, "abierto");
        pila.push({ id: a.to, i: 0 });
      }
    }
  };

  const gradoEntrada = new Map(ids.map((id) => [id, 0]));
  for (const a of edges) if (gradoEntrada.has(a.to)) gradoEntrada.set(a.to, gradoEntrada.get(a.to) + 1);
  const raices = [
    ...(grafo.start_node && salientes.has(grafo.start_node) ? [grafo.start_node] : []),
    ...ids.filter((id) => (grafo.nodes[id] || {}).type === "start"),
    ...ids.filter((id) => gradoEntrada.get(id) === 0),
    ...ids,
  ];
  for (const id of raices) if (!estado.has(id)) visitar(id);
  return haciaAtras;
}

/**
 * Una arista que salta varias capas (por ejemplo, una decisión temprana que
 * alimenta un nodo mucho más abajo) se parte en tramos de una capa cada uno,
 * metiendo un nodo fantasma en cada capa intermedia — la misma técnica que
 * usa dagre. Sin esto, esa arista se dibuja en diagonal por encima de todo lo
 * que hay en el medio, porque ni el barycenter ni el conteo de cruces la
 * tienen en cuenta fila por fila: para esos algoritmos era una sola arista
 * "de la capa 2 a la 9", no nueve decisiones de orden.
 */
function expandirConDummies(capas, adelante) {
  const nivelDe = new Map();
  capas.forEach((fila, n) => fila.forEach((id) => nivelDe.set(id, n)));

  const nuevasCapas = capas.map((c) => [...c]);
  const cadenaPorArista = new Map();
  const segmentosOrden = [];
  let contador = 0;

  for (const a of adelante) {
    const n1 = nivelDe.get(a.from);
    const n2 = nivelDe.get(a.to);
    if (n1 === undefined || n2 === undefined) continue;

    const cadena = [a.from];
    for (let nivel = n1 + 1; nivel < n2; nivel++) {
      const idDummy = `__ruta_${contador++}__`;
      nuevasCapas[nivel].push(idDummy);
      cadena.push(idDummy);
    }
    cadena.push(a.to);

    cadenaPorArista.set(a, cadena);
    for (let i = 0; i < cadena.length - 1; i++) {
      segmentosOrden.push({ from: cadena[i], to: cadena[i + 1] });
    }
  }
  return { capas: nuevasCapas, cadenaPorArista, segmentosOrden };
}

/**
 * En qué punto del borde de un nodo real se engancha cada arista que sale o
 * entra — ordenadas por dónde está su vecino, así el orden de los enganches
 * no cruza entre sí más de lo que ya cruzan las propias líneas. Un nodo
 * fantasma no necesita esto: sólo tiene una arista de cada lado, siempre por
 * su centro.
 */
function calcularAnclas(cadenaPorArista, posicion) {
  const salientes = new Map();
  const entrantes = new Map();
  for (const [edge, cadena] of cadenaPorArista) {
    const vecinoDeSalida = posicion.get(cadena[1]);
    if (vecinoDeSalida) {
      if (!salientes.has(cadena[0])) salientes.set(cadena[0], []);
      salientes.get(cadena[0]).push({ edge, x: vecinoDeSalida.x });
    }
    const vecinoDeEntrada = posicion.get(cadena[cadena.length - 2]);
    if (vecinoDeEntrada) {
      const destino = cadena[cadena.length - 1];
      if (!entrantes.has(destino)) entrantes.set(destino, []);
      entrantes.get(destino).push({ edge, x: vecinoDeEntrada.x });
    }
  }

  // 0.25–0.75 del ancho de la caja, nunca hasta el borde mismo: pegado a la
  // esquina, un puerto se lee peor que uno que sale un poco adentro.
  const repartir = (mapaDeListas) => {
    const resultado = new Map();
    for (const lista of mapaDeListas.values()) {
      lista.sort((p, q) => p.x - q.x);
      const n = lista.length;
      lista.forEach((item, i) => resultado.set(item.edge, n === 1 ? 0.5 : 0.25 + (0.5 * i) / (n - 1)));
    }
    return resultado;
  };

  return { anchoSalida: repartir(salientes), anchoEntrada: repartir(entrantes) };
}

/**
 * Los puntos de conexión que se dibujan en los bordes de un nodo: uno por
 * arista, en la misma fracción de ancho que usa el trazo. Un nodo sin aristas
 * de un lado igual muestra su puerto en el centro — como en n8n, donde el
 * puerto libre es la señal de que ahí se puede enganchar algo.
 */
function puertosDe(id, cadenaPorArista, anclas) {
  const salida = new Set();
  const entrada = new Set();
  for (const [edge, cadena] of cadenaPorArista) {
    if (cadena[0] === id) salida.add(anclas.anchoSalida.get(edge) ?? 0.5);
    if (cadena[cadena.length - 1] === id) entrada.add(anclas.anchoEntrada.get(edge) ?? 0.5);
  }
  return {
    salida: salida.size ? [...salida] : [0.5],
    entrada: entrada.size ? [...entrada] : [0.5],
    hayEntrada: entrada.size > 0,
  };
}

/**
 * Camino más largo y no más corto: un nodo se ubica recién cuando ya se
 * calcularon **todos** los que le llegan, no sólo el más cercano. Con el más
 * corto, un nodo al que convergen una rama de un paso y otra de cinco
 * quedaba en la capa 1, y la arista de la rama larga cruzaba por encima de
 * todo el resto del dibujo para alcanzarlo.
 *
 * `adelante` ya viene sin las aristas que cierran ciclos (`romperCiclos`), así
 * que es un DAG y Kahn termina siempre.
 */
function capasPorCaminoMasLargo(grafo, adelante) {
  const ids = Object.keys(grafo.nodes || {});

  const salientes = new Map(ids.map((id) => [id, []]));
  const gradoEntrada = new Map(ids.map((id) => [id, 0]));
  for (const a of adelante) {
    if (!salientes.has(a.from) || !gradoEntrada.has(a.to)) continue;
    salientes.get(a.from).push(a.to);
    gradoEntrada.set(a.to, gradoEntrada.get(a.to) + 1);
  }

  // Kahn: un nodo se procesa recién cuando ya se restó una vez por cada
  // arista que le entra, así que para entonces todos sus orígenes ya le
  // dieron su nivel y el máximo que quede es el camino más largo real.
  const nivel = new Map();
  const restante = new Map(gradoEntrada);
  let cola = ids.filter((id) => restante.get(id) === 0);
  cola.forEach((id) => nivel.set(id, 0));
  while (cola.length) {
    const siguiente = [];
    for (const id of cola) {
      for (const destino of salientes.get(id) || []) {
        nivel.set(destino, Math.max(nivel.get(destino) ?? -1, nivel.get(id) + 1));
        restante.set(destino, restante.get(destino) - 1);
        if (restante.get(destino) === 0) siguiente.push(destino);
      }
    }
    cola = siguiente;
  }

  // Camino más largo deja cada nodo lo más **arriba** posible, pegado a su
  // origen. Un nodo cuyo único destino está muchas filas más abajo (los
  // "Comentario …" que desembocan todos en el mismo cierre) quedaba arriba
  // con un cable que bajaba media pantalla hasta el destino. dagre (Mermaid)
  // acorta esos cables al rankear: acá se hace lo equivalente bajando cada
  // nodo hasta justo encima de su sucesor más cercano, mientras eso lo aleje
  // de sus orígenes (sólo se baja, nunca se sube, así que sigue siendo un
  // orden topológico válido). Converge porque los niveles sólo crecen y
  // están acotados por el más profundo.
  let bajoAlguno = true;
  while (bajoAlguno) {
    bajoAlguno = false;
    for (const id of ids) {
      const destinos = (salientes.get(id) || []).map((d) => nivel.get(d)).filter((n) => n !== undefined);
      if (!destinos.length || !nivel.has(id)) continue;
      const deseado = Math.min(...destinos) - 1;
      if (deseado > nivel.get(id)) { nivel.set(id, deseado); bajoAlguno = true; }
    }
  }

  // Lo que no se resolvió no debería existir (el DAG se drena entero), pero
  // si un grafo raro lo produce hay que poder verlo: va al final.
  const sueltos = ids.filter((id) => !nivel.has(id));
  const maximo = Math.max(-1, ...nivel.values());
  sueltos.forEach((id) => nivel.set(id, maximo + 1));

  // Se arma denso con `Array.from` y no asignando por índice: un array con
  // huecos hace que `forEach` y `map` salteen las filas que faltan, y el
  // resultado es un SVG vacío sin ningún error.
  const total = Math.max(0, ...nivel.values()) + 1;
  const capas = Array.from({ length: total }, () => []);
  for (const [id, n] of nivel) capas[n].push(id);
  return capas;
}

const ITERACIONES_ORDEN = 6;

/**
 * El orden adentro de cada capa: barycenter de toda la vida (Sugiyama), la
 * misma heurística que usa dagre puertas adentro.
 *
 * Sin esto el orden es el que salió de recorrer el grafo — que en la práctica
 * es el orden en que las cosas están escritas en el .mmd, no cómo conectan de
 * verdad. Bajando y subiendo por turnos, cada nodo se reordena al promedio de
 * la posición de sus vecinos en la capa de al lado; después de unas pasadas
 * eso decanta en el orden que menos aristas cruza, sin que le importe en qué
 * línea del archivo estaba cada uno.
 */
function ordenarCapas(capas, edgesPlanas) {
  if (capas.length < 2) return capas;

  const entrantes = new Map();
  const salientes = new Map();
  for (const a of edgesPlanas) {
    if (!entrantes.has(a.to)) entrantes.set(a.to, []);
    entrantes.get(a.to).push(a.from);
    if (!salientes.has(a.from)) salientes.set(a.from, []);
    salientes.get(a.from).push(a.to);
  }

  const posEnCapa = (capa) => new Map(capa.map((id, i) => [id, i]));

  const barycentro = (id, vecinosDe, posReferencia) => {
    const posiciones = (vecinosDe.get(id) || [])
      .map((v) => posReferencia.get(v))
      .filter((p) => p !== undefined);
    if (!posiciones.length) return null;
    return posiciones.reduce((suma, p) => suma + p, 0) / posiciones.length;
  };

  /** Una pasada: reordena cada capa según el barycenter contra la de al lado. */
  const pasada = (capas, bajando) => {
    const nuevas = capas.map((c) => [...c]);
    const vecinosDe = bajando ? entrantes : salientes;
    const rango = bajando
      ? Array.from({ length: capas.length - 1 }, (_, i) => i + 1)
      : Array.from({ length: capas.length - 1 }, (_, i) => capas.length - 2 - i);

    for (const i of rango) {
      const referencia = posEnCapa(nuevas[bajando ? i - 1 : i + 1]);
      const conBarycentro = nuevas[i].map((id, orden) => ({
        id, orden, b: barycentro(id, vecinosDe, referencia),
      }));
      // Sin vecinos en la capa de al lado (un nodo suelto): se queda donde
      // estaba en vez de irse a un extremo, que sería más arbitrario todavía.
      conBarycentro.sort((x, y) => {
        if (x.b === null && y.b === null) return x.orden - y.orden;
        if (x.b === null) return 1;
        if (y.b === null) return -1;
        return x.b - y.b || x.orden - y.orden;
      });
      nuevas[i] = conBarycentro.map((x) => x.id);
    }
    return nuevas;
  };

  /** Cruces sólo entre capas consecutivas, que es como se dibuja la arista acá. */
  const contarCruces = (capas) => {
    const nivelDe = new Map();
    capas.forEach((capa, n) => capa.forEach((id) => nivelDe.set(id, n)));
    const posDe = capas.map(posEnCapa);

    const porCapa = new Map();
    for (const a of edgesPlanas) {
      const n1 = nivelDe.get(a.from);
      const n2 = nivelDe.get(a.to);
      if (n1 === undefined || n2 === undefined || n2 !== n1 + 1) continue;
      if (!porCapa.has(n1)) porCapa.set(n1, []);
      porCapa.get(n1).push([posDe[n1].get(a.from), posDe[n2].get(a.to)]);
    }

    let cruces = 0;
    for (const pares of porCapa.values()) {
      for (let i = 0; i < pares.length; i++) {
        for (let j = i + 1; j < pares.length; j++) {
          const [a1, b1] = pares[i];
          const [a2, b2] = pares[j];
          if ((a1 - a2) * (b1 - b2) < 0) cruces++;
        }
      }
    }
    return cruces;
  };

  let actuales = capas;
  let mejores = capas;
  let mejorCantidad = contarCruces(capas);

  for (let it = 0; it < ITERACIONES_ORDEN; it++) {
    actuales = pasada(actuales, it % 2 === 0);
    const cantidad = contarCruces(actuales);
    if (cantidad < mejorCantidad) {
      mejorCantidad = cantidad;
      mejores = actuales;
    }
  }
  return mejores;
}

const ITERACIONES_ALINEAR = 10;

/**
 * La coordenada X de cada nodo, una vez que `ordenarCapas` ya decidió el
 * orden dentro de cada fila (esto no reordena nada, sólo mueve). Bajando y
 * subiendo por turnos, cada nodo se acerca al promedio real —en píxeles, no
 * en índice de columna— de sus vecinos en la fila de al lado; después de unas
 * pasadas, una cadena de fantasmas que antes zigzagueaba (cada capa la
 * centraba por su cuenta, sin memoria de la de al lado) queda derecha. Es la
 * pieza que le falta a esto respecto de dagre/mermaid: ahí se llama
 * Brandes-Köpf, acá es la misma idea con una resolución de superposición más
 * simple.
 */
function alinearX(capas, posicion, segmentos) {
  const entrantes = new Map();
  const salientes = new Map();
  for (const { from, to } of segmentos) {
    if (!entrantes.has(to)) entrantes.set(to, []);
    entrantes.get(to).push(from);
    if (!salientes.has(from)) salientes.set(from, []);
    salientes.get(from).push(to);
  }

  // Las medidas salen de `posicion`, que ya las tiene por nodo: con uno
  // abierto no son todas iguales.
  const anchoDeId = (id) => { const p = posicion.get(id); return p ? p.ancho : NODO_ANCHO; };

  // El promedio se toma sobre el **centro** de cada vecino y se devuelve como
  // borde del nodo que se está moviendo: un fantasma mide 4 px y un nodo 116,
  // así que alinear borde con borde dejaba las cadenas largas corridas medio
  // nodo a la izquierda respecto de la caja que conectaban.
  const centroDeseado = (vecinos) => {
    if (!vecinos || !vecinos.length) return null;
    const centros = [];
    for (const v of vecinos) {
      const p = posicion.get(v);
      if (p) centros.push(p.x + p.ancho / 2);
    }
    if (!centros.length) return null;
    return centros.reduce((suma, x) => suma + x, 0) / centros.length;
  };

  for (let it = 0; it < ITERACIONES_ALINEAR; it++) {
    const bajando = it % 2 === 0;
    const filas = bajando
      ? capas.map((_, i) => i).slice(1)
      : capas.map((_, i) => i).slice(0, -1).reverse();

    for (const y of filas) {
      const fila = capas[y];
      const vecinosDe = bajando ? entrantes : salientes;
      const anchos = fila.map(anchoDeId);
      const deseada = fila.map((id, i) => {
        const centro = centroDeseado(vecinosDe.get(id));
        return centro === null ? posicion.get(id).x : centro - anchos[i] / 2;
      });
      const x = resolverFila(deseada, anchos);
      fila.forEach((id, i) => { posicion.get(id).x = x[i]; });
    }
  }
}

/**
 * Acerca cada posición a lo que pidió, sin cambiar el orden ni dejar dos
 * nodos superpuestos: primero empuja a la derecha al que quedó pegado a su
 * vecino de la izquierda, después empuja a la izquierda al que quedó pegado
 * al de la derecha (sin perder lo que ya se ganó en la primera pasada), y una
 * última vuelta a la derecha por si esa segunda pasada generó una nueva
 * superposición en cadena.
 */
function resolverFila(deseada, anchos) {
  const n = deseada.length;
  const x = deseada.slice();
  for (let i = 1; i < n; i++) x[i] = Math.max(x[i], x[i - 1] + anchos[i - 1] + SEP_X);
  for (let i = n - 2; i >= 0; i--) x[i] = Math.min(x[i], x[i + 1] - anchos[i] - SEP_X);
  for (let i = 1; i < n; i++) x[i] = Math.max(x[i], x[i - 1] + anchos[i - 1] + SEP_X);
  return x;
}

// ── El nodo ─────────────────────────────────────────────────────────────

/**
 * La caja es siempre blanca, como en n8n: el color vive en la pastilla del
 * ícono, no en el relleno. Un lienzo donde cada caja es de otro color se lee
 * como una alarma permanente; así el único color fuerte que aparece es el del
 * resultado de una corrida.
 */
const COLORES = {
  start: { acento: "var(--verde)", tile: "var(--verde-fondo)", borde: "var(--verde-borde)" },
  action: { acento: "var(--azul)", tile: "var(--azul-fondo)", borde: "var(--azul-borde)" },
  decision: { acento: "var(--ambar)", tile: "var(--ambar-fondo)", borde: "var(--ambar-borde)" },
  unknown: { acento: "var(--rojo)", tile: "var(--rojo-fondo)", borde: "var(--rojo-borde)" },
};

const COLOR_ESTADO = {
  ok: { borde: "var(--verde)", badge: "var(--verde)", glifo: "✓" },
  err: { borde: "var(--rojo)", badge: "var(--rojo)", glifo: "!" },
  skip: { borde: "var(--borde-fuerte)", badge: "var(--texto-4)", glifo: "–" },
};

const RADIO = 12;

/**
 * @returns {object|null} con `grupo` (el SVG) y los tres mutadores que la vista
 *   usa para no reconstruir el dibujo: `marcarSeleccion`, `marcarBuscado` y
 *   `aplicarEstado` — reconstruirlo tira el paneo/zoom acumulado.
 */
function nodo(id, datos, pos, { alClic, estado, paso, seleccionado, puertos, tooltip, edicion, menu, conexion, abrirDestinos, panel }) {
  if (!pos) return null;
  // Abierto: la caja crece y adentro va el editor del nodo, en un
  // `foreignObject`. Nada de tile, nombre ni tooltip — todo eso está escrito
  // con letras de verdad ahí adentro.
  const abierto = Boolean(panel);
  const tipo = datos.type || "action";
  const color = COLORES[tipo] || COLORES.action;
  const etiqueta = datos.display || datos.label || datos.variable || datos.fn || id;
  const secundaria = tipo === "action" ? (datos.fn || "sin tool")
    : tipo === "decision" ? "decisión"
    : tipo === "start" ? "inicio" : "sin definir";

  // La caja del inicio tiene el borde de arriba redondeado entero, el nodo
  // disparador de n8n girado al sentido de este flujo: se distingue de un paso
  // cualquiera de un vistazo, aun alejado donde no se leen los textos.
  const forma = tipo === "start" && !abierto
    ? s("path", {
        d: `M ${pos.x} ${pos.y + pos.ancho / 2}
            a ${pos.ancho / 2} ${pos.ancho / 2} 0 0 1 ${pos.ancho} 0
            V ${pos.y + pos.alto - RADIO} a ${RADIO} ${RADIO} 0 0 1 ${-RADIO} ${RADIO}
            H ${pos.x + RADIO} a ${RADIO} ${RADIO} 0 0 1 ${-RADIO} ${-RADIO} z`.replace(/\s+/g, " "),
      })
    : s("rect", { x: pos.x, y: pos.y, width: pos.ancho, height: pos.alto, rx: RADIO });

  const bordeBase = tipo === "unknown" ? color.borde : "var(--grafo-borde-nodo)";
  for (const [k, v] of Object.entries({
    fill: "var(--fondo)", stroke: seleccionado ? "var(--azul)" : bordeBase,
    "stroke-width": seleccionado ? 2 : 1.2,
    "stroke-dasharray": tipo === "unknown" ? "5 3" : null,
    filter: "url(#sombra-nodo)",
  })) if (v !== null) forma.setAttribute(k, String(v));

  // La pastilla del ícono: el monograma sale del prefijo del tool (`fs.leer` →
  // "FS"). Ninguna pantalla conoce un plugin por nombre — esto lee lo que el
  // manifest ya declaró, así que un plugin nuevo se dibuja solo.
  const tileX = pos.x + pos.ancho / 2 - 19;
  const tileY = pos.y + (tipo === "start" ? 22 : 14);
  const tile = s("g", {}, [
    s("rect", { x: tileX, y: tileY, width: 38, height: 38, rx: 10, fill: color.tile, stroke: color.borde }),
    glifoDeTipo(tipo, datos, tileX + 19, tileY + 19, color.acento),
  ]);

  // El estado de la corrida: anillo de color en la caja y una chapita en la
  // esquina, como el tilde verde que n8n deja sobre cada nodo ejecutado.
  const badgeCirculo = s("circle", { cx: pos.x + pos.ancho - 8, cy: pos.y + 8, r: 9, fill: "var(--fondo)", stroke: "none" });
  const badgeTexto = s("text", {
    x: pos.x + pos.ancho - 8, y: pos.y + 12, "text-anchor": "middle",
    "font-size": "11", "font-weight": "700", fill: "var(--fondo)",
  });
  const badge = s("g", { style: "display:none" }, [badgeCirculo, badgeTexto]);

  // Los dos botones del nodo, que aparecen al pasar el mouse (CSS,
  // `.lienzo__mas` y `.lienzo__borrar`): el "+" de n8n —abre el menú y el nodo
  // nuevo queda colgado de éste, o se arrastra desde ahí para conectar— y la
  // "×" para eliminarlo. El inicio no se elimina: el parser pide exactamente
  // uno, y sin él el flujo no arranca.
  const botonRedondo = (cx, cy, clase, relleno, glifo, titulo, handlers) => s("g", {
    class: clase, style: "cursor:pointer", "data-interactivo": "1", ...handlers,
  }, [
    s("circle", { cx, cy, r: 9, fill: relleno }),
    s("path", { d: glifo(cx, cy), fill: "none", stroke: "var(--fondo)", "stroke-width": 1.8, "stroke-linecap": "round" }),
    s("title", {}, [titulo]),
  ]);

  const mas = edicion ? botonRedondo(
    pos.x + pos.ancho + 14, pos.y + pos.alto - 12, "lienzo__mas", "var(--azul)",
    (x, y) => `M ${x - 4.5} ${y} h 9 M ${x} ${y - 4.5} v 9`,
    "Agregar un nodo acá · arrastrar para conectar · doble clic para elegir el destino de una lista",
    {
      onClick: (e) => {
        e.stopPropagation();
        if (conexion.recienArrastro()) return;
        menu.abrir(e.clientX, e.clientY, (tipo, fn) => edicion.alAgregar(tipo, { desde: id, fn }));
      },
      onPointerdown: (e) => conexion.iniciar(id, e),
      onDblclick: (e) => { e.stopPropagation(); menu.cerrar(); abrirDestinos(id, e); },
    },
  ) : null;

  const borrar = edicion && tipo !== "start" ? botonRedondo(
    pos.x + pos.ancho + 14, pos.y + 14, "lienzo__borrar", "var(--rojo)",
    (x, y) => `M ${x - 3.5} ${y - 3.5} l 7 7 M ${x + 3.5} ${y - 3.5} l -7 7`,
    "Eliminar el nodo",
    { onClick: (e) => { e.stopPropagation(); edicion.alQuitarNodo(id); } },
  ) : null;

  // El editor, adentro de la caja. Un clic ahí no es un clic en el nodo: sin
  // esto, tocar un campo cerraba el nodo que se estaba editando.
  const hueco = abierto ? s("foreignObject", {
    x: pos.x + 1, y: pos.y + 1, width: pos.ancho - 2, height: pos.alto - 2,
    onClick: (e) => e.stopPropagation(),
    onDblclick: (e) => e.stopPropagation(),
  }, [panel]) : null;

  const grupo = s("g", {
    class: "lienzo__nodo" + (abierto ? " lienzo__nodo--abierto" : ""),
    style: alClic ? "cursor:pointer" : "",
    onClick: alClic ? () => alClic(id) : null,
    // Con el nodo abierto no hay tooltip: lo que diría está a la vista.
    onPointerenter: abierto ? null : (e) => tooltip.mostrar(e, contenidoTooltip()),
    onPointermove: abierto ? null : (e) => tooltip.mover(e),
    onPointerleave: abierto ? null : () => tooltip.ocultar(),
    // Marca para que el paneo (`hacerPaneable`) sepa que un gesto que arranca
    // acá es un clic sobre el nodo, no el fondo del canvas, y lo deje pasar
    // sin capturar el puntero. `data-nodo-id` es lo que busca el arrastre
    // para saber sobre qué nodo se soltó el cable.
    "data-nodo": alClic ? "1" : null,
    "data-nodo-id": id,
  }, [
    forma,
    abierto ? hueco : tile,
    ...dibujarPuertos(pos, puertos, tipo, { id, conexion, abrirDestinos }),
    ...(abierto ? [] : etiquetaDelNodo(pos, etiqueta, secundaria)),
    abierto ? null : badge,
    mas,
    borrar,
  ]);

  // Lo que no entra en la caja va acá: nombre completo, id, tool, params y —si
  // hubo corrida— cómo le fue a este nodo.
  const contenidoTooltip = () => tooltipDeNodo(id, datos, etiqueta, secundaria, estadoAhora, pasoAhora);

  let seleccionadoAhora = Boolean(seleccionado);
  let estadoAhora = estado;
  let pasoAhora = paso;

  let destinoAhora = false;
  const pintar = () => {
    const e = COLOR_ESTADO[estadoAhora];
    const marcado = abierto || destinoAhora || seleccionadoAhora;
    forma.setAttribute("stroke", marcado ? "var(--azul)" : (e ? e.borde : bordeBase));
    forma.setAttribute("stroke-width", destinoAhora ? 3 : marcado ? 2 : (e ? 2 : 1.2));
    forma.setAttribute("stroke-dasharray", destinoAhora ? "6 4" : (tipo === "unknown" && !abierto ? "5 3" : ""));
    if (!e || abierto) { badge.setAttribute("style", "display:none"); }
    else {
      badge.setAttribute("style", "");
      badgeCirculo.setAttribute("fill", e.badge);
      badgeTexto.textContent = e.glifo;
    }
  };

  pintar();

  return {
    id, grupo,
    marcarSeleccion: (valor) => { seleccionadoAhora = valor; pintar(); },
    marcarBuscado: (valor, sigueSeleccionado = false) => {
      if (valor) {
        forma.setAttribute("stroke", "var(--rojo)");
        forma.setAttribute("stroke-width", 3);
      } else {
        seleccionadoAhora = sigueSeleccionado;
        pintar();
      }
    },
    aplicarEstado: (e, p) => { estadoAhora = e; pasoAhora = p; pintar(); },
    // Mientras se arrastra un cable por encima: borde azul punteado, "acá se
    // puede soltar".
    marcarDestino: (valor) => { destinoAhora = valor; pintar(); },
    // Cambiar el editor de adentro sin rearmar el dibujo (lo usa el dry run).
    reemplazarPanel: (nuevo) => { if (hueco && nuevo) hueco.replaceChildren(nuevo); },
  };
}

/**
 * Los puntitos de conexión de los bordes: entrada arriba, salidas abajo. Con
 * edición, arrastrar desde un puerto de salida saca un cable para conectar, y
 * el **doble clic** abre la lista de destinos: arrastrar hasta un nodo que
 * está diez filas más abajo obliga a tener los dos en pantalla, y en un flujo
 * de treinta nodos eso no pasa.
 */
function dibujarPuertos(pos, puertos, tipo, { id, conexion, abrirDestinos } = {}) {
  const punto = (x, y, lleno, arrastrable = false) => s("circle", {
    cx: x, cy: y, r: arrastrable ? 5 : 4,
    fill: lleno ? "var(--grafo-puerto)" : "var(--fondo)",
    stroke: "var(--grafo-puerto)", "stroke-width": 1.5,
    class: arrastrable ? "lienzo__puerto" : null,
    "data-interactivo": arrastrable ? "1" : null,
    onPointerdown: arrastrable ? (e) => conexion.iniciar(id, e) : null,
    onClick: arrastrable ? (e) => e.stopPropagation() : null,
    onDblclick: arrastrable ? (e) => { e.stopPropagation(); abrirDestinos(id, e); } : null,
  });
  const salidas = puertos.salida.map((f) => punto(pos.x + f * pos.ancho, pos.y + pos.alto, true, Boolean(conexion)));
  // El inicio no lleva puerto de entrada: no hay nada antes de él, y dibujarlo
  // sugeriría lo contrario.
  const entradas = tipo === "start" ? [] : puertos.entrada.map((f) => punto(pos.x + f * pos.ancho, pos.y, puertos.hayEntrada));
  return [...entradas, ...salidas];
}

/** El ícono de la pastilla, por tipo de nodo. Trazo, como el resto de la app. */
function glifoDeTipo(tipo, datos, cx, cy, color) {
  if (tipo === "start") {
    // El rayo del disparador.
    return s("path", {
      d: `M ${cx + 2} ${cy - 10} L ${cx - 6} ${cy + 1} H ${cx} L ${cx - 2} ${cy + 10} L ${cx + 6} ${cy - 1} H ${cx} Z`,
      fill: color, stroke: "none",
    });
  }
  if (tipo === "decision") {
    // La bifurcación: una entrada que se abre en dos, hacia abajo.
    return s("path", {
      d: `M ${cx} ${cy - 9} V ${cy - 2} M ${cx} ${cy - 2} L ${cx - 7} ${cy + 5} M ${cx} ${cy - 2} L ${cx + 7} ${cy + 5}`
         + ` M ${cx - 10} ${cy + 5} h 6 M ${cx + 4} ${cy + 5} h 6`,
      fill: "none", stroke: color, "stroke-width": 1.8, "stroke-linecap": "round",
    });
  }
  if (tipo === "unknown") {
    return s("text", { x: cx, y: cy + 6, "text-anchor": "middle", "font-size": "17", "font-weight": "700", fill: color }, ["?"]);
  }
  // Una acción: el monograma del plugin (`fs.leer_archivo` → "FS"). Es lo que
  // en n8n sería el logo de la integración, armado con lo único genérico que
  // hay acá — el prefijo del id del tool.
  const fn = String(datos.fn || "");
  const prefijo = (fn.split(".")[0] || "·").slice(0, 2).toUpperCase();
  return s("text", {
    x: cx, y: cy + 5, "text-anchor": "middle", "font-size": "14", "font-weight": "700",
    "letter-spacing": "0.5", fill: color, "font-family": "var(--fuente)",
  }, [prefijo]);
}

// Cuántos caracteres entran en la caja: 104 px útiles a ~6.2 px por letra en
// 11 px semibold, y un poco más en el mono de 9 px.
const ANCHO_ETIQUETA = 17;
const ANCHO_SECUNDARIA = 20;

/**
 * El nombre **adentro** de la caja, corto, y el tool en gris debajo. Una sola
 * línea cada uno: lo que no entra se recorta con "…" y vive en el tooltip.
 */
function etiquetaDelNodo(pos, etiqueta, secundaria) {
  const centro = pos.x + pos.ancho / 2;
  const textos = [s("text", {
    x: centro, y: pos.y + 72,
    "text-anchor": "middle", "font-size": "11", "font-weight": "600", fill: "var(--texto)",
  }, [recortar(String(etiqueta), ANCHO_ETIQUETA)])];
  if (secundaria) {
    textos.push(s("text", {
      x: centro, y: pos.y + 87,
      "text-anchor": "middle", "font-size": "9", fill: "var(--texto-4)", "font-family": "var(--mono)",
    }, [recortar(secundaria, ANCHO_SECUNDARIA)]));
  }
  return textos;
}

// ── El tooltip ──────────────────────────────────────────────────────────

/**
 * Un solo tooltip por lienzo, que se mueve de nodo en nodo. Es un `div`
 * encima del visor (no adentro del SVG): así no se escala con el zoom, se lee
 * igual a cualquier escala, y puede usar los estilos de la app.
 */
function crearTooltip() {
  const elemento = h("div", { class: "lienzo__tooltip" });
  elemento.hidden = true;
  let visible = false;

  const ubicar = (e) => {
    const marco = elemento.parentElement;
    if (!marco) return;
    const rect = marco.getBoundingClientRect();
    let x = e.clientX - rect.left + 14;
    let y = e.clientY - rect.top + 14;
    // Que no se salga del visor por la derecha ni por abajo: se da vuelta.
    if (x + elemento.offsetWidth > rect.width - 8) x = e.clientX - rect.left - elemento.offsetWidth - 10;
    if (y + elemento.offsetHeight > rect.height - 8) y = e.clientY - rect.top - elemento.offsetHeight - 10;
    elemento.style.left = `${Math.max(4, x)}px`;
    elemento.style.top = `${Math.max(4, y)}px`;
  };

  return {
    elemento,
    mostrar: (e, contenido) => {
      elemento.replaceChildren(...[].concat(contenido).filter(Boolean));
      elemento.hidden = false;
      visible = true;
      ubicar(e);
    },
    mover: (e) => { if (visible) ubicar(e); },
    ocultar: () => { elemento.hidden = true; visible = false; },
  };
}

// ── Editar desde el lienzo ──────────────────────────────────────────────

/**
 * Un panel flotante sobre el visor. El menú de alta, la lista de destinos y el
 * editor de una condición son los tres lo mismo: una cajita ubicada al lado de
 * donde se hizo clic, que se cierra con Escape o con un clic afuera. Vive en el
 * DOM y no en el SVG para no escalarse con el zoom y para poder tener inputs
 * de verdad.
 */
function crearPanelFlotante(clase) {
  const elemento = h("div", { class: `lienzo__panel ${clase}` });
  elemento.hidden = true;
  let alClicAfuera = null;
  let alTecla = null;
  let donde = null;

  const cerrar = () => {
    if (elemento.hidden) return;
    elemento.hidden = true;
    elemento.replaceChildren();
    if (alClicAfuera) { document.removeEventListener("pointerdown", alClicAfuera, true); alClicAfuera = null; }
    if (alTecla) { document.removeEventListener("keydown", alTecla, true); alTecla = null; }
  };

  // Adentro del visor: un panel alto abierto abajo se sale de la ventana, y
  // uno abierto contra el borde derecho se corta.
  const ubicar = () => {
    if (!donde || !elemento.parentElement) return;
    const marco = elemento.parentElement.getBoundingClientRect();
    let x = donde.x - marco.left + 8;
    let y = donde.y - marco.top + 8;
    if (x + elemento.offsetWidth > marco.width - 8) x = donde.x - marco.left - elemento.offsetWidth - 8;
    if (y + elemento.offsetHeight > marco.height - 8) y = marco.height - elemento.offsetHeight - 8;
    elemento.style.left = `${Math.max(4, x)}px`;
    elemento.style.top = `${Math.max(4, y)}px`;
  };

  /** Cambia el contenido sin cerrar ni mover el panel de lugar. */
  const reemplazar = (...hijos) => {
    elemento.replaceChildren(...[].concat(hijos).flat(Infinity).filter(Boolean));
    ubicar();
  };

  const abrir = (clientX, clientY, hijos) => {
    donde = { x: clientX, y: clientY };
    elemento.hidden = false;
    reemplazar(hijos);
    // En el siguiente turno, para que el mismo gesto que lo abrió no lo cierre.
    setTimeout(() => {
      alClicAfuera = (e) => { if (!elemento.contains(e.target)) cerrar(); };
      alTecla = (e) => { if (e.key === "Escape") { e.stopPropagation(); cerrar(); } };
      document.addEventListener("pointerdown", alClicAfuera, true);
      document.addEventListener("keydown", alTecla, true);
    });
  };

  return { elemento, abrir, cerrar, reemplazar };
}

/** Lo que se busca de un tool: su id, su nombre y lo que documenta. */
const textoDeTool = (t) => [t.id, t.label, t.category, t.doc].filter(Boolean).join(" ").toLowerCase();

/**
 * El menú de alta: "Acción" o "Decisión", y adentro de Acción la lista de
 * tools instalados con un buscador arriba, agrupados por plugin.
 *
 * Elegir el tool acá y no después, en la tarjeta, es lo que hace que agregar
 * un paso sea un gesto y no dos pantallas — es el panel de nodos de n8n. La
 * lista sale del manifest (`GET /tools`, que la vista pasa en `edicion.tools`):
 * este módulo no conoce ningún plugin por nombre, y uno nuevo aparece solo.
 */
function crearMenuDeAlta(tools) {
  const panel = crearPanelFlotante("lienzo__menu");
  let alElegir = null;

  const elegir = (tipo, fn) => { panel.cerrar(); if (alElegir) alElegir(tipo, fn); };

  const opcion = (rotulo, detalle, onClick, flecha = false) => h("button", {
    class: "lienzo__menu-opcion", type: "button",
    onClick: (e) => { e.stopPropagation(); onClick(); },
  }, [
    h("b", {}, [rotulo, flecha ? h("span", { class: "lienzo__menu-flecha", text: "›" }) : null]),
    h("span", { text: detalle }),
  ]);

  const raiz = () => [
    opcion("Acción",
      tools.length ? `elegir entre ${tools.length} tools instalados` : "un tool de un plugin",
      () => (tools.length ? acciones() : elegir("action")), tools.length > 0),
    opcion("Decisión", "bifurca según una variable", () => elegir("decision")),
  ];

  const acciones = () => {
    const busqueda = h("input", {
      class: "lienzo__menu-buscador", type: "text", placeholder: "Buscar una acción…",
    });
    const lista = h("div", { class: "lienzo__menu-lista" });

    const pintar = () => {
      const q = busqueda.value.trim().toLowerCase();
      const grupos = new Map();
      for (const tool of tools) {
        if (q && !textoDeTool(tool).includes(q)) continue;
        const clave = tool.category || "otros";
        if (!grupos.has(clave)) grupos.set(clave, []);
        grupos.get(clave).push(tool);
      }
      const filas = [...grupos].flatMap(([categoria, suyos]) => [
        h("div", { class: "lienzo__menu-grupo", text: categoria }),
        ...suyos.map((tool) => h("button", {
          class: "lienzo__menu-tool", type: "button", title: tool.doc || "",
          onClick: (e) => { e.stopPropagation(); elegir("action", tool.id); },
        }, [
          h("b", { text: tool.label || tool.id }),
          h("span", { class: "mono", text: tool.id }),
        ])),
      ]);
      lista.replaceChildren(...(filas.length ? filas : [
        h("div", { class: "lienzo__menu-vacio", text:
          "Ningún tool coincide. Se puede crear la acción sin tool y elegirlo después." }),
      ]));
    };

    busqueda.addEventListener("input", pintar);
    // Enter toma el primero de la lista: escribir tres letras y aceptar es el
    // camino corto cuando uno ya sabe qué tool quiere.
    busqueda.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const primero = lista.querySelector(".lienzo__menu-tool");
      if (primero) primero.click();
    });
    pintar();

    panel.reemplazar([
      h("div", { class: "lienzo__menu-cab" }, [
        h("button", { class: "lienzo__menu-volver", type: "button", title: "Volver",
                      onClick: (e) => { e.stopPropagation(); panel.reemplazar(raiz()); } }, ["‹"]),
        h("b", { text: "Acción" }),
        h("button", { class: "lienzo__menu-suelto", type: "button", text: "sin tool",
                      title: "Crear la acción ahora y elegir el tool en su tarjeta",
                      onClick: (e) => { e.stopPropagation(); elegir("action"); } }),
      ]),
      busqueda,
      lista,
    ]);
    busqueda.focus();
  };

  return {
    elemento: panel.elemento,
    cerrar: panel.cerrar,
    abrir: (clientX, clientY, cb) => { alElegir = cb; panel.abrir(clientX, clientY, raiz()); },
  };
}

/**
 * La lista de nodos a los que se puede conectar uno, con buscador. Es la
 * alternativa al arrastre: para llegar a un nodo que está diez filas más
 * abajo habría que tener los dos en pantalla a la vez, y con treinta nodos eso
 * no pasa. Se abre con doble clic en el puerto de salida o en el "+".
 */
function crearMenuDeDestinos() {
  const panel = crearPanelFlotante("lienzo__destinos");

  const abrir = (clientX, clientY, desde, candidatos, alElegir) => {
    const busqueda = h("input", {
      class: "lienzo__menu-buscador", type: "text", placeholder: "Buscar el nodo destino…",
    });
    const lista = h("div", { class: "lienzo__menu-lista" });

    const pintar = () => {
      const q = busqueda.value.trim().toLowerCase();
      const visibles = candidatos.filter((c) => !q
        || `${c.id} ${c.etiqueta} ${c.secundaria}`.toLowerCase().includes(q));
      lista.replaceChildren(...(visibles.length ? visibles.map((c) => h("button", {
        class: "lienzo__menu-tool", type: "button",
        onClick: (e) => { e.stopPropagation(); panel.cerrar(); alElegir(c.id); },
      }, [
        h("b", { text: c.etiqueta }),
        h("span", { class: "mono", text: `${c.id} · ${c.secundaria}` }),
      ])) : [h("div", { class: "lienzo__menu-vacio", text: "Ningún nodo coincide." })]));
    };

    busqueda.addEventListener("input", pintar);
    busqueda.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const primero = lista.querySelector(".lienzo__menu-tool");
      if (primero) primero.click();
    });
    pintar();

    panel.abrir(clientX, clientY, [
      h("div", { class: "lienzo__menu-cab" }, [h("b", { text: `Conectar ${desde} con…` })]),
      candidatos.length ? busqueda : null,
      lista,
      h("div", { class: "lienzo__menu-pie", text:
        "Los que ya están conectados desde este nodo no aparecen." }),
    ]);
    busqueda.focus();
  };

  return { elemento: panel.elemento, abrir, cerrar: panel.cerrar };
}

/**
 * La condición de una arista, editable en el lugar. Abrir la tarjeta entera
 * del nodo para escribir "ok" es desproporcionado, y además obliga a
 * encontrar cuál de sus aristas es la que se está mirando en el dibujo.
 */
function crearEditorDeCondicion() {
  const panel = crearPanelFlotante("lienzo__cond");

  const abrir = (clientX, clientY, arista, alGuardar) => {
    const entrada = h("input", {
      class: "lienzo__cond-entrada mono", type: "text",
      value: arista.condition || "", placeholder: "sin condición",
    });
    const guardar = () => { const v = entrada.value.trim(); panel.cerrar(); alGuardar(v); };

    entrada.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      guardar();
    });

    panel.abrir(clientX, clientY, [
      h("div", { class: "lienzo__menu-cab" }, [h("b", { text: `${arista.from} → ${arista.to}` })]),
      entrada,
      h("div", { class: "lienzo__menu-pie" }, [
        "Desde una acción: ",
        h("span", { class: "mono", text: "ok" }), ", ",
        h("span", { class: "mono", text: "err" }), " o ",
        h("span", { class: "mono", text: "loop" }),
        ". Desde una decisión, el valor que tiene que tener la variable; una coma arma una lista. Vacío = siempre.",
      ]),
      h("div", { class: "lienzo__cond-acciones" }, [
        h("button", { class: "btn btn--chico", type: "button", text: "Cancelar",
                      onClick: (e) => { e.stopPropagation(); panel.cerrar(); } }),
        h("button", { class: "btn btn--chico btn--primario", type: "button", text: "Guardar",
                      onClick: (e) => { e.stopPropagation(); guardar(); } }),
      ]),
    ]);
    entrada.focus();
    entrada.select();
  };

  return { elemento: panel.elemento, abrir, cerrar: panel.cerrar };
}

const UMBRAL_ARRASTRE = 6;

/**
 * Conectar arrastrando: desde un puerto de salida o el "+" de un nodo sale un
 * cable que sigue al mouse; soltarlo sobre otro nodo crea la arista, soltarlo
 * en el vacío abre el menú para crear un nodo nuevo ya conectado — las dos
 * cosas que hace n8n. El cable provisorio vive adentro del SVG (en
 * coordenadas del dibujo, vía `aPuntoDeContenido`) para que acompañe el zoom.
 *
 * El puntero se captura en el elemento donde arrancó, así que `pointermove` y
 * `pointerup` llegan ahí aunque el mouse esté sobre otro nodo; a ese otro nodo
 * se lo encuentra con `elementFromPoint` y el `data-nodo-id` del grupo.
 */
function crearConexion(edicion, menu, tooltip) {
  let svg = null;
  let lienzo = null;
  let envoltura = null;
  let porId = new Map();
  let ultimoArrastre = 0;

  const montar = (elSvg, elLienzo, elEnvoltura, mapa) => {
    svg = elSvg; lienzo = elLienzo; envoltura = elEnvoltura; porId = mapa;
  };

  const iniciar = (desde, e) => {
    if (e.button !== 0 || !svg) return;
    e.stopPropagation();
    e.preventDefault();
    tooltip.ocultar();
    const origen = e.currentTarget;
    origen.setPointerCapture(e.pointerId);
    envoltura.classList.add("lienzo--conectando");

    const inicio = lienzo.aPuntoDeContenido(e.clientX, e.clientY);
    const cable = s("path", {
      class: "lienzo__cable", fill: "none", stroke: "var(--azul)", "stroke-width": 2,
      "stroke-dasharray": "6 4", "marker-end": "url(#punta)", style: "pointer-events:none",
    });
    svg.appendChild(cable);

    let destino = null;
    let movido = false;

    const alMover = (ev) => {
      const p = lienzo.aPuntoDeContenido(ev.clientX, ev.clientY);
      if (Math.abs(ev.clientX - e.clientX) > UMBRAL_ARRASTRE || Math.abs(ev.clientY - e.clientY) > UMBRAL_ARRASTRE) movido = true;
      const medio = (inicio.y + p.y) / 2;
      cable.setAttribute("d", `M ${inicio.x} ${inicio.y} C ${inicio.x} ${medio}, ${p.x} ${medio}, ${p.x} ${p.y}`);
      const bajo = document.elementFromPoint(ev.clientX, ev.clientY);
      const grupo = bajo && bajo.closest ? bajo.closest("[data-nodo-id]") : null;
      const id = grupo && grupo.dataset.nodoId !== desde ? grupo.dataset.nodoId : null;
      if (id !== destino) {
        if (destino && porId.has(destino)) porId.get(destino).marcarDestino(false);
        destino = id;
        if (destino && porId.has(destino)) porId.get(destino).marcarDestino(true);
      }
    };

    const terminar = (ev) => {
      origen.removeEventListener("pointermove", alMover);
      origen.removeEventListener("pointerup", terminar);
      origen.removeEventListener("pointercancel", terminar);
      cable.remove();
      envoltura.classList.remove("lienzo--conectando");
      if (destino && porId.has(destino)) porId.get(destino).marcarDestino(false);
      if (!movido) return;
      ultimoArrastre = Date.now();
      if (destino) edicion.alConectar(desde, destino);
      else if (ev.type === "pointerup") {
        menu.abrir(ev.clientX, ev.clientY, (tipo, fn) => edicion.alAgregar(tipo, { desde, fn }));
      }
    };

    origen.addEventListener("pointermove", alMover);
    origen.addEventListener("pointerup", terminar);
    origen.addEventListener("pointercancel", terminar);
  };

  // El `click` que sigue a un arrastre llega igual al "+" que lo arrancó: se
  // distingue por tiempo para no abrir el menú encima de la arista recién
  // creada.
  const recienArrastro = () => Date.now() - ultimoArrastre < 300;

  return { montar, iniciar, recienArrastro };
}

const MAX_PARAMS_TOOLTIP = 8;

/** El cuerpo del tooltip de un nodo. */
function tooltipDeNodo(id, datos, etiqueta, secundaria, estado, paso) {
  const params = Object.entries(datos.params || {});
  const filas = params.slice(0, MAX_PARAMS_TOOLTIP);
  const resueltos = paso && paso.params ? paso.params : null;
  const estadoRotulo = estado === "err" ? "falló en seco" : estado === "ok" ? "ok en seco" : estado === "skip" ? "salteado" : null;
  return [
    h("div", { class: "lienzo__tooltip-titulo" }, [
      h("span", { text: String(etiqueta) }),
      estadoRotulo ? h("span", { class: `lienzo__tooltip-estado lienzo__tooltip-estado--${estado}`, text: estadoRotulo }) : null,
    ]),
    h("div", { class: "lienzo__tooltip-sub mono", text: `${id} · ${secundaria}` }),
    filas.length
      ? h("div", { class: "lienzo__tooltip-params mono" }, filas.flatMap(([k, v]) => [
          h("span", { class: "lienzo__tooltip-k", text: k }),
          h("span", { text: recortar(String(resueltos && k in resueltos ? resueltos[k] : v), 60) }),
        ]))
      : null,
    params.length > MAX_PARAMS_TOOLTIP
      ? h("div", { class: "lienzo__tooltip-sub", text: `… y ${params.length - MAX_PARAMS_TOOLTIP} más` })
      : null,
    resueltos && filas.length
      ? h("div", { class: "lienzo__tooltip-sub", text: "Valores ya resueltos por el dry run." })
      : null,
    paso && paso.message
      ? h("div", { class: `lienzo__tooltip-msg${estado === "err" ? " lienzo__tooltip-msg--err" : ""}`, text: paso.message })
      : null,
  ];
}


// ── Las aristas ─────────────────────────────────────────────────────────

const COLOR_ARISTA = {
  err: { trazo: "var(--rojo-borde)", punta: "url(#punta-err)" },
  ok: { trazo: "var(--verde-borde)", punta: "url(#punta-cond-ok)" },
};
const ARISTA_NEUTRA = { trazo: "var(--grafo-linea)", punta: "url(#punta)" };

/**
 * Sólo para las que cierran un ciclo (`romperCiclos`): van hacia arriba, y
 * quedan aparte del ruteo por capas — no tiene sentido meterles nodos fantasma
 * para "ir para adelante" cuando el punto es justo lo contrario. Se dibujan
 * del origen al destino real rodeando por el costado derecho: una curva que
 * cruzara el medio del dibujo se confundiría con el camino normal, y la
 * vuelta es lo contrario del camino normal. Punteada sólo si el flujo la
 * rotuló `loop`; una vuelta sin rótulo se dibuja llena, como cualquier otra.
 */
function aristaSuelta(a, posicion, extras = {}) {
  const desde = posicion.get(a.from);
  const hasta = posicion.get(a.to);
  if (!desde || !hasta) return null;

  const x1 = desde.x + desde.ancho;
  const x2 = hasta.x + hasta.ancho;
  const y1 = desde.y + desde.alto / 2;
  const y2 = hasta.y + hasta.alto / 2;
  const afuera = Math.max(x1, x2) + 70;
  const d = `M ${x1} ${y1} C ${afuera} ${y1}, ${afuera} ${y2}, ${x2} ${y2}`;

  const color = COLOR_ARISTA[a.condition] || ARISTA_NEUTRA;
  const linea = s("path", {
    d, fill: "none", stroke: color.trazo, "stroke-width": "1.6",
    "marker-end": color.punta, "stroke-dasharray": a.condition === "loop" ? "5 4" : null,
  });

  const elementos = [linea, ...rotulo(a.condition, afuera - 16, (y1 + y2) / 2, color.trazo)];
  // A mitad de la curva (t = 0,5 de la cúbica), un poco más abajo del rótulo.
  const medio = { x: (x1 + x2) / 8 + 0.75 * afuera, y: (y1 + y2) / 2 + 22 };
  return armarArista(a, elementos, linea, medio, extras);
}

/**
 * Una arista "de verdad" (no `loop`): recorre su cadena de nodos —reales y
 * fantasma— con una curva por tramo, igual que las de n8n pero en vertical:
 * sale por abajo, entra por arriba, y los puntos de control están a media
 * altura, así el arranque y la llegada son verticales. El punto de enganche en
 * cada extremo real sale de `anclas`, no siempre el centro.
 */
function trazoDeArista(a, cadena, posicion, anclas, extras = {}) {
  if (!cadena) return null;

  const puntos = cadena.map((id, i) => {
    const pos = posicion.get(id);
    if (!pos) return null;
    if (esDummy(id)) return { x: pos.x + ANCHO_DUMMY / 2, y: pos.y + pos.alto / 2 };
    if (i === 0) {
      const frac = anclas.anchoSalida.get(a) ?? 0.5;
      return { x: pos.x + frac * pos.ancho, y: pos.y + pos.alto };
    }
    const frac = anclas.anchoEntrada.get(a) ?? 0.5;
    return { x: pos.x + frac * pos.ancho, y: pos.y };
  });
  if (puntos.some((p) => !p)) return null;

  let d = `M ${puntos[0].x} ${puntos[0].y}`;
  for (let i = 0; i < puntos.length - 1; i++) {
    const p1 = puntos[i], p2 = puntos[i + 1];
    const medio = (p1.y + p2.y) / 2;
    d += ` C ${p1.x} ${medio}, ${p2.x} ${medio}, ${p2.x} ${p2.y}`;
  }

  const color = COLOR_ARISTA[a.condition] || ARISTA_NEUTRA;
  // Una `loop` que va hacia adelante (el reingreso al gate, que ahora cae
  // debajo de quien reintenta) se dibuja como cualquier tramo, punteada.
  const linea = s("path", {
    d, fill: "none", stroke: color.trazo, "stroke-width": "1.6", "marker-end": color.punta,
    "stroke-dasharray": a.condition === "loop" ? "5 4" : null,
  });

  // El rótulo va pegado al puerto de salida, no al medio del camino: un salto
  // largo tiene varios nodos fantasma en el medio, y un rótulo ahí flotaría
  // lejos de los dos nodos reales que en verdad conecta. Es también donde lo
  // pone n8n para las salidas de un IF. Va **sobre** el cable, que ahí todavía
  // es vertical: entre filas no hay otra cosa que pisar, y correrlo al costado
  // lo hacía chocar con el rótulo de la salida de al lado.
  const elementos = [linea, ...rotulo(a.condition, puntos[0].x, puntos[0].y + 24, color.trazo)];
  // El punto medio del tramo del medio: con los puntos de control a media
  // altura, la cúbica pasa a t = 0,5 justo por el promedio de sus extremos.
  // Corrido hacia abajo para no pisar el rótulo de la condición.
  const m = Math.floor((puntos.length - 1) / 2);
  const medio = { x: (puntos[m].x + puntos[m + 1].x) / 2, y: (puntos[m].y + puntos[m + 1].y) / 2 + 14 };
  return armarArista(a, elementos, linea, medio, extras);
}

/** La pastillita con la condición ("ok", "err", lo que diga el flujo). */
function rotulo(condicion, x, y, color) {
  if (!condicion) return [];
  const texto = recortar(condicion, 22);
  const ancho = texto.length * 5.6 + 12;
  return [
    s("rect", { x: x - ancho / 2, y: y - 8, width: ancho, height: 16, rx: 8, fill: "var(--fondo)", stroke: color }),
    s("text", {
      x, y: y + 3.5, "text-anchor": "middle", "font-size": "9.5",
      fill: color, "font-family": "var(--mono)",
    }, [texto]),
  ];
}

/**
 * Lo común a las dos clases de arista: la clave con la que el dry run la
 * encuentra, cómo se resalta cuando el recorrido pasó por ella y —con
 * edición— las tres herramientas que aparecen al pasar el mouse, como en n8n:
 * "+" para meter un nodo en el medio, el lápiz para la condición y "×" para
 * quitarla. El área sensible es un trazo invisible y ancho por encima de la
 * línea: una línea de 1,6 px no se puede apuntar.
 *
 * Un clic la deja **seleccionada** y las herramientas quedan fijas: llegar
 * hasta ellas con el mouse sale del área de la línea, y hasta que hubo
 * selección desaparecían justo antes de poder apretarlas.
 */
function armarArista(a, elementos, linea, medio, { edicion, menu, editorCond, alSeleccionar } = {}) {
  const ancho = linea.getAttribute("stroke-width");
  const color = linea.getAttribute("stroke");
  const punta = linea.getAttribute("marker-end");
  let envoltorio = null;

  if (edicion && medio) {
    const zona = s("path", {
      d: linea.getAttribute("d"), fill: "none", stroke: "transparent", "stroke-width": 16,
      style: "pointer-events:stroke",
    });
    const boton = (dx, relleno, glifo, titulo, onClick) => s("g", { style: "cursor:pointer", onClick: (e) => { e.stopPropagation(); onClick(e); } }, [
      s("circle", { cx: medio.x + dx, cy: medio.y, r: 9, fill: relleno }),
      s("path", { d: glifo(medio.x + dx, medio.y), fill: "none", stroke: "var(--fondo)", "stroke-width": 1.8, "stroke-linecap": "round" }),
      s("title", {}, [titulo]),
    ]);
    const herramientas = s("g", { class: "lienzo__arista-tools", "data-interactivo": "1" }, [
      boton(-22, "var(--azul)", (x, y) => `M ${x - 4.5} ${y} h 9 M ${x} ${y - 4.5} v 9`, "Agregar un nodo en el medio",
        (e) => menu.abrir(e.clientX, e.clientY, (tipo, fn) => edicion.alAgregar(tipo, { arista: a, fn }))),
      boton(0, "var(--texto-3)", (x, y) => `M ${x - 4.5} ${y + 4.5} l 1 -3 l 4 -4 l 2 2 l -4 4 z`, "Editar la condición",
        (e) => editorCond.abrir(e.clientX, e.clientY, a, (valor) => edicion.alCambiarCondicion(a, valor))),
      boton(22, "var(--texto-4)", (x, y) => `M ${x - 3.5} ${y - 3.5} l 7 7 M ${x + 3.5} ${y - 3.5} l -7 7`, "Quitar la arista",
        () => edicion.alQuitarArista(a)),
    ]);
    // `data-interactivo` en el grupo entero, no sólo en la zona sensible:
    // encima de la curva el hit-test devuelve el trazo **visible**, que pinta
    // por arriba de la zona, y sin la marca en un ancestro el paneo capturaba
    // el puntero y se quedaba con el clic (`setPointerCapture` retarget
    // también el `click`) — la arista no se podía seleccionar nunca.
    envoltorio = s("g", { class: "lienzo__arista", "data-interactivo": "1" }, [zona, ...elementos, herramientas]);
    elementos = [envoltorio];
  }

  const api = {
    clave: `${a.from}→${a.to}`,
    elementos,
    marcarRecorrida: (valor) => {
      linea.setAttribute("stroke", valor ? "var(--verde)" : color);
      linea.setAttribute("stroke-width", valor ? 2.4 : ancho);
      linea.setAttribute("marker-end", valor ? "url(#punta-ok)" : punta);
    },
    marcarSeleccionada: (valor) => {
      if (envoltorio) envoltorio.classList.toggle("lienzo__arista--sel", Boolean(valor));
    },
  };

  // El listener se cuelga acá abajo porque necesita `api`, que es lo que la
  // vista guarda como "la arista seleccionada".
  if (envoltorio && alSeleccionar) {
    envoltorio.addEventListener("click", (e) => {
      // Un clic en una de las herramientas no es "seleccionar la arista": ya
      // hizo lo suyo. Se mira la clase y no `data-interactivo`, que acá lo
      // lleva también la zona sensible (para que el paneo la deje pasar).
      if (e.target.closest(".lienzo__arista-tools")) return;
      e.stopPropagation();
      alSeleccionar(api);
    });
  }

  return api;
}

function recortar(texto, largo) {
  const t = String(texto || "");
  return t.length > largo ? t.slice(0, largo - 1) + "…" : t;
}

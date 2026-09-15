/**
 * El render del flujo, en SVG dibujado a mano.
 *
 * Sin Mermaid. La librería pesa unos 3 MB y habría que embarcarla en el repo
 * para que la app funcione sin internet — que es un requisito, corre en una
 * máquina de producción. Y no hace falta: el backend ya devuelve el grafo que el
 * motor entiende (`GET /workflows/{n}/graph`), así que dibujarlo es acomodar
 * cajas y líneas. A cambio se gana lo que Mermaid no da: los colores del
 * sistema de diseño, el estado de cada nodo tras un dry run, y clic para abrir
 * la tarjeta.
 *
 * El layout es por capas (Sugiyama, la misma familia que dagre/Mermaid): el
 * camino más largo desde el inicio decide la fila, y adentro de cada fila el
 * orden sale de un barycenter contra la fila de al lado — ver `porCapas`.
 */

import { h } from "../dom.js";

const NS = "http://www.w3.org/2000/svg";

const ANCHO_NODO = 190;
const ALTO_NODO = 40;
const SEP_X = 34;
const SEP_Y = 62;
const MARGEN = 18;

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
 * @param {object} opts    {alClic: fn(nodeId), estados: {nodeId: "ok"|"err"|"skip"}, seleccionado}
 */
export function dibujarGrafo(grafo, { alClic, estados = {}, seleccionado = null } = {}) {
  const nodos = grafo.nodes || {};
  const aristas = grafo.edges || [];
  const ids = Object.keys(nodos);

  if (!ids.length) {
    const vacio = h("div", { class: "tabla__vacia", text: "El flujo todavía no tiene ningún nodo." });
    vacio.actualizarSeleccion = () => {};
    return vacio;
  }

  const { capas, cadenaPorArista, segmentosOrden } = porCapas(grafo);
  const posicion = new Map();
  // Los nodos fantasma de ruteo (ver `expandirConDummies`) ocupan una franja
  // angosta, no un cajón entero: si pesaran como un nodo real, una arista que
  // salta muchas capas ensancharía el diagrama entero sin necesidad.
  capas.forEach((fila, y) => {
    let xAcum = 0;
    fila.forEach((id) => {
      posicion.set(id, { x: MARGEN + xAcum, y: MARGEN + y * (ALTO_NODO + SEP_Y) });
      xAcum += anchoDe(id) + SEP_X;
    });
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
  for (const [id, pos] of posicion) {
    minX = Math.min(minX, pos.x);
    maxX = Math.max(maxX, pos.x + anchoDe(id));
  }
  const corrimiento = MARGEN - minX;
  for (const pos of posicion.values()) pos.x += corrimiento;
  const anchoMax = maxX - minX;

  const ancho = anchoMax + MARGEN * 2;
  const alto = capas.length * (ALTO_NODO + SEP_Y) - SEP_Y + MARGEN * 2;

  // Sin `max-width:100%`: un grafo de 30 nodos encogido a la fuerza en una
  // columna deja los textos ilegibles. El tamaño real es el punto de partida
  // — de ahí para abajo (o para arriba) lo decide la barra de zoom, no el CSS.
  const nodosInfo = ids.map((id) => nodo(id, nodos[id], posicion.get(id), {
    alClic, estado: estados[id], seleccionado: seleccionado === id,
  })).filter(Boolean);

  // Dónde se engancha cada arista en el borde de un nodo real: no siempre el
  // centro. Con varias flechas saliendo o llegando al mismo nodo, todas por
  // el centro es justo el amontonamiento de la captura — acá se reparten a lo
  // ancho según dónde está el próximo punto de la ruta, en el mismo orden que
  // van a quedar dibujadas.
  const anclas = calcularAnclas(cadenaPorArista, posicion);

  const svg = s("svg", {
    width: ancho, height: alto, viewBox: `0 0 ${ancho} ${alto}`,
    style: "display:block",
  }, [
    s("defs", {}, [
      s("marker", {
        id: "punta", viewBox: "0 0 8 8", refX: "7", refY: "4",
        markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
      }, [s("path", { d: "M0,0 L8,4 L0,8 z", fill: "var(--borde-3)" })]),
    ]),
    ...aristas.map((a) => a.condition === "loop"
      ? aristaSuelta(a, posicion)
      : trazoDeArista(a, cadenaPorArista.get(a), posicion, anclas)).flat(),
    ...nodosInfo.map((n) => n.grupo),
  ]);

  const { envoltura, lienzo } = envolverEnLienzo(svg, ancho, alto);

  // Resaltar o soltar un nodo muta el `stroke` de su rect en el propio SVG,
  // no reconstruye nada: reconstruir tiraría el `transform` de paneo/zoom que
  // ya se acumuló. Quien llama (la pantalla de Workflows) usa esto para abrir
  // la tarjeta flotante de un nodo sin resetear la vista del diagrama.
  const rectPorId = new Map(nodosInfo.map((n) => [n.id, { rect: n.rect, colorBorde: n.colorBorde }]));
  let actual = seleccionado;
  envoltura.actualizarSeleccion = (nuevoId) => {
    if (actual && rectPorId.has(actual)) {
      const { rect, colorBorde } = rectPorId.get(actual);
      rect.setAttribute("stroke", colorBorde);
      rect.setAttribute("stroke-width", "1");
    }
    if (nuevoId && rectPorId.has(nuevoId)) {
      const { rect } = rectPorId.get(nuevoId);
      rect.setAttribute("stroke", "var(--azul)");
      rect.setAttribute("stroke-width", "2");
    }
    actual = nuevoId;
  };

  // El buscador de la cabecera: centra el nodo encontrado con zoom y lo
  // resalta un momento en un color que no se confunda con la selección
  // (azul) — el aviso tiene que notarse aunque el nodo ya esté seleccionado.
  let temporizadorResaltado = null;
  envoltura.enfocarNodo = (id) => {
    const pos = posicion.get(id);
    if (!pos) return;
    lienzo.centrarEn(pos.x + ANCHO_NODO / 2, pos.y + ALTO_NODO / 2, Math.max(1, lienzo.obtenerEscala()));

    if (temporizadorResaltado) clearTimeout(temporizadorResaltado);
    if (!rectPorId.has(id)) return;
    const { rect, colorBorde } = rectPorId.get(id);
    rect.setAttribute("stroke", "var(--rojo)");
    rect.setAttribute("stroke-width", "3");
    temporizadorResaltado = setTimeout(() => {
      const seleccionadoAhora = actual === id;
      rect.setAttribute("stroke", seleccionadoAhora ? "var(--azul)" : colorBorde);
      rect.setAttribute("stroke-width", seleccionadoAhora ? "2" : "1");
    }, 1200);
  };

  return envoltura;
}

const ZOOM_MIN = 0.05;
const ZOOM_MAX = 3;
const ZOOM_PASO = 1.25;

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
  const contenedor = h("div", {
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
  const aplicar = () => { svg.style.transform = `translate(${panX}px, ${panY}px) scale(${escala})`; };
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

  const boton = (texto, titulo, onClick) => h("button", {
    class: "btn btn--chico", text: texto, title: titulo,
    style: { width: "22px", height: "20px", padding: "0", lineHeight: "1" },
    onClick,
  });

  const elemento = h("div", {
    style: {
      position: "absolute", top: "6px", right: "6px", display: "flex", gap: "3px",
      background: "var(--fondo)", border: "1px solid var(--borde)", borderRadius: "3px", padding: "2px",
    },
  }, [
    boton("+", "Acercar", () => acercar()),
    boton("−", "Alejar", () => alejar()),
    boton("⊙", "Ajustar el diagrama entero a la ventana", () => ajustar()),
  ]);

  /** El diagrama entero a la vista. */
  const ajustar = () => {
    // Sólo achica: agrandar un diagrama chico a que llene la ventana lo deja
    // borroso sin ganar nada, cuando ya se lee bien a tamaño real.
    const disponibleX = contenedor.clientWidth - 8;
    const disponibleY = contenedor.clientHeight - 8;
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

  return { elemento, alRueda, mover, centrarEn, ajustar, obtenerEscala: () => escala };
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
    if (e.target.closest("[data-nodo]")) return;
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

/**
 * Las filas del dibujo: capas por camino **más largo**, y adentro de cada
 * capa el orden que menos cruces deja — lo mismo que hace Mermaid/dagre, sin
 * traerlos.
 *
 * Las aristas `loop` (`flow.retry_gate` volviendo atrás) no cuentan para
 * ninguna de las dos cosas: son intencionalmente hacia atrás, y si entraran
 * en la cuenta el nivel subiría sin límite en cada vuelta del ciclo —
 * un flujo legacy de 30 nodos salía de 92.896 px de alto con eso. Sacándolas, lo que
 * queda es un DAG de verdad.
 */
const ANCHO_DUMMY = 2;
const esDummy = (id) => typeof id === "string" && id.startsWith("__ruta_");
const anchoDe = (id) => (esDummy(id) ? ANCHO_DUMMY : ANCHO_NODO);

function porCapas(grafo) {
  const capasBase = capasPorCaminoMasLargo(grafo);
  const { capas, cadenaPorArista, segmentosOrden } = expandirConDummies(capasBase, grafo);
  return { capas: ordenarCapas(capas, segmentosOrden), cadenaPorArista, segmentosOrden };
}

/**
 * Una arista que salta varias capas (por ejemplo, una decisión temprana que
 * alimenta un nodo mucho más abajo) se parte en tramos de una capa cada uno,
 * metiendo un nodo fantasma en cada capa intermedia — la misma técnica que
 * usa dagre. Sin esto, esa arista se dibuja en diagonal por encima de todo lo
 * que hay en el medio (la captura que mandó el usuario), porque ni el
 * barycenter ni el conteo de cruces la tienen en cuenta fila por fila: para
 * esos algoritmos era una sola arista "de la capa 2 a la 9", no nueve
 * decisiones de orden.
 */
function expandirConDummies(capas, grafo) {
  const nivelDe = new Map();
  capas.forEach((fila, n) => fila.forEach((id) => nivelDe.set(id, n)));

  const adelante = (grafo.edges || []).filter((a) => a.condition !== "loop");
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

  // 0.2–0.8 del ancho del nodo, nunca hasta el borde mismo: pegada a la
  // esquina, una flecha se lee peor que una que sale un poco adentro.
  const repartir = (mapaDeListas) => {
    const resultado = new Map();
    for (const lista of mapaDeListas.values()) {
      lista.sort((p, q) => p.x - q.x);
      const n = lista.length;
      lista.forEach((item, i) => resultado.set(item.edge, n === 1 ? 0.5 : 0.2 + (0.6 * i) / (n - 1)));
    }
    return resultado;
  };

  return { anchoSalida: repartir(salientes), anchoEntrada: repartir(entrantes) };
}

/**
 * Camino más largo y no más corto: un nodo se ubica recién cuando ya se
 * calcularon **todos** los que le llegan, no sólo el más cercano. Con el más
 * corto, un nodo al que convergen una rama de un paso y otra de cinco
 * quedaba en la capa 1, y la arista de la rama larga cruzaba por encima de
 * todo el resto del dibujo para alcanzarlo — exactamente la zona confusa que
 * esto arregla.
 */
function capasPorCaminoMasLargo(grafo) {
  const ids = Object.keys(grafo.nodes || {});
  const edges = grafo.edges || [];
  const adelante = edges.filter((a) => a.condition !== "loop");
  const deVuelta = edges.filter((a) => a.condition === "loop");

  const salientes = new Map(ids.map((id) => [id, []]));
  const gradoEntrada = new Map(ids.map((id) => [id, 0]));
  for (const a of adelante) {
    if (!salientes.has(a.from) || !gradoEntrada.has(a.to)) continue;
    salientes.get(a.from).push(a.to);
    gradoEntrada.set(a.to, gradoEntrada.get(a.to) + 1);
  }

  // El destino de un `loop` (el reingreso de un `flow.retry_gate`) puede no
  // tener ninguna otra arista hacia adelante que le entre — su único camino
  // "de verdad" es ESE loop. Sin esto se lo confunde con una raíz real y
  // termina en la primera capa, junto al inicio, en vez de al lado de donde
  // se dispara el reintento.
  const origenesLoopDe = new Map();
  for (const a of deVuelta) {
    if (!gradoEntrada.has(a.to)) continue;
    if (!origenesLoopDe.has(a.to)) origenesLoopDe.set(a.to, []);
    origenesLoopDe.get(a.to).push(a.from);
  }
  const entranSoloPorLoop = new Set(
    [...origenesLoopDe.keys()].filter((id) => gradoEntrada.get(id) === 0),
  );

  // Kahn: un nodo se procesa recién cuando ya se restó una vez por cada
  // arista que le entra, así que para entonces todos sus orígenes ya le
  // dieron su nivel y el máximo que quede es el camino más largo real.
  const nivel = new Map();
  const restante = new Map(gradoEntrada);
  let cola = ids.filter((id) => restante.get(id) === 0 && !entranSoloPorLoop.has(id));
  cola.forEach((id) => nivel.set(id, 0));

  const drenarCola = () => {
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
  };
  drenarCola();

  // Los que quedaron afuera a propósito se liberan apenas alguno de sus
  // orígenes de loop ya tiene nivel — recién ahí se sabe "un paso después de
  // dónde reintenta" — y desde ese punto se sigue drenando la cola normal:
  // el resto de su propio tramo del ciclo hereda un nivel real, no cero.
  let pendientes = new Set(entranSoloPorLoop);
  let avanzo = true;
  while (pendientes.size && avanzo) {
    avanzo = false;
    for (const id of pendientes) {
      const nivelesOrigen = (origenesLoopDe.get(id) || [])
        .map((o) => nivel.get(o)).filter((n) => n !== undefined);
      if (!nivelesOrigen.length) continue;
      nivel.set(id, Math.max(...nivelesOrigen) + 1);
      pendientes.delete(id);
      avanzo = true;
      cola = [id];
      drenarCola();
    }
  }

  // Lo que no se resolvió es una isla que sólo conecta por `loop` sin que su
  // origen tenga nivel tampoco (un ciclo fuera de este caso), o un nodo
  // realmente desconectado — raro, pero existe y hay que poder verlo: va al
  // final.
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

  const promedioX = (vecinos) => {
    if (!vecinos || !vecinos.length) return null;
    const xs = vecinos.map((v) => posicion.get(v)).filter(Boolean).map((p) => p.x);
    if (!xs.length) return null;
    return xs.reduce((suma, x) => suma + x, 0) / xs.length;
  };

  for (let it = 0; it < ITERACIONES_ALINEAR; it++) {
    const bajando = it % 2 === 0;
    const filas = bajando
      ? capas.map((_, i) => i).slice(1)
      : capas.map((_, i) => i).slice(0, -1).reverse();

    for (const y of filas) {
      const fila = capas[y];
      const vecinosDe = bajando ? entrantes : salientes;
      const deseada = fila.map((id) => promedioX(vecinosDe.get(id)) ?? posicion.get(id).x);
      const anchos = fila.map(anchoDe);
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

const COLORES = {
  start: { relleno: "var(--verde-fondo)", borde: "var(--verde-borde)", texto: "var(--verde)" },
  action: { relleno: "var(--fondo)", borde: "var(--borde-3)", texto: "var(--texto)" },
  decision: { relleno: "var(--ambar-fondo)", borde: "var(--ambar-borde)", texto: "var(--ambar)" },
  unknown: { relleno: "var(--rojo-fondo)", borde: "var(--rojo-borde)", texto: "var(--rojo)" },
};

const COLOR_ESTADO = {
  ok: { relleno: "var(--verde-fondo)", borde: "var(--verde)" },
  err: { relleno: "var(--rojo-fondo)", borde: "var(--rojo)" },
  skip: { relleno: "var(--fondo-zebra)", borde: "var(--borde)" },
};

/**
 * @returns {{id, grupo, rect, colorBorde}|null} `rect` y `colorBorde` quedan
 *   sueltos para que `actualizarSeleccion` pueda resaltar o soltar un nodo
 *   después, mutando el atributo del SVG en vez de reconstruir todo el
 *   dibujo — reconstruirlo tira el `transform` de paneo/zoom acumulado.
 */
function nodo(id, datos, pos, { alClic, estado, seleccionado }) {
  if (!pos) return null;
  const tipo = datos.type || "action";
  const color = { ...(COLORES[tipo] || COLORES.action), ...(COLOR_ESTADO[estado] || {}) };
  const etiqueta = datos.display || datos.label || datos.variable || datos.fn || id;
  const secundaria = tipo === "action" ? (datos.fn || "") : tipo === "decision" ? "decisión" : "";

  const rect = s("rect", {
    x: pos.x, y: pos.y, width: ANCHO_NODO, height: ALTO_NODO,
    rx: tipo === "start" ? ALTO_NODO / 2 : tipo === "decision" ? 6 : 3,
    fill: color.relleno,
    stroke: seleccionado ? "var(--azul)" : color.borde,
    "stroke-width": seleccionado ? 2 : 1,
  });

  const grupo = s("g", {
    style: alClic ? "cursor:pointer" : "",
    onClick: alClic ? () => alClic(id) : null,
    // Marca para que el paneo (`hacerPaneable`) sepa que un gesto que arranca
    // acá es un clic sobre el nodo, no el fondo del canvas, y lo deje pasar
    // sin capturar el puntero.
    "data-nodo": alClic ? "1" : null,
  }, [
    rect,
    s("text", {
      x: pos.x + ANCHO_NODO / 2, y: pos.y + (secundaria ? 17 : 24),
      "text-anchor": "middle", "font-size": "11.5", "font-weight": "500", fill: color.texto,
    }, [recortar(etiqueta, 26)]),
    secundaria
      ? s("text", {
          x: pos.x + ANCHO_NODO / 2, y: pos.y + 31,
          "text-anchor": "middle", "font-size": "9.5", fill: "var(--texto-3)", "font-family": "var(--mono)",
        }, [recortar(secundaria, 30)])
      : null,
    s("title", {}, [`${id} · ${etiqueta}${secundaria ? ` · ${secundaria}` : ""}`]),
  ]);
  return { id, grupo, rect, colorBorde: color.borde };
}

/** Sólo para las `loop`: van hacia atrás a propósito, y quedan aparte del
 * ruteo por capas — no tiene sentido meterles nodos fantasma para "ir para
 * adelante" cuando el punto es justo lo contrario. Se dibujan igual que
 * siempre: derecho, punteado, del origen al destino real. */
function aristaSuelta(a, posicion) {
  const desde = posicion.get(a.from);
  const hasta = posicion.get(a.to);
  if (!desde || !hasta) return [];

  const x1 = desde.x + ANCHO_NODO / 2;
  const x2 = hasta.x + ANCHO_NODO / 2;
  const haciaAbajo = hasta.y > desde.y;
  const y1 = haciaAbajo ? desde.y + ALTO_NODO : desde.y;
  const y2 = haciaAbajo ? hasta.y : hasta.y + ALTO_NODO;

  // Curva en S vertical: dos puntos de control a media altura. Con líneas
  // rectas diagonales las aristas de un nodo con tres salidas se cruzan y no se
  // distingue cuál va a dónde.
  const medio = (y1 + y2) / 2;
  const d = `M ${x1} ${y1} C ${x1} ${medio}, ${x2} ${medio}, ${x2} ${y2}`;

  const color = a.condition === "err" ? "var(--rojo-borde)"
    : a.condition === "ok" ? "var(--verde-borde)"
    : "var(--borde-3)";

  const trazos = [s("path", {
    d, fill: "none", stroke: color, "stroke-width": "1.4",
    "marker-end": "url(#punta)",
    "stroke-dasharray": a.condition === "loop" ? "4 3" : null,
  })];

  if (a.condition) {
    const texto = recortar(a.condition, 22);
    const ancho = texto.length * 5.6 + 10;
    trazos.push(s("rect", {
      x: (x1 + x2) / 2 - ancho / 2, y: medio - 8, width: ancho, height: 15,
      rx: 3, fill: "var(--fondo)", stroke: color,
    }));
    trazos.push(s("text", {
      x: (x1 + x2) / 2, y: medio + 3, "text-anchor": "middle",
      "font-size": "9.5", fill: color, "font-family": "var(--mono)",
    }, [texto]));
  }
  return trazos;
}

/**
 * Una arista "de verdad" (no `loop`): recorre su cadena de nodos —reales y
 * fantasma— con una curva en S por tramo, igual estilo que antes pero
 * seguido, así se ve una sola línea continua y no una por segmento. El punto
 * de enganche en cada extremo real sale de `anclas`, no siempre el centro.
 */
function trazoDeArista(a, cadena, posicion, anclas) {
  if (!cadena) return [];

  const puntos = cadena.map((id, i) => {
    const pos = posicion.get(id);
    if (!pos) return null;
    if (esDummy(id)) return { x: pos.x + ANCHO_DUMMY / 2, y: pos.y + ALTO_NODO / 2 };
    if (i === 0) {
      const frac = anclas.anchoSalida.get(a) ?? 0.5;
      return { x: pos.x + frac * ANCHO_NODO, y: pos.y + ALTO_NODO };
    }
    const frac = anclas.anchoEntrada.get(a) ?? 0.5;
    return { x: pos.x + frac * ANCHO_NODO, y: pos.y };
  });
  if (puntos.some((p) => !p)) return [];

  let d = `M ${puntos[0].x} ${puntos[0].y}`;
  for (let i = 0; i < puntos.length - 1; i++) {
    const p1 = puntos[i], p2 = puntos[i + 1];
    const medio = (p1.y + p2.y) / 2;
    d += ` C ${p1.x} ${medio}, ${p2.x} ${medio}, ${p2.x} ${p2.y}`;
  }

  const color = a.condition === "err" ? "var(--rojo-borde)"
    : a.condition === "ok" ? "var(--verde-borde)"
    : "var(--borde-3)";

  const trazos = [s("path", { d, fill: "none", stroke: color, "stroke-width": "1.4", "marker-end": "url(#punta)" })];

  if (a.condition) {
    // El rótulo va pegado al primer tramo (la salida del origen), no al medio
    // del camino entero: un salto largo tiene varios nodos fantasma en el
    // medio, y un rótulo ahí flotaría lejos de cualquiera de los dos nodos
    // reales que en verdad conecta.
    const p1 = puntos[0], p2 = puntos[1];
    const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
    const texto = recortar(a.condition, 22);
    const ancho = texto.length * 5.6 + 10;
    trazos.push(s("rect", { x: mx - ancho / 2, y: my - 8, width: ancho, height: 15, rx: 3, fill: "var(--fondo)", stroke: color }));
    trazos.push(s("text", { x: mx, y: my + 3, "text-anchor": "middle", "font-size": "9.5", fill: color, "font-family": "var(--mono)" }, [texto]));
  }
  return trazos;
}

function recortar(texto, largo) {
  const t = String(texto || "");
  return t.length > largo ? t.slice(0, largo - 1) + "…" : t;
}

/**
 * Crear elementos sin framework y sin `innerHTML`.
 *
 * `innerHTML` con template literals parece más cómodo hasta que pasan las dos
 * cosas que pasan siempre: se pierden las referencias a los elementos (así que
 * cualquier cambio obliga a redibujar todo) y un dato de la API con `<` termina
 * ejecutándose. Acá el texto siempre es texto.
 */

/**
 * @param {string} tag
 * @param {object} props  class, text, style (objeto), on<Evento>, y atributos
 * @param {*} hijos  nodo, string, array, o null/false para no poner nada
 */
export function h(tag, props = {}, hijos = []) {
  const el = document.createElement(tag);

  for (const [clave, valor] of Object.entries(props || {})) {
    if (valor === null || valor === undefined || valor === false) continue;

    if (clave === "class") el.className = valor;
    else if (clave === "text") el.textContent = valor;
    else if (clave === "style" && typeof valor === "object") Object.assign(el.style, valor);
    else if (clave === "dataset") Object.assign(el.dataset, valor);
    else if (clave.startsWith("on") && typeof valor === "function") {
      el.addEventListener(clave.slice(2).toLowerCase(), valor);
    }
    // value/checked/disabled son propiedades, no atributos: puestos como
    // atributo dejan de reflejar lo que el usuario escribió.
    else if (clave === "value" || clave === "checked" || clave === "disabled") el[clave] = valor;
    else el.setAttribute(clave, valor);
  }

  // `flat(Infinity)`: los hijos se arman mapeando listas, y una lista anidada
  // por accidente fallaba con "parameter 1 is not of type Node" señalando al
  // `h` y no a quien la armó. Aplanar es más barato que rastrear eso cada vez.
  for (const hijo of [].concat(hijos).flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.appendChild(typeof hijo === "string" || typeof hijo === "number"
      ? document.createTextNode(String(hijo))
      : hijo);
  }
  return el;
}

/** Vacía un elemento sin tocar el resto del árbol. */
export function vaciar(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** Reemplaza el contenido de un elemento. */
export function poner(el, ...hijos) {
  vaciar(el);
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.appendChild(typeof hijo === "string" ? document.createTextNode(hijo) : hijo);
  }
  return el;
}

const NS = "http://www.w3.org/2000/svg";

/**
 * Un icono de línea. Nada de emoji: no escalan ni se recolorean.
 * @param {string} d  uno o varios `path` separados por `|`
 */
export function icono(d, tam = 14, ancho = 1.8) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", tam);
  svg.setAttribute("height", tam);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", ancho);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.style.flex = "0 0 auto";
  for (const parte of d.split("|")) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", parte);
    svg.appendChild(p);
  }
  return svg;
}

export const ICONOS = {
  marca: "M6 6v12|M18 11c0 4-5 4-8 4|M6 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"
       + "|M6 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4z|M18 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  alerta: "M12 4l9 16H3z|M12 10v4|M12 17h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z|M12 8h.01|M11 12h1v4h1",
  ok: "M20 6L9 17l-5-5",
  error: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z|M12 8v5|M12 16h.01",
  candado: "M4 10h16v11H4z|M8 10V7a4 4 0 0 1 8 0v3",
  basura: "M4 7h16|M9 7V4h6v3|M6 7l1 13h10l1-13",
  cerrar: "M6 6l12 12|M18 6l-12 12",
  plegar: "M11 7l-5 5 5 5|M18 7l-5 5 5 5",
  lapiz: "M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z",
  agrandar: "M4 9V4h5|M20 9V4h-5|M4 15v5h5|M20 15v5h-5",
  achicar: "M9 4v5H4|M15 4v5h5|M9 20v-5H4|M15 20v-5h5",
  campana: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"
         + "|M13.73 21a2 2 0 0 1-3.46 0",
  base: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3z"
      + "|M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6|M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
};

/** El logo de la barra lateral. */
export function marca() {
  const svg = icono(ICONOS.marca, 14, 2);
  svg.setAttribute("stroke", "#3b82f6");
  return svg;
}

/**
 * Un renderer de Markdown chico, a mano.
 *
 * Sin build no hay cómo traer una librería, y lo único que esto necesita
 * mostrar son notas de un release de GitHub: encabezados, listas, negrita,
 * cursiva, código en línea y links — no tablas ni bloques de código con
 * triple backtick. Lo que no reconoce queda como texto plano en su propio
 * párrafo, que es mejor que romper o que interpretarlo como HTML.
 *
 * Nunca pasa por `innerHTML`: cada pedazo de texto llega a `dom.js` como
 * `textContent`, así que un cuerpo de release con `<script>` no ejecuta
 * nada — sigue la misma regla que el resto de la app (`dom.js`).
 */

import { h } from "../dom.js";

/**
 * La primera línea no vacía, sin el `#`/`-`/`*` que la abre — el resumen
 * corto para una fila de tabla. La mayoría de las notas empiezan con un
 * título o una frase que resume el release; cuando no, al menos no queda
 * vacío.
 */
export function primeraLinea(md) {
  const linea = (md || "").split("\n").map((l) => l.trim()).find((l) => l);
  if (!linea) return "";
  return linea.replace(/^#{1,6}\s*/, "").replace(/^[-*]\s+/, "").trim();
}

/** El markdown entero, como nodos DOM listos para `poner()`. */
export function renderMarkdown(md) {
  const contenedor = h("div", { class: "markdown" });
  const lineas = (md || "").replace(/\r\n/g, "\n").split("\n");

  // Un párrafo son líneas seguidas sin blanco entre medio; una lista, viñetas
  // o números seguidos. Los dos se cortan al primer blanco, encabezado, regla
  // o al cambiar de tipo — como espera cualquiera que ya vio Markdown.
  let listaActual = null;
  let parrafo = [];

  const cerrarParrafo = () => {
    if (parrafo.length) contenedor.appendChild(h("p", {}, enLinea(parrafo.join(" "))));
    parrafo = [];
  };
  const cerrarLista = () => { listaActual = null; };

  for (const linea of lineas) {
    const t = linea.trim();

    if (!t) { cerrarParrafo(); cerrarLista(); continue; }

    const encabezado = /^(#{1,6})\s+(.*)$/.exec(t);
    if (encabezado) {
      cerrarParrafo(); cerrarLista();
      contenedor.appendChild(h(`h${Math.min(encabezado[1].length, 6)}`, {}, enLinea(encabezado[2])));
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      cerrarParrafo(); cerrarLista();
      contenedor.appendChild(h("hr"));
      continue;
    }

    const viñeta = /^[-*]\s+(.*)$/.exec(t);
    const numerada = /^\d+[.)]\s+(.*)$/.exec(t);
    if (viñeta || numerada) {
      cerrarParrafo();
      const etiqueta = numerada ? "ol" : "ul";
      if (!listaActual || listaActual.tagName.toLowerCase() !== etiqueta) {
        listaActual = h(etiqueta, {});
        contenedor.appendChild(listaActual);
      }
      listaActual.appendChild(h("li", {}, enLinea((viñeta || numerada)[1])));
      continue;
    }

    cerrarLista();
    parrafo.push(t);
  }
  cerrarParrafo();

  if (!contenedor.childNodes.length) {
    contenedor.appendChild(h("p", { class: "markdown__vacio", text: "Sin notas." }));
  }
  return contenedor;
}

/**
 * `**negrita**`, `*cursiva*`, `` `código` `` y `[texto](url)`, dentro de una
 * línea. Devuelve un array de nodos y strings — nunca un string armado a
 * mano — para no tener que volver a escapar nada al pasarlo a `h()`.
 */
function enLinea(texto) {
  const nodos = [];
  const patron = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*([^*]+)\*/g;
  let ultimo = 0;
  let m;
  while ((m = patron.exec(texto))) {
    if (m.index > ultimo) nodos.push(texto.slice(ultimo, m.index));
    if (m[1] !== undefined) nodos.push(h("strong", {}, [m[1]]));
    else if (m[2] !== undefined) nodos.push(h("code", {}, [m[2]]));
    else if (m[3] !== undefined) nodos.push(h("a", { href: m[4], target: "_blank", rel: "noopener", text: m[3] }));
    else if (m[5] !== undefined) nodos.push(h("em", {}, [m[5]]));
    ultimo = patron.lastIndex;
  }
  if (ultimo < texto.length) nodos.push(texto.slice(ultimo));
  return nodos;
}

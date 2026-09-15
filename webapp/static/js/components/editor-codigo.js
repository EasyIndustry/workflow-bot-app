/**
 * Un editor de texto con números de línea.
 *
 * Sin resaltado de sintaxis ni ninguna dependencia externa: es el mismo
 * mecanismo liviano que ya usaba el modo texto del editor de flujos (Mermaid)
 * — una columna de números sincronizada por scroll con un textarea de verdad —
 * generalizado para que lo use cualquier campo de código, empezando por los
 * `json` de un formulario (headers, payload).
 */

import { h } from "../dom.js";

/**
 * @param {string} valorInicial
 * @param {object} opciones {onCambiar, minHeight, anchoNumeros, llenarAltura}
 *   `llenarAltura` es para cuando el editor vive dentro de una columna que ya
 *   tiene su propia altura acotada (`flex:1; min-height:0`, como el modo
 *   texto de un flujo): el editor pasa a ocupar el 100% de esa caja y scrollea
 *   él solo, en vez de crecer con el texto y dejar que un scroll de página lo
 *   contenga por afuera — que es como terminan apareciendo dos scrolls
 *   verticales por la misma razón, uno para el texto y otro para todo lo de
 *   alrededor (el botón "Volver a parsear" incluido, que así queda siempre a
 *   la vista en vez de scrollear con el texto).
 * @returns {{elemento: HTMLElement, textarea: HTMLTextAreaElement}}
 */
export function crearEditorDeCodigo(valorInicial = "", {
  onCambiar = () => {}, minHeight = "90px", anchoNumeros = "30px", llenarAltura = false,
} = {}) {
  const numeros = h("div", {
    class: "mono",
    style: {
      flex: `0 0 ${anchoNumeros}`, padding: "9px 6px", textAlign: "right", fontSize: "11px",
      lineHeight: "1.55", color: "var(--texto-4)", background: "var(--fondo-panel)",
      borderRight: "1px solid var(--borde)", userSelect: "none", whiteSpace: "pre",
      overflow: llenarAltura ? "hidden" : "visible",
    },
  });

  const textarea = h("textarea", {
    class: "entrada entrada--area",
    style: {
      flex: "1", minWidth: "0", border: "none", borderRadius: "0",
      fontFamily: "var(--mono)", fontSize: "11.5px", lineHeight: "1.55",
      padding: "9px 10px", whiteSpace: "pre", overflowWrap: "normal",
      minHeight: llenarAltura ? "0" : minHeight,
      height: llenarAltura ? "100%" : "auto",
    },
    spellcheck: "false",
    value: valorInicial,
  });

  const refrescarNumeros = () => {
    numeros.textContent = textarea.value.split("\n").map((_, i) => i + 1).join("\n");
  };
  refrescarNumeros();

  textarea.addEventListener("input", () => { refrescarNumeros(); onCambiar(); });
  textarea.addEventListener("scroll", () => { numeros.scrollTop = textarea.scrollTop; });

  const elemento = h("div", {
    style: {
      display: "flex", border: "1px solid var(--borde)",
      height: llenarAltura ? "100%" : "auto", minHeight: "0",
    },
  }, [numeros, textarea]);

  return { elemento, textarea };
}

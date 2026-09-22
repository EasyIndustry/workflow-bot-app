/**
 * Las `{variables}` de un campo de texto, resaltadas mientras se escribe.
 *
 * El valor sigue siendo el texto plano del `<input>` —con sus llaves, que es
 * lo que el flujo guarda y el núcleo interpola—; lo que cambia es cómo se ve:
 * cada `{ruta}` sale marcada, distinta del texto fijo de alrededor, así
 * `C:\salida\{carpeta}\{env.CLIENTE}.pdf` se lee de un vistazo. Una variable
 * calificada por nodo, `{MOVER_PDF.ruta}`, muestra la relación entera: el
 * nodo en un color y la salida en otro.
 *
 * Cómo: un espejo detrás del campo. El input queda arriba con el texto
 * transparente y el cursor visible; debajo, una caja con las mismas clases
 * —misma fuente, mismo padding, mismo borde— dibuja el mismo texto con las
 * variables envueltas en un `<span>`. Se elige esto y no un `contenteditable`
 * porque el input de verdad conserva todo lo que ya funciona: escribir,
 * pegar, deshacer, seleccionar, el autocompletado y quien escucha `input`.
 *
 * La marca no usa negrita de verdad: una letra en negrita es más ancha, y en
 * una fuente proporcional el texto del espejo dejaría de coincidir con el del
 * input, que es el que mueve el cursor. El "peso" se hace con `text-shadow`,
 * que engorda el trazo sin mover una sola letra. Ver `.variable` en el CSS.
 */

import { h } from "../dom.js";

// {nombre}, {objeto.campo}, {env.CLAVE}: lo mismo que reconoce el núcleo.
const VARIABLE = /\{[\w.]+\}/g;

/**
 * El texto partido en trozos: strings para lo fijo, <span> para cada variable.
 *
 * `esNodo(nombre)` dice si el primer tramo antes del punto es un nodo del
 * flujo: entonces `{NODO.salida}` se dibuja en dos tonos, nodo y salida. Sin
 * eso, `{a.b}` es lo que siempre fue —`env.CLAVE`, un campo de un objeto— y
 * va de un solo tono. `nodoSoportado` dice si el núcleo ya resuelve esa forma
 * (core#30); mientras no, se marca como pendiente y no como válida.
 */
export function trozos(texto, { esNodo = () => false, nodoSoportado = false } = {}) {
  const salida = [];
  let desde = 0;
  for (const m of texto.matchAll(VARIABLE)) {
    if (m.index > desde) salida.push(texto.slice(desde, m.index));
    const adentro = m[0].slice(1, -1);
    const punto = adentro.indexOf(".");
    const nodo = punto > 0 ? adentro.slice(0, punto) : "";
    if (nodo && esNodo(nodo)) {
      salida.push(h("span", {
        class: "variable variable--nodo" + (nodoSoportado ? "" : " variable--sin-nucleo"),
        title: nodoSoportado
          ? `la salida "${adentro.slice(punto + 1)}" del nodo ${nodo}`
          : `El núcleo todavía no resuelve {nodo.salida} (core#30): al correr queda sin valor.`,
      }, [
        "{", h("span", { class: "variable__nodo", text: nodo }), ".",
        h("span", { class: "variable__nombre", text: adentro.slice(punto + 1) }), "}",
      ]));
    } else {
      salida.push(h("span", { class: "variable", text: m[0] }));
    }
    desde = m.index + m[0].length;
  }
  if (desde < texto.length) salida.push(texto.slice(desde));
  return salida;
}

/**
 * Envuelve el campo en su caja con espejo y lo mantiene sincronizado.
 * Sólo para `<input type="text">` de una línea: un textarea envuelve líneas y
 * el espejo tendría que copiar también ese envolvimiento.
 *
 * @param {HTMLInputElement} campo
 * @param {object} opciones  las de `trozos`: {esNodo, nodoSoportado}
 */
export function resaltarVariables(campo, opciones = {}) {
  if (!campo.parentNode || campo.dataset.resaltado) return;
  campo.dataset.resaltado = "1";

  const espejo = h("div", { class: `${campo.className} resaltado__espejo`, "aria-hidden": "true" });
  const caja = h("div", { class: "resaltado" });
  campo.parentNode.insertBefore(caja, campo);
  caja.append(espejo, campo);
  campo.classList.add("resaltado__campo");

  const pintar = () => {
    espejo.replaceChildren(...trozos(campo.value, opciones));
    espejo.scrollLeft = campo.scrollLeft;
  };
  campo.addEventListener("input", pintar);
  // Un valor más largo que el campo scrollea adentro del input; el espejo
  // tiene que seguirlo o las marcas quedan sobre otras letras.
  campo.addEventListener("scroll", () => { espejo.scrollLeft = campo.scrollLeft; });
  pintar();
  return { pintar };
}

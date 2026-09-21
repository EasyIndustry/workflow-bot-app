/**
 * Dos o tres vistas adentro de un mismo panel.
 *
 * Nace de Config: varias secciones venían creciendo hasta ser dos pantallas
 * apiladas en una —secretos y variables, las raíces de archivos y los
 * programas permitidos, los repos y cada componente de Actualizaciones—, y
 * quien entraba tenía que barrer con el scroll para encontrar la mitad que
 * buscaba. Partirlas en secciones del lateral tampoco servía: son la misma
 * idea vista de dos maneras, y separarlas ahí las hace parecer temas
 * distintos.
 *
 * La vista elegida va en la URL (`#/config/limites/programas`), no en una
 * variable de módulo: así un enlace lleva a donde uno quiere, recargar no
 * devuelve a la primera, y el botón de atrás hace lo que parece. Es la misma
 * razón por la que el alta de un item de colección tiene su propia URL.
 */

import { h } from "../dom.js";

/**
 * @param {Array<{id: string, label: string}>} vistas
 * @param {string} activa   id de la que se está viendo
 * @param {(id: string) => void} alElegir
 */
export function subVistas(vistas, activa, alElegir) {
  return h("div", { class: "subvistas" }, vistas.map((v) => h("button", {
    class: "subvistas__tab" + (v.id === activa ? " subvistas__tab--activa" : ""),
    text: v.label,
    onClick: () => { if (v.id !== activa) alElegir(v.id); },
  })));
}

/**
 * Cuál mostrar, dado lo que vino en la URL.
 *
 * Un id que no existe —un enlace viejo, una vista que se renombró— cae en la
 * primera en vez de dejar el panel vacío, que es lo que se veía cuando la
 * pantalla no podía dibujar nada y no decía por qué.
 */
export function vistaElegida(vistas, id) {
  return vistas.find((v) => v.id === id) || vistas[0];
}

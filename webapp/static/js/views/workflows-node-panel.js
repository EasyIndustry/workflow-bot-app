/**
 * La tarjeta de un nodo, en un panel compacto anclado adentro del propio
 * diagrama — para editarlo sin salir del render ni ir a buscarlo en la pila
 * de Tarjetas.
 *
 * No reimplementa nada de la edición: reusa el mismo cuerpo que arma
 * `workflows-cards.js` para su pila (`contenidoDeNodo`) — el selector de
 * tool, los params del manifest, las variables disponibles, las aristas. Lo
 * único propio de este módulo es el marco: encabezado, cerrar, y el atajo
 * para abrir el mismo nodo en la pestaña Tarjetas si hace falta más lugar.
 */

import { h, icono, ICONOS } from "../dom.js";
import { contenidoDeNodo, TIPO_ROTULO } from "./workflows-cards.js";

/**
 * @param {string} id
 * @param {object} grafo      el grafo mutable que edita la vista
 * @param {object} catalogo   GET /tools
 * @param {object} opts       {alCambiar, alCerrar, alAbrirCompleta, columnasDeLaFila}
 */
export function tarjetaFlotante(id, grafo, catalogo, { alCambiar, alCerrar, alAbrirCompleta, columnasDeLaFila }) {
  const nodo = grafo.nodes[id];
  if (!nodo) return null;

  return h("div", {
    style: {
      position: "absolute", left: "10px", right: "10px", bottom: "10px",
      maxHeight: "60%", display: "flex", flexDirection: "column",
      background: "var(--fondo)", border: "1px solid var(--borde-fuerte)",
      borderRadius: "5px", boxShadow: "0 6px 24px rgba(0,0,0,.18)", zIndex: "15",
    },
  }, [
    h("div", {
      style: {
        display: "flex", alignItems: "center", gap: "8px", padding: "8px 10px",
        borderBottom: "1px solid var(--borde)", background: "var(--fondo-cabecera)",
        borderRadius: "5px 5px 0 0", flexShrink: "0",
      },
    }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { style: { fontSize: "12.5px", fontWeight: "600", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
                   text: nodo.display || nodo.label || nodo.variable || nodo.fn || id }),
        h("div", { class: "mono", style: { fontSize: "10.5px", color: "var(--texto-4)" },
                   text: `${id} · ${nodo.type === "action" ? (nodo.fn || "sin tool") : TIPO_ROTULO[nodo.type] || nodo.type}` }),
      ]),
      h("button", { class: "btn btn--chico", text: "Abrir en Tarjetas", onClick: alAbrirCompleta }),
      h("button", { class: "btn btn--chico", title: "Cerrar", onClick: alCerrar }, [icono(ICONOS.cerrar, 11, 2)]),
    ]),
    h("div", { style: { flex: "1", minHeight: "0", overflow: "auto" } }, [
      contenidoDeNodo(id, grafo, catalogo, alCambiar, columnasDeLaFila),
    ]),
  ]);
}

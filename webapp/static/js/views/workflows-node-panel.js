/**
 * El editor de un nodo, **adentro de su propia caja** del diagrama: al
 * seleccionarlo, el nodo se agranda en el lienzo y muestra esto, con los
 * parámetros ahí mismo. Clic en otro nodo o en el fondo y vuelve a su tamaño.
 *
 * Antes era una tarjeta flotante anclada abajo del visor, y tenía dos
 * problemas: tapaba una franja del dibujo justo cuando uno quiere mirarlo, y
 * nada la ataba visualmente al nodo que estaba editando — con diez cajas
 * iguales en pantalla había que acordarse de cuál se había tocado. El nodo
 * abierto es la misma información sin ninguna de las dos cosas; el lienzo le
 * hace lugar de verdad (ver `NODO_ANCHO_ABIERTO` en workflows-graph.js).
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
 * @param {object} opts       {alCambiar, alCerrar, alAbrirCompleta, paso, estado, hayCorrida, columnasDeLaFila, grande, alAgrandar, ramaDry}
 *   `paso` es la entrada de este nodo en el trace del último dry run (o null si
 *   el recorrido no pasó por él), y `estado` cómo lo pintó el lienzo ("ok",
 *   "err", "aviso"); `hayCorrida` dice si hubo algún dry run, para
 *   distinguir "no se corrió nada" de "se corrió y este nodo quedó afuera".
 *   `ramaDry` ({ramas, elegida, alElegir}), sólo en una decisión: qué rama
 *   probar en seco.
 *   `columnasDeLaFila` es lo que el autocompletado ofrece como columnas.
 *   `grande` dice con qué tamaño está dibujado, y `alAgrandar` lo alterna: el
 *   tamaño lo decide el layout del lienzo, no el panel.
 * @returns {HTMLElement} pensado para llenar la caja del nodo: ocupa el 100 %
 *   de lo que le den y scrollea adentro. El marco (borde, sombra) lo pone el
 *   propio nodo del SVG.
 */
export function panelDeNodo(id, grafo, catalogo, { alCambiar, alCerrar, alAbrirCompleta, paso = null, estado = null, hayCorrida = false, columnasDeLaFila = null, grande = false, alAgrandar = null, ramaDry = null }) {
  const nodo = grafo.nodes[id];
  if (!nodo) return null;

  return h("div", {
    // `nodo-panel`: la caja del nodo es angosta (unos 400 px), y con la
    // etiqueta de cada campo ocupando 200 px al control le quedaba la mitad y
    // la ayuda se leía en una columna de cuatro palabras. La clase apila
    // etiqueta y control (ver componentes.css); es lo único que cambia
    // respecto de los mismos campos en la pila de Tarjetas.
    class: "nodo-panel",
    style: {
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--fondo)", borderRadius: "11px", overflow: "hidden",
    },
  }, [
    h("div", {
      style: {
        display: "flex", alignItems: "center", gap: "8px", padding: "8px 10px",
        borderBottom: "1px solid var(--borde)", background: "var(--fondo-cabecera)",
        flexShrink: "0",
      },
    }, [
      h("div", { style: { minWidth: "0", flex: "1" } }, [
        h("div", { style: { fontSize: "12.5px", fontWeight: "600", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
                   text: nodo.display || nodo.label || nodo.variable || nodo.fn || id }),
        h("div", { class: "mono", style: { fontSize: "10.5px", color: "var(--texto-4)" },
                   text: `${id} · ${nodo.type === "action" ? (nodo.fn || "sin tool") : TIPO_ROTULO[nodo.type] || nodo.type}` }),
      ]),
      paso
        ? h("span", { class: paso.status === "err" ? "badge badge--error" : estado === "aviso" ? "badge badge--falta" : "badge badge--ok",
                      text: paso.status === "err" ? "falló en seco" : estado === "aviso" ? "sin valor en seco" : "ok en seco" })
        : hayCorrida ? h("span", { class: "badge", text: "no recorrido" }) : null,
      h("button", { class: "btn btn--chico", text: "Abrir en Tarjetas", onClick: alAbrirCompleta }),
      alAgrandar
        ? h("button", { class: "btn btn--chico", title: grande ? "Achicar el nodo" : "Agrandar el nodo", onClick: alAgrandar },
            [icono(grande ? ICONOS.achicar : ICONOS.agrandar, 11, 2)])
        : null,
      h("button", { class: "btn btn--chico", title: "Cerrar", onClick: alCerrar }, [icono(ICONOS.cerrar, 11, 2)]),
    ]),
    // `overscrollBehavior`: al llegar al final, la rueda no sigue de largo a
    // scrollear lo que haya detrás del lienzo.
    // La clase la busca `workflows.js` para reponer el scroll al redibujar.
    h("div", { class: "nodo-panel__scroll", style: { flex: "1", minHeight: "0", overflow: "auto", overscrollBehavior: "contain" } }, [
      paso ? resultadoDry(paso, estado) : null,
      ramaDry ? selectorDeRama(ramaDry) : null,
      contenidoDeNodo(id, grafo, catalogo, alCambiar, columnasDeLaFila),
    ]),
  ]);
}

/**
 * Qué rama probar en seco, en una decisión. En seco las acciones no corren, así
 * que una decisión sobre lo que deja una de ellas no tiene con qué decidir y el
 * núcleo sigue por la primera rama: sin esto, las demás no se podían revisar
 * nunca. "Automática" es lo que haya en la fila elegida en Registro.
 */
function selectorDeRama({ ramas, elegida, alElegir }) {
  if (!ramas.length) return null;
  const AUTO = "";
  const selector = h("select", {
    class: "selector",
    onChange: (e) => alElegir(e.target.value === AUTO ? null : e.target.value),
  }, [
    h("option", { value: AUTO, text: "automática (lo que dé la fila)" }),
    ...ramas.map((r) => h("option", { value: r.valor, text: r.etiqueta })),
  ]);
  selector.value = elegida ?? AUTO;
  return h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "En seco, probar la rama" })]),
    h("div", { class: "campo__control" }, [
      selector,
      h("div", { class: "campo__ayuda", text: "Sólo para el dry run: la corrida de verdad decide con el valor real." }),
    ]),
  ]);
}

/**
 * Lo que el dry run resolvió para este nodo, arriba del editor: los params
 * **ya interpolados** y el mensaje si falló. Es la misma columna que justifica
 * la tabla del pie, pero al lado del nodo que uno acaba de tocar en el lienzo
 * — como el panel de salida que n8n abre sobre cada nodo ejecutado.
 */
function resultadoDry(paso, estado) {
  const params = paso.params || {};
  const claves = Object.keys(params);
  const fallo = paso.status === "err";
  const aviso = estado === "aviso";
  const esDecision = paso.node_type === "decision";
  const tono = fallo ? "rojo" : aviso ? "ambar" : "verde";
  return h("div", {
    style: {
      padding: "8px 10px", borderBottom: "1px solid var(--borde)",
      background: `var(--${tono}-fondo)`,
    },
  }, [
    h("div", { style: { fontSize: "10.5px", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".04em",
                        color: `var(--${tono})`, marginBottom: "4px" },
               text: esDecision ? (aviso ? "Dry run · sin valor para decidir" : "Dry run · lo que decidió") : "Dry run · parámetros ya resueltos" }),
    // Una decisión no tiene params: lo que importa es con qué valor decidió.
    esDecision
      ? h("div", { class: "mono", style: { fontSize: "11px" },
                   text: paso.decision_value ? `valor = "${paso.decision_value}"` : "sin valor" })
      : claves.length
      ? h("div", { style: { display: "grid", gridTemplateColumns: "max-content 1fr", gap: "1px 10px", fontSize: "11px", lineHeight: "1.55" } },
          claves.flatMap((k) => [
            h("span", { class: "mono", style: { color: "var(--texto-3)" }, text: k }),
            h("span", { class: "mono", style: { wordBreak: "break-all" }, text: String(params[k]) }),
          ]))
      : h("div", { style: { fontSize: "11px", color: "var(--texto-3)" }, text: "Este nodo no lleva parámetros." }),
    paso.message
      ? h("div", { style: { marginTop: "6px", fontSize: "11.5px", color: fallo ? "var(--rojo)" : "var(--texto-2)" }, text: paso.message })
      : null,
  ]);
}

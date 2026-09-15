/**
 * El render "original": el mismo archivo `.mmd`, dibujado por Mermaid.
 *
 * Es la segunda vista del diagrama, al lado del render propio
 * (workflows-graph.js). No lo reemplaza: el propio sabe de estados de dry run,
 * de la tarjeta flotante y de los colores del sistema; éste muestra el flujo
 * tal cual lo vería cualquier otro visor de Mermaid — sirve para comparar, y
 * para confiar en que lo que se guarda es lo que se cree.
 *
 * La librería pesa casi 3 MB, así que va embarcada en `static/vendor/mermaid`
 * (la app corre sin internet) y se carga a demanda, la primera vez que alguien
 * elige esta vista. El render propio no la toca.
 */

import { h } from "../dom.js";
import { aviso } from "../components/aviso.js";
import { envolverEnLienzo } from "./workflows-graph.js";

const RUTA = "/static/vendor/mermaid/mermaid.min.js";

let carga = null;

/** Carga la librería una sola vez; las demás llamadas esperan la misma promesa. */
function cargarMermaid() {
  if (window.mermaid) return Promise.resolve(window.mermaid);
  if (carga) return carga;
  carga = new Promise((resolver, rechazar) => {
    const script = document.createElement("script");
    script.src = RUTA;
    script.onload = () => {
      if (!window.mermaid) return rechazar(new Error("La librería cargó pero no expuso `mermaid`."));
      window.mermaid.initialize({
        startOnLoad: false,
        // Nada de HTML dentro de las etiquetas: el texto viene del archivo.
        securityLevel: "strict",
        theme: "neutral",
        flowchart: { useMaxWidth: false, htmlLabels: false },
      });
      resolver(window.mermaid);
    };
    script.onerror = () => {
      carga = null;
      rechazar(new Error(`No se pudo cargar ${RUTA}.`));
    };
    document.head.appendChild(script);
  });
  return carga;
}


let contador = 0;

/**
 * @param {string} texto   el contenido del `.mmd`, tal cual se guarda
 * @returns {HTMLElement}  el visor; se llena solo cuando termina el render
 */
export function dibujarMermaid(texto) {
  const visor = h("div", {
    style: { width: "100%", height: "100%", overflow: "hidden", position: "relative" },
  }, [h("div", { class: "tabla__vacia", text: "Dibujando con Mermaid…" })]);

  if (!texto || !texto.trim()) {
    visor.replaceChildren(h("div", { class: "tabla__vacia", text: "El flujo todavía no tiene texto." }));
    return visor;
  }

  (async () => {
    try {
      const mermaid = await cargarMermaid();
      const id = `mermaid-flujo-${++contador}`;
      const { svg } = await mermaid.render(id, texto);
      // Si mientras tanto se cambió de vista, el visor ya no está en pantalla
      // y no vale la pena escribirle.
      if (!visor.isConnected) return;
      const caja = h("div");
      caja.innerHTML = svg;
      const el = caja.querySelector("svg");
      if (!el) throw new Error("Mermaid no devolvió un SVG.");
      // Con `useMaxWidth:false` Mermaid escribe el tamaño natural en
      // width/height; el `viewBox` lo tiene siempre. De ahí sale el tamaño base
      // con el que el lienzo sabe cuánto es "el diagrama entero".
      const vb = (el.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
      const ancho = parseFloat(el.getAttribute("width")) || vb[2] || el.clientWidth || 800;
      const alto = parseFloat(el.getAttribute("height")) || vb[3] || el.clientHeight || 600;
      el.setAttribute("width", ancho);
      el.setAttribute("height", alto);
      el.style.maxWidth = "none";
      el.style.display = "block";
      const { envoltura, lienzo } = envolverEnLienzo(el, ancho, alto);
      visor.replaceChildren(envoltura);
      // Un flujo real dibujado por Mermaid, con los params completos en cada
      // etiqueta, sale de varios miles de píxeles de ancho: arrancar a escala
      // 1 mostraba una esquina blanca. Se abre entero y de ahí se acerca.
      lienzo.ajustar();
    } catch (e) {
      if (!visor.isConnected) return;
      // Mermaid deja un `<div id=...>` colgado en el body cuando falla el parse.
      for (const huerfano of document.querySelectorAll('[id^="dmermaid-flujo-"], [id^="mermaid-flujo-"]')) {
        if (!visor.contains(huerfano)) huerfano.remove();
      }
      visor.replaceChildren(aviso("error", "Mermaid no pudo dibujar este archivo",
        h("pre", {
          class: "mono",
          style: { whiteSpace: "pre-wrap", margin: "6px 0 0", fontSize: "11.5px" },
          text: mensajeDe(e),
        })));
    }
  })();

  return visor;
}

function mensajeDe(e) {
  if (!e) return "Error desconocido.";
  const m = e.message || String(e);
  // El parser de Mermaid repite el texto entero en su mensaje: con la primera
  // parte alcanza para ubicar la línea.
  return m.length > 600 ? m.slice(0, 600) + "…" : m;
}

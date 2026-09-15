/**
 * El marco de la app: barra lateral y pestañas.
 *
 * Se arma una sola vez y sobrevive al cambio de vista. Cada vista escribe en
 * los dos huecos que este módulo devuelve — no reemplaza el marco.
 */

import { h, poner, marca, vaciar } from "./dom.js";
import { irA } from "./router.js";

export const PESTANAS = [
  { id: "sources", label: "Sources" },
  { id: "workflows", label: "Workflows" },
  { id: "plugins", label: "Plug ins" },
  { id: "agente", label: "Agente" },
  { id: "config", label: "Config" },
];

export function crearShell(raiz) {
  const rotulo = h("div", { class: "lateral__rotulo" });
  const cuerpoLateral = h("div", { class: "lateral__cuerpo" });
  const pieLateral = h("div", { class: "lateral__pie", text: "v0.9 · local" });
  const extraLateral = h("div");

  const lateral = h("div", { class: "lateral" }, [
    h("div", { class: "lateral__marca", title: "Inicio", style: { cursor: "pointer" }, onClick: () => irA("inicio") },
      [marca(), h("span", { text: "FLOW-BOT" })]),
    rotulo,
    cuerpoLateral,
    extraLateral,
    pieLateral,
  ]);

  const pestanas = h("div", { class: "pestanas" });
  const botones = {};
  for (const p of PESTANAS) {
    const b = h("div", { class: "pestana", text: p.label, onClick: () => irA(p.id) });
    botones[p.id] = b;
    pestanas.appendChild(b);
  }

  const vista = h("div", { class: "vista" });
  const principal = h("div", { class: "principal" }, [pestanas, vista]);

  poner(raiz, h("div", { class: "shell" }, [lateral, principal]));

  return {
    vista,
    cuerpoLateral,
    extraLateral,

    /** Marca la pestaña activa. */
    marcarPestana(id) {
      for (const [clave, boton] of Object.entries(botones)) {
        boton.className = clave === id ? "pestana pestana--activa" : "pestana";
      }
    },

    /** El rótulo de la barra lateral cambia por pestaña. */
    ponerRotulo(texto) {
      rotulo.textContent = texto || "";
      rotulo.style.display = texto ? "" : "none";
    },

    /** Deja la barra lateral lista para que la escriba la vista. */
    limpiarLateral() {
      vaciar(cuerpoLateral);
      vaciar(extraLateral);
    },
  };
}

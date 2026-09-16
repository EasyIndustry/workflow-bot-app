/**
 * El marco de la app: barra lateral y pestañas.
 *
 * Se arma una sola vez y sobrevive al cambio de vista. Cada vista escribe en
 * los dos huecos que este módulo devuelve — no reemplaza el marco.
 */

import { h, poner, marca, vaciar, icono, ICONOS } from "./dom.js";
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
  // A diferencia de `extraLateral`, esta no la vacía `limpiarLateral()`: es el
  // lugar donde vive el indicador de la terminal del agente (ver
  // `agent_terminal.js`), que tiene que sobrevivir al cambio de pestaña igual
  // que la sesión que representa.
  const indicadorTerminal = h("div", { class: "lateral__indicador" });

  // Plegado: la barra queda en una franja del ancho del ícono. La preferencia
  // vive en el navegador porque es de quien opera, no de la instalación, y
  // recargar no tiene por qué volver a abrirla.
  const CLAVE_PLEGADO = "lateral-plegado";
  let shellEl = null;
  const plegar = (si) => {
    shellEl.classList.toggle("shell--plegado", si);
    try { localStorage.setItem(CLAVE_PLEGADO, si ? "1" : ""); } catch { /* sin storage, no se recuerda */ }
  };
  const botonPlegar = h("button", {
    class: "lateral__plegar", title: "Ocultar el panel",
    onClick: (e) => { e.stopPropagation(); plegar(true); },
  }, [icono(ICONOS.plegar, 12, 2)]);

  const lateral = h("div", { class: "lateral" }, [
    h("div", {
      class: "lateral__marca", title: "Inicio", style: { cursor: "pointer" },
      // Plegada, la marca es lo único que queda: tocarla vuelve a abrir el panel.
      onClick: () => (shellEl.classList.contains("shell--plegado") ? plegar(false) : irA("inicio")),
    }, [marca(), h("span", { text: "FLOW-BOT" }), botonPlegar]),
    rotulo,
    cuerpoLateral,
    extraLateral,
    indicadorTerminal,
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

  shellEl = h("div", { class: "shell" }, [lateral, principal]);
  let plegadoGuardado = false;
  try { plegadoGuardado = localStorage.getItem(CLAVE_PLEGADO) === "1"; } catch { /* idem */ }
  if (plegadoGuardado) shellEl.classList.add("shell--plegado");
  poner(raiz, shellEl);

  return {
    vista,
    cuerpoLateral,
    extraLateral,
    indicadorTerminal,

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

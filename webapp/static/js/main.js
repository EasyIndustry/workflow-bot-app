/**
 * Arranque.
 *
 * Cada vista es un módulo que se baja cuando se abre, con `import()` dinámico:
 * es nativo del navegador, no necesita build, y sólo se descarga lo que se usa.
 */

import { crearShell } from "./shell.js";
import { alCambiar, rutaActual, irA } from "./router.js";
import { h, poner } from "./dom.js";

const VISTAS = {
  inicio: () => import("./views/inicio.js"),
  plugins: () => import("./views/plugins.js"),
  config: () => import("./views/config.js"),
  sources: () => import("./views/sources.js"),
  workflows: () => import("./views/workflows.js"),
  agente: () => import("./views/agente.js"),
};

const shell = crearShell(document.getElementById("app"));

function pendiente(nombre) {
  shell.limpiarLateral();
  shell.ponerRotulo("");
  poner(shell.vista, h("div", { class: "cargando" }, [
    h("div", { class: "titulo", text: nombre }),
    h("div", { class: "subtitulo", style: { margin: "8px auto 0" },
               text: "Esta pantalla está diseñada pero todavía no escrita." }),
  ]));
}

async function navegar(ruta) {
  const id = ruta.vista || "plugins";
  shell.marcarPestana(id);

  const cargar = VISTAS[id];
  if (!cargar) return pendiente(id);

  poner(shell.vista, h("div", { class: "cargando", text: "Cargando…" }));
  try {
    const modulo = await cargar();
    await modulo.montar(shell, ruta.partes);
  } catch (e) {
    poner(shell.vista, h("div", { class: "aviso aviso--error" }, [
      h("div", { class: "aviso__cuerpo" }, [
        h("div", { class: "aviso__titulo", text: "No se pudo abrir la pantalla" }),
        h("div", { text: e.message || String(e) }),
      ]),
    ]));
  }
}

alCambiar(navegar);

// Sin hash: una instalación recién hecha —sin plugins, fuentes ni flujos—
// arranca en Inicio, que dice qué sigue; una en uso, en Plug ins como siempre.
// Si el resumen no contesta, Plug ins igual: la pantalla de arranque no puede
// ser lo que impida entrar.
if (!location.hash) {
  import("./api.js")
    .then(({ api }) => api.resumen())
    .then((r) => irA(r.fresh ? "inicio" : "plugins"))
    .catch(() => irA("plugins"));
} else {
  navegar(rutaActual());
}

/**
 * Arranque.
 *
 * Cada vista es un módulo que se baja cuando se abre, con `import()` dinámico:
 * es nativo del navegador, no necesita build, y sólo se descarga lo que se usa.
 */

import { crearShell } from "./shell.js";
import { alCambiar, rutaActual, irA, recordarRuta } from "./router.js";
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
  recordarRuta({ vista: id, partes: ruta.partes });

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

// El título de la pestaña es el nombre que esta instalación se puso (Config →
// General, webapp/identidad.py), no siempre "Bot". Con varios Bots abiertos
// en pestañas del mismo navegador —cada uno con su URL, por IP— es lo único
// que distingue una de otra sin leer la barra de direcciones; y funciona
// tanto en la pestaña propia como en la que otra máquina abrió con la IP de
// ésta, porque cada Bot titula la suya sola, sin depender de qué la abrió.
function titular(r) {
  // Si este Bot todavía no se puso nombre (Config → General), el `?bot=` con
  // el que se abrió la pestaña es el respaldo: el alias que la persona le
  // puso a esta conexión en su lista, guardado en su propia colección — más
  // útil que un Bot sin nombrar. Es una convención genérica de la URL, no
  // algo que sepa de qué plugin la puso ahí.
  const desdeUrl = new URLSearchParams(location.search).get("bot");
  document.title = (r && r.nombre) || desdeUrl || "Bot";
}

// Sin hash: una instalación recién hecha —sin plugins, fuentes ni flujos—
// arranca en Inicio, que dice qué sigue; una en uso, en Plug ins como siempre.
// Si el resumen no contesta, Plug ins igual: la pantalla de arranque no puede
// ser lo que impida entrar.
if (!location.hash) {
  import("./api.js")
    .then(({ api }) => api.resumen())
    .then((r) => { titular(r); irA(r.fresh ? "inicio" : "plugins"); })
    .catch(() => irA("plugins"));
} else {
  navegar(rutaActual());
  // Con hash ya hay ruta: el título no puede esperar a que se resuelva, así
  // que se pide aparte y en paralelo.
  import("./api.js").then(({ api }) => api.resumen()).then(titular).catch(() => {});
}

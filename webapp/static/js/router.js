/**
 * Ruteo por hash.
 *
 * Sin history API a propósito: el servidor sirve un solo HTML y con hash no
 * hace falta que sepa nada de las rutas del front. `#/plugins/http` es
 * {vista: "plugins", partes: ["http"]}.
 */

const oyentes = [];

export function rutaActual() {
  const crudo = location.hash.replace(/^#\/?/, "");
  const partes = crudo.split("/").filter(Boolean).map(decodeURIComponent);
  return { vista: partes[0] || "", partes: partes.slice(1) };
}

export function irA(...partes) {
  location.hash = "#/" + partes.filter(Boolean).map(encodeURIComponent).join("/");
}

// La última ruta completa de cada vista, para que la pestaña vuelva a donde
// se estaba —la fuente con sus filtros, el flujo a medio editar, el item del
// plugin— y no al primero de la lista. Antes la pestaña iba a `#/sources` pelado
// y la vista elegía la primera fuente, así que cambiar de pestaña era perder el
// lugar. En sessionStorage para que sobreviva a un F5 de esta pestaña del
// navegador y no a otra: dos pestañas del navegador son dos lugares distintos.
const CLAVE_RUTAS = "bot.rutas";
const _rutas = (() => {
  try { return JSON.parse(sessionStorage.getItem(CLAVE_RUTAS) || "{}"); } catch { return {}; }
})();

export function recordarRuta(ruta) {
  if (!ruta.vista) return;
  _rutas[ruta.vista] = ruta.partes;
  try { sessionStorage.setItem(CLAVE_RUTAS, JSON.stringify(_rutas)); } catch { /* sin storage, dura la sesión */ }
}

/** Vuelve a la vista por donde se la dejó; sin rastro, a su raíz. */
export function volverA(vista) {
  irA(vista, ...(_rutas[vista] || []));
}

export function alCambiar(fn) {
  oyentes.push(fn);
}

window.addEventListener("hashchange", () => {
  const ruta = rutaActual();
  for (const fn of oyentes) fn(ruta);
});

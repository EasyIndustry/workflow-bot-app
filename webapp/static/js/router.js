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

export function alCambiar(fn) {
  oyentes.push(fn);
}

window.addEventListener("hashchange", () => {
  const ruta = rutaActual();
  for (const fn of oyentes) fn(ruta);
});

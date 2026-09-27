/**
 * Preferencias de quien opera, no de la instalación: viven en el navegador
 * (`localStorage`), igual que el plegado de la barra lateral en `shell.js`.
 *
 * La primera fue si además de los releases finales se quieren ver los de
 * prueba. La usan Config → Actualizaciones y el botón de notificaciones del
 * marco — si cada uno tuviera la suya, activarla en un lado y no en el otro
 * dejaría a la campana avisando sólo de finales mientras la pantalla ya
 * muestra las de prueba, sin que nada lo explique.
 */

const CLAVE_INCLUIR_PRUEBA = "actualizaciones-incluir-prueba";

/** Por defecto muestra todo, prueba incluida: es como arrancaba la pantalla antes de esto. */
export function incluirPrueba() {
  try { return localStorage.getItem(CLAVE_INCLUIR_PRUEBA) !== "0"; } catch { return true; }
}

export function guardarIncluirPrueba(valor) {
  try { localStorage.setItem(CLAVE_INCLUIR_PRUEBA, valor ? "1" : "0"); } catch { /* sin storage, no se recuerda */ }
}

// Si Workflows esconde la columna de Tarjetas/Texto y deja sólo el diagrama.
// Con el lienzo que edita en el lugar, quien arma el flujo desde el dibujo no
// necesita la pila al lado; quien la usa, no la pierde por default.
const CLAVE_SOLO_DIAGRAMA = "workflows-solo-diagrama";

export function soloDiagrama() {
  try { return localStorage.getItem(CLAVE_SOLO_DIAGRAMA) === "1"; } catch { return false; }
}

export function guardarSoloDiagrama(valor) {
  try { localStorage.setItem(CLAVE_SOLO_DIAGRAMA, valor ? "1" : "0"); } catch { /* sin storage, no se recuerda */ }
}

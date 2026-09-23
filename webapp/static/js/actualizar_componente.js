/**
 * Instalar un release de un componente (núcleo o web app): confirmar,
 * aplicar, mostrar el resultado y, si se puede, reiniciar.
 *
 * Vive acá y no adentro de `views/config.js` porque lo dispara la misma
 * pantalla de Config → Actualizaciones **y** el botón de notificaciones del
 * marco (`components/notificaciones.js`) — es el mismo flujo completo, no
 * una versión resumida para la campana, así que escribirlo dos veces
 * significaría mantenerlo dos veces.
 *
 * No toca `shell.vista`: todo lo que dibuja (el modal, la pantalla de
 * "reiniciando") vive en su propio overlay sobre `document.body`, para
 * poder dispararse desde cualquier pantalla sin pisar lo que esa pantalla
 * tenía dibujado — la campana puede estar abierta parada en Workflows.
 */

import { h, poner } from "./dom.js";
import { api } from "./api.js";
import { abrirModal, confirmar } from "./components/modal.js";
import { aviso } from "./components/aviso.js";

// Los dos componentes que se actualizan por release, con lo que hace falta
// para armar el texto de cada pantalla. Vive acá y no en `views/config.js`
// para que tanto esa vista como `components/notificaciones.js` lo lean del
// mismo lugar — un componente no importa de una vista, así que si viviera
// allá la campana no podría usarlo sin invertir esa dependencia.
export const COMPONENTES_UPDATE = [
  { id: "core", titulo: "NÚCLEO", label: "Núcleo", carpeta: "backend/", que: "el núcleo", de: "del núcleo" },
  { id: "webapp", titulo: "WEB APP", label: "Web app", carpeta: "webapp/", que: "la web app", de: "de la web app" },
];

/**
 * @param {object} c  {id, que, carpeta} — un elemento de `COMPONENTES_UPDATE`
 * @param {object} origen  {tag} o {archivo} (subida sin internet)
 * @param {object} opciones  {boton: el que disparó, para deshabilitarlo mientras corre;
 *                            alTerminar: qué hacer después de "Más tarde" o de aplicar sin reinicio}
 */
export async function instalarRelease(c, { tag, archivo }, { boton, alTerminar } = {}) {
  const etiqueta = tag || (archivo && archivo.name);
  confirmar({
    titulo: `Actualizar ${c.que} a ${etiqueta}`,
    texto: `Se reemplaza ${c.carpeta} entero; el actual queda guardado al lado para poder volver. Ningún run puede estar corriendo mientras se aplica, y después hay que reiniciar la app.`,
    botonTexto: "Actualizar",
    alConfirmar: async () => {
      if (boton) { boton.disabled = true; boton.textContent = "Validando…"; }
      try {
        const r = archivo ? await api.instalarReleaseArchivo(c.id, archivo, tag || "") : await api.instalarRelease(c.id, tag);
        mostrarResultadoUpdate(c, r, alTerminar);
      } catch (e) {
        abrirModal({
          titulo: "No se aplicó",
          sub: e.message,
          cuerpo: h("pre", { class: "mono", style: { margin: "12px 16px", whiteSpace: "pre-wrap", fontSize: "11.5px" }, text: (e.errores || []).join("\n") || "Sin más detalle." }),
          acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => { document.querySelector(".velo")?.remove(); } })],
        });
        if (boton) { boton.disabled = false; boton.textContent = "Instalar"; }
      }
    },
  });
}

/**
 * El modal de "se aplicó, falta reiniciar". Aparte de `instalarRelease` de
 * arriba porque `revertirComponente` (volver al anterior) también termina
 * acá sin haber pasado por el confirm-y-aplicar: ya se aplicó al llamar.
 */
export function mostrarResultadoUpdate(c, r, alTerminar) {
  const que = c.que.charAt(0).toUpperCase() + c.que.slice(1);
  const cuerpo = h("div", { style: { padding: "12px 16px", fontSize: "12.5px", lineHeight: "1.55" } }, [
    h("div", {}, [`${que} `, h("span", { class: "mono", text: r.applied.tag }), r.core_version ? ` (versión ${r.core_version})` : "", ` copiado en ${c.carpeta}. El anterior quedó guardado al lado.`]),
    r.new_requirements && r.new_requirements.length
      ? aviso("falta", "Pide dependencias que el actual no tenía", h("div", { class: "mono", style: { fontSize: "11.5px" }, text: r.new_requirements.join("\n") }))
      : null,
    h("div", { style: { marginTop: "8px" } }, [
      r.can_restart
        ? "Python ya tiene cargado el código viejo: hasta reiniciar sigue corriendo ese. Reiniciar corta la app unos segundos."
        : "Python ya tiene cargado el código viejo: hay que reiniciar el proceso a mano para que corra el nuevo.",
    ]),
  ]);
  const { cerrar } = abrirModal({
    titulo: "Actualización aplicada",
    sub: "Falta reiniciar.",
    cuerpo,
    acciones: [
      h("button", { class: "btn", text: "Más tarde", onClick: () => { cerrar(); if (alTerminar) alTerminar(); } }),
      r.can_restart ? h("button", { class: "btn btn--primario", text: "Reiniciar ahora", onClick: () => { cerrar(); reiniciarApp(); } }) : null,
    ].filter(Boolean),
  });
}

/**
 * Pide el reinicio y espera a que el servidor vuelva, en un overlay propio
 * — no en `shell.vista`, que puede ser la pantalla de cualquier otra
 * pestaña si esto lo disparó la campana. Termina recargando la página
 * entera en Config → Actualizaciones.
 */
export async function reiniciarApp() {
  const overlay = h("div", { class: "reinicio-overlay" }, [
    h("div", { class: "cargando", text: "Reiniciando… la app vuelve sola en unos segundos." }),
  ]);
  document.body.appendChild(overlay);
  try { await api.reiniciar(); } catch (e) { /* la conexión se corta justo al reiniciar: es lo esperado */ }
  const espera = (ms) => new Promise((r) => setTimeout(r, ms));
  await espera(1500);
  for (let i = 0; i < 40; i++) {
    try {
      await api.actualizaciones();
      location.hash = "#/config/actualizaciones";
      location.reload();
      return;
    } catch { await espera(1000); }
  }
  poner(overlay, aviso("error", "La app no volvió",
    "Si no levanta con lo nuevo, desde una consola en la carpeta del programa: python -m webapp --revertir-nucleo (o --revertir-webapp), y arrancarla de nuevo."));
}

/** Un modal. Se cierra con Escape o clic en el velo, como espera cualquiera. */

import { h, poner } from "../dom.js";

/**
 * @param {object} opciones {titulo, sub, cuerpo, acciones, alCerrar}
 * @returns {{cerrar: fn, cuerpo: HTMLElement}}
 */
export function abrirModal({ titulo, sub, cuerpo, acciones = [], izquierda = null, alCerrar }) {
  const contenido = h("div", { class: "modal__cuerpo" }, [cuerpo]);

  const caja = h("div", { class: "modal", onClick: (e) => e.stopPropagation() }, [
    h("div", { class: "modal__cabecera" }, [
      h("div", { class: "modal__titulo", text: titulo }),
      sub ? h("div", { class: "modal__sub", text: sub }) : null,
    ]),
    contenido,
    h("div", { class: "modal__pie" }, [
      h("div", {}, [izquierda]),
      h("div", { style: { display: "flex", gap: "8px" } }, acciones),
    ]),
  ]);

  const velo = h("div", { class: "velo", onClick: () => cerrar() }, [caja]);

  function alTeclear(e) {
    if (e.key === "Escape") cerrar();
  }

  function cerrar() {
    document.removeEventListener("keydown", alTeclear);
    velo.remove();
    if (alCerrar) alCerrar();
  }

  document.addEventListener("keydown", alTeclear);
  document.body.appendChild(velo);
  return { cerrar, cuerpo: contenido };
}

/** Confirmación para lo que no se puede deshacer. */
export function confirmar({ titulo, texto, botonTexto = "Eliminar", alConfirmar }) {
  const { cerrar } = abrirModal({
    titulo,
    cuerpo: h("div", { style: { padding: "16px", fontSize: "12.5px", lineHeight: "1.6" }, text: texto }),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      h("button", {
        class: "btn btn--rojo", text: botonTexto,
        onClick: async () => { cerrar(); await alConfirmar(); },
      }),
    ],
  });
}

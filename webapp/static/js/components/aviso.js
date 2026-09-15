/** Un aviso con icono. El mismo componente para ok, falta, error e info. */

import { h, icono, ICONOS } from "../dom.js";

const ICONO = { ok: ICONOS.ok, falta: ICONOS.alerta, error: ICONOS.error, info: ICONOS.info };

export function aviso(tono, titulo, cuerpo) {
  return h("div", { class: `aviso aviso--${tono}` }, [
    h("span", { class: "aviso__icono" }, [icono(ICONO[tono] || ICONOS.info, 15)]),
    h("div", { class: "aviso__cuerpo" }, [
      titulo ? h("div", { class: "aviso__titulo", text: titulo }) : null,
      typeof cuerpo === "string" ? h("div", { text: cuerpo }) : cuerpo,
    ]),
  ]);
}

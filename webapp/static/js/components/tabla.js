/**
 * Una tabla. La misma para la grilla de casos, las colecciones de un plugin y
 * el visor de la base: cambian las columnas y las filas, no el componente.
 *
 * Se dibuja con divs y no con `<table>` porque las columnas fijas contra el
 * borde derecho (las del bot en la grilla de casos) necesitan `position:
 * sticky`, y en una celda de tabla no funciona igual en todos lados.
 */

import { h, poner } from "../dom.js";

/**
 * `fijas` es la cantidad de columnas, contadas desde el final, que quedan
 * pegadas al borde derecho al scrollear horizontalmente.
 *
 * Van **todas juntas dentro de un único contenedor** con `position: sticky`,
 * no cada una por su cuenta: cinco `sticky` vecinos, cada uno con su propio
 * `right` calculado a mano, dependen de que los cinco redondeen al mismo
 * subpíxel para no dejar una costura — y alguna vez no lo hacían, y por esa
 * costura se veía la columna de atrás. Un solo contenedor sticky no tiene con
 * qué desalinearse contra sí mismo.
 *
 * @param {Array} columnas  [{clave, label, ancho, mono, peso, envuelve, filtro, render}]
 * @param {Array} filas     objetos
 * `conFiltros` agrega una segunda fila de cabecera con el `filtro` de cada
 * columna. Va pegada a la cabecera y no en una barra aparte para que el input
 * quede debajo de la columna que filtra: en una barra hay que leer la etiqueta
 * para saber qué filtra cada cosa.
 *
 * @param {object} opciones {vacio: string|Node, alClic: fn(fila), clase, conFiltros, fijas}
 */
export function tabla(columnas, filas, {
  vacio = "No hay nada todavía.", alClic, clase = "tabla", conFiltros = false, fijas = 0,
} = {}) {
  const envuelveAlguna = columnas.some((c) => c.envuelve);
  const libres = fijas ? columnas.slice(0, -fijas) : columnas;
  const pegadas = fijas ? columnas.slice(-fijas) : [];

  const celda = (col, contenido, extra = {}) => {
    const estilo = col.ancho
      ? { flex: `0 0 ${col.ancho}`, width: col.ancho }
      : { flex: "1", minWidth: "0" };
    if (col.mono) estilo.fontFamily = "var(--mono)";
    if (col.peso) estilo.fontWeight = col.peso;
    const clases = "tabla__celda" + (col.envuelve ? " tabla__celda--envuelve" : "");
    return h("div", { class: clases, style: { ...estilo, ...extra } }, [contenido]);
  };

  /** El grupo pegado de una fila: una sola caja sticky, no una por columna. */
  const grupoFijo = (variante, celdas) => pegadas.length
    ? [h("div", { class: `tabla__grupo-fijo ${variante}` }, celdas)]
    : [];

  const fila = (variante, celdasLibres, celdasFijas) =>
    [...celdasLibres, ...grupoFijo(variante, celdasFijas)];

  const cabecera = h("div", { class: "tabla__fila tabla__fila--cabecera" }, fila(
    "tabla__grupo-fijo--cabecera",
    libres.map((col) => celda({ ...col, mono: false, peso: null }, col.label ?? col.clave)),
    pegadas.map((col) => celda({ ...col, mono: false, peso: null }, col.label ?? col.clave)),
  ));

  const filaFiltros = conFiltros
    ? h("div", { class: "tabla__fila tabla__fila--filtros" }, fila(
        "tabla__grupo-fijo--filtros",
        libres.map((col) => celda({ ...col, mono: false, peso: null }, col.filtro || null)),
        pegadas.map((col) => celda({ ...col, mono: false, peso: null }, col.filtro || null)),
      ))
    : null;

  // Las dos filas de arriba van adentro de una sola caja `sticky`, no pegadas
  // uma por una: cuando cada una se pegaba sola, la de filtros necesitaba un
  // `top` igual al alto de la cabecera —un número escrito a mano— y bastaba
  // que la cabecera midiera un pixel distinto para que quedaran encimadas o
  // separadas. Una sola caja se pega entera y las dos se mueven juntas por
  // definición.
  const cabeza = h("div", { class: "tabla__cabeza" }, [cabecera, filaFiltros].filter(Boolean));

  const cuerpo = filas.length
    ? filas.map((f, i) => {
        const variante = i % 2 ? "tabla__grupo-fijo--par" : "tabla__grupo-fijo--impar";
        const celdaDe = (col) => {
          const contenido = col.render ? col.render(f) : String(f[col.clave] ?? "—");
          const apagado = contenido === "—" ? { color: "var(--texto-4)" } : {};
          return celda(col, contenido, apagado);
        };
        return h("div", {
          class: "tabla__fila" + (i % 2 ? " tabla__fila--par" : "") + (envuelveAlguna ? " tabla__fila--alto" : ""),
          style: alClic ? { cursor: "pointer" } : null,
          onClick: alClic ? () => alClic(f) : null,
        }, fila(variante, libres.map(celdaDe), pegadas.map(celdaDe)));
      })
    : [h("div", { class: "tabla__vacia" }, [vacio])];

  return h("div", { class: clase }, [cabeza, ...cuerpo]);
}

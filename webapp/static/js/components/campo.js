/**
 * Un campo dibujado desde el esquema que declara el plugin.
 *
 * Sirve igual para un `Setting` (por instalación) y para un `Field` de una
 * colección (por item): los dos traen tipo, etiqueta, si es obligatorio, sus
 * opciones y su ayuda. Ninguna pantalla conoce un plugin por nombre — si hace
 * falta tocar este archivo para que un plugin nuevo se vea bien, algo se
 * declaró en el lugar equivocado.
 */

import { h, poner } from "../dom.js";
import { crearEditorDeCodigo } from "./editor-codigo.js";

// Para que cada `<datalist>` tenga su id sin que nadie lo invente a mano.
let _seqOpciones = 0;

/** Los siete tipos de `ParamType`. Cualquier otro cae en texto. */
function control(esq, valor, alCambiar) {
  // `placeholder` es el ejemplo del valor que el manifest declara para mostrar
  // adentro del campo vacío (core#29): explica cómo se escribe, no qué es —eso
  // es `doc`, que va abajo—. Hasta que el núcleo lo publique llega vacío y no
  // se dibuja nada, que es lo mismo que hoy.
  const comun = { class: "entrada", onInput: alCambiar, placeholder: esq.placeholder || "" };

  // Un param que declara de qué colección salen sus valores (`options_from`,
  // core#27): texto con buscador, **no** un `<select>`. La lista es una ayuda
  // para no tener que acordarse del nombre exacto, no una lista cerrada — el
  // valor puede ser una `{variable}` que recién se resuelve al correr, y por
  // eso el núcleo declara `options_from` como informativo y no lo valida.
  // Quién sabe traer los valores es quien arma el campo; sin eso, texto pelado.
  if (esq.options_from && esq.opciones) {
    const lista = h("datalist", { id: `opciones-${++_seqOpciones}` });
    const entrada = h("input", {
      ...comun, type: "text", list: lista.id, value: valor ?? esq.default ?? "",
      placeholder: `escribí, o elegí de ${esq.options_from}`,
    });
    Promise.resolve(esq.opciones())
      .then((valores) => poner(lista, ...(valores || []).map((v) => h("option", { value: v }))))
      // Que no se pueda traer la lista no puede dejar el campo sin usar: sigue
      // siendo un texto, que es lo que era antes de esto.
      .catch(() => {});
    return h("div", {}, [entrada, lista]);
  }

  if (esq.type === "enum" && (esq.choices || []).length) {
    const sel = h("select", { class: "selector", onChange: alCambiar },
      (esq.required ? esq.choices : ["", ...esq.choices]).map((op) =>
        h("option", { value: op, text: op === "" ? "—" : op })));
    sel.value = valor ?? esq.default ?? "";
    return sel;
  }

  if (esq.type === "bool") {
    const chk = h("input", { type: "checkbox", checked: !!(valor ?? esq.default), onChange: alCambiar });
    return h("label", { class: "fila-control", style: { cursor: "pointer" } },
      [chk, h("span", { style: { fontSize: "12.5px" }, text: esq.doc_corto || "Sí" })]);
  }

  if (esq.type === "json") {
    // El front no conoce la forma de adentro: el tipo declarado es `json`, así
    // que se edita como JSON. Quien conoce la forma es el plugin, y la explica
    // en su ayuda. Con números de línea porque un payload de diez claves sin
    // ellos es puro conteo a ojo para encontrar el error que tira el parser.
    const texto = valor === undefined || valor === null
      ? JSON.stringify(esq.default ?? {}, null, 2)
      : JSON.stringify(valor, null, 2);
    const { elemento } = crearEditorDeCodigo(texto, { onCambiar: alCambiar });
    return elemento;
  }

  if (esq.type === "int" || esq.type === "float") {
    return h("input", { ...comun, class: "entrada entrada--corta entrada--mono", type: "number",
                        step: esq.type === "int" ? "1" : "any",
                        value: valor ?? esq.default ?? "" });
  }

  if (esq.secret) {
    // Un secreto no se muestra nunca, ni siquiera a quien lo cargó: si ya tiene
    // valor, el campo queda vacío y escribir algo lo reemplaza.
    return h("input", { ...comun, type: "password", autocomplete: "new-password",
                        placeholder: valor ? "configurado — escribí para reemplazarlo" : "" });
  }

  if (esq.multiline) {
    return h("textarea", { class: "entrada entrada--area", onInput: alCambiar, value: valor ?? esq.default ?? "",
                           placeholder: esq.placeholder || "" });
  }

  const claseExtra = esq.type === "path" ? " entrada--mono" : "";
  return h("input", { ...comun, class: "entrada" + claseExtra, type: "text",
                      value: valor ?? esq.default ?? "" });
}

/**
 * @param {object} esq   entrada del catálogo (Setting o Field)
 * @param {*} valor      valor actual, o undefined
 * @param {object} opciones  {falta: boolean, alCambiar: fn}
 * @returns {{clave: string, elemento: HTMLElement, leer: () => *}}
 */
export function crearCampo(esq, valor, { falta = false, alCambiar = () => {} } = {}) {
  const clave = esq.key || esq.name;
  const ctl = control(esq, valor, alCambiar);
  // El control es el propio input/textarea/select casi siempre; un checkbox
  // viene envuelto en su <label> y el editor de código en su columna de
  // números — en los dos casos hay que buscar el elemento que de verdad
  // guarda el valor.
  const entrada = /^(input|textarea|select)$/i.test(ctl.tagName)
    ? ctl
    : ctl.querySelector("input, textarea, select");

  const ayuda = esq.doc ? h("div", { class: "campo__ayuda", text: esq.doc }) : null;
  const alerta = falta
    ? h("div", { class: "campo__error",
                 text: "Sin valor configurado — el plugin no puede trabajar hasta que lo completes." })
    : null;
  if (falta && entrada.classList) entrada.classList.add("entrada--falta");

  const elemento = h("div", { class: "campo" + (falta ? " campo--falta" : "") }, [
    h("div", { class: "campo__etiqueta" }, [
      h("div", { class: "campo__nombre" }, [
        esq.label || clave,
        esq.required ? h("span", { class: "requerido", text: " *" }) : null,
      ]),
      h("div", { class: "campo__clave", text: `${clave} · ${esq.type}` }),
    ]),
    h("div", { class: "campo__control" }, [ctl, ayuda, alerta]),
  ]);

  /** Devuelve el valor tipado. Lanza si el JSON está roto. */
  function leer() {
    if (esq.type === "bool") return entrada.checked;
    const crudo = entrada.value;

    if (esq.type === "json") {
      if (!crudo.trim()) return esq.default ?? null;
      try {
        return JSON.parse(crudo);
      } catch (e) {
        throw new Error(`${esq.label || clave}: el JSON no es válido (${e.message})`);
      }
    }
    if (esq.type === "int" || esq.type === "float") {
      if (crudo === "") return null;
      const n = Number(crudo);
      if (Number.isNaN(n)) throw new Error(`${esq.label || clave}: no es un número`);
      return esq.type === "int" ? Math.trunc(n) : n;
    }
    // El valor no se trimea: el DSL preserva sufijos con espacios a propósito.
    return crudo;
  }

  return { clave, elemento, leer, esquema: esq };
}

/**
 * Un formulario entero desde una lista de esquemas.
 * @returns {{elemento: HTMLElement, leer: () => object, campos: Array}}
 */
export function crearFormulario(esquemas, valores = {}, { faltantes = [] } = {}) {
  const campos = esquemas.map((esq) => {
    const clave = esq.key || esq.name;
    return crearCampo(esq, valores[clave], { falta: faltantes.includes(clave) });
  });
  return {
    elemento: h("div", {}, campos.map((c) => c.elemento)),
    campos,
    /** Lee todo. Si un campo está mal, lanza con su mensaje. */
    leer() {
      const salida = {};
      for (const campo of campos) salida[campo.clave] = campo.leer();
      return salida;
    },
  };
}

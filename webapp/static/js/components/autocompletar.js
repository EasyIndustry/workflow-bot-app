/**
 * Autocompletado de `{variables}` en un campo de texto.
 *
 * Al tipear `{` en un input o textarea se abre una lista pegada al campo con
 * las variables que ese nodo puede usar, y al elegir una se escribe `{nombre}`
 * entero, con la llave de cierre. Existe porque hasta acá había que
 * acordarse de memoria el nombre exacto de cada salida: el helper de la
 * tarjeta las lista, pero abajo de todo y sin decir cuál va a valer cuando dos
 * nodos anteriores dejan la misma. Cada opción dice de qué nodo viene.
 *
 * No usa `<datalist>` a propósito: ése completa el valor entero del campo, y
 * lo que hace falta es completar en el medio de `C:\salida\{inten…}.pdf`. Es
 * un componente propio, sin dependencias, con las teclas de cualquier editor:
 * flechas, Enter o Tab para insertar, Esc para cerrar. El valor guardado sigue
 * siendo texto plano con sus llaves: el componente sólo escribe en el campo y
 * dispara `input`, así que quien escucha el campo no nota la diferencia.
 *
 * Quién sabe qué variables hay es quien arma el campo (la tarjeta del flujo):
 * se le pasa una función que devuelve la lista, y se llama al abrir, así que
 * refleja el grafo tal como está en ese momento.
 */

import { h } from "../dom.js";

/** Cuántas opciones se muestran a la vez; con más, el filtro es el camino. */
const MAXIMO = 12;

// Un único desplegable para toda la página: dos campos no pueden estar
// escribiendo a la vez, y así no queda uno abierto por cada tarjeta dibujada.
let abierto = null;

function cerrarAbierto() {
  if (abierto) {
    abierto.cerrar();
    abierto = null;
  }
}

/**
 * Lo que está a la izquierda del cursor que parece una variable a medio
 * escribir: `{`, `{ru`, `{MOVER.ru`. Null si el cursor no está adentro de una.
 */
function variableEnCurso(texto, cursor) {
  const antes = texto.slice(0, cursor);
  const m = /\{([\w.]*)$/.exec(antes);
  return m ? { desde: cursor - m[0].length, prefijo: m[1] } : null;
}

function filtrar(opciones, prefijo) {
  const p = prefijo.toLowerCase();
  const empiezan = [];
  const contienen = [];
  for (const o of opciones) {
    const n = o.nombre.toLowerCase();
    if (!p || n.startsWith(p)) empiezan.push(o);
    else if (n.includes(p)) contienen.push(o);
  }
  return [...empiezan, ...contienen].slice(0, MAXIMO);
}

/**
 * @param {HTMLInputElement|HTMLTextAreaElement} campo
 * @param {() => Array<{nombre: string, detalle?: string}>|Promise} obtenerOpciones
 *   `nombre` es lo que va entre llaves (`ruta`, `env.CLAVE`); `detalle` es de
 *   dónde sale, para leerlo al lado ("la deja Mover PDF").
 */
export function autocompletar(campo, obtenerOpciones) {
  let lista = null;      // el <div> del desplegable, o null si está cerrado
  let visibles = [];     // las opciones dibujadas, en orden
  let elegida = 0;
  let enCurso = null;    // {desde, prefijo} de la variable que se está escribiendo

  const cerrar = () => {
    if (lista) lista.remove();
    lista = null;
    visibles = [];
    if (abierto && abierto.campo === campo) abierto = null;
  };

  const insertar = (opcion) => {
    if (!enCurso) return;
    const valor = campo.value;
    const cursor = campo.selectionStart;
    const texto = `{${opcion.nombre}}`;
    campo.value = valor.slice(0, enCurso.desde) + texto + valor.slice(cursor);
    const fin = enCurso.desde + texto.length;
    campo.setSelectionRange(fin, fin);
    cerrar();
    // Quien guarda el valor escucha `input`: así no hay dos caminos de guardado.
    campo.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const ubicar = () => {
    // Pegado debajo del campo, en coordenadas de la página: el campo puede
    // estar adentro de una caja con scroll y overflow oculto (la pila de
    // tarjetas, el panel flotante del diagrama), y un hijo absoluto quedaría
    // recortado. Fijo a la ventana, se cierra si algo scrollea.
    const r = campo.getBoundingClientRect();
    Object.assign(lista.style, {
      position: "fixed", left: `${Math.round(r.left)}px`, top: `${Math.round(r.bottom + 2)}px`,
      minWidth: `${Math.round(Math.min(Math.max(r.width, 260), window.innerWidth - r.left - 8))}px`,
    });
  };

  const dibujar = () => {
    lista.replaceChildren(...visibles.map((o, i) =>
      h("div", {
        class: "autocompletar__opcion" + (i === elegida ? " autocompletar__opcion--elegida" : ""),
        // mousedown y no click: el click llega después del blur del campo, que
        // ya cerró la lista. preventDefault mantiene el foco donde estaba.
        onMousedown: (e) => { e.preventDefault(); insertar(o); },
        onMousemove: () => { if (elegida !== i) { elegida = i; dibujar(); } },
      }, [
        h("span", { class: "autocompletar__nombre mono", text: `{${o.nombre}}` }),
        o.detalle ? h("span", { class: "autocompletar__detalle", text: o.detalle }) : null,
      ])));
    const activa = lista.children[elegida];
    if (activa && activa.scrollIntoView) activa.scrollIntoView({ block: "nearest" });
  };

  const abrir = async () => {
    enCurso = variableEnCurso(campo.value, campo.selectionStart);
    if (!enCurso) { cerrar(); return; }
    let opciones;
    try {
      opciones = await Promise.resolve(obtenerOpciones());
    } catch {
      opciones = [];
    }
    // Mientras se esperaba la lista el cursor pudo moverse o el campo perder el foco.
    enCurso = variableEnCurso(campo.value, campo.selectionStart);
    if (!enCurso || document.activeElement !== campo) { cerrar(); return; }
    visibles = filtrar(opciones || [], enCurso.prefijo);
    if (!visibles.length) { cerrar(); return; }
    elegida = 0;
    if (!lista) {
      cerrarAbierto();
      lista = h("div", { class: "autocompletar", role: "listbox" });
      document.body.appendChild(lista);
      abierto = { campo, cerrar };
    }
    ubicar();
    dibujar();
  };

  campo.addEventListener("input", abrir);
  campo.addEventListener("click", () => { if (lista) abrir(); });
  campo.addEventListener("blur", cerrar);
  campo.addEventListener("keydown", (e) => {
    if (!lista) return;
    if (e.key === "ArrowDown") { elegida = (elegida + 1) % visibles.length; dibujar(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { elegida = (elegida - 1 + visibles.length) % visibles.length; dibujar(); e.preventDefault(); }
    else if (e.key === "Enter" || e.key === "Tab") { insertar(visibles[elegida]); e.preventDefault(); }
    else if (e.key === "Escape") { cerrar(); e.preventDefault(); e.stopPropagation(); }
  });

  return { cerrar };
}

// Cualquier scroll o cambio de tamaño desubica la lista fija: mejor cerrada que flotando lejos del campo.
window.addEventListener("scroll", cerrarAbierto, true);
window.addEventListener("resize", cerrarAbierto);

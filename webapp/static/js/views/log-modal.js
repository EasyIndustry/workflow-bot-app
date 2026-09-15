/**
 * El modal del registro de eventos de una fila.
 *
 * Es la pantalla que más se usa en el día a día: el botón **Log** de una fila
 * abre todo lo que le pasó a esa fila, run tras run, y desde acá se copia o se
 * limpia. La app vieja lo tenía y funcionaba; se mantiene el comportamiento
 * —ver, copiar, limpiar, cerrar— y cambia sólo de dónde salen los datos.
 *
 * Lo que cambió por debajo: antes el registro vivía en `localStorage` del
 * navegador, se reescribía entero en cada línea, y se perdía al limpiar el
 * navegador o al abrir la app en otra máquina. Ahora es una tabla en la base, y
 * el navegador sólo lo lee.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api } from "../api.js";
import { abrirModal, confirmar } from "../components/modal.js";

const NIVEL = {
  error: { color: "var(--rojo)", fondo: "var(--rojo-fondo)" },
  warning: { color: "var(--ambar)", fondo: "var(--ambar-fondo)" },
  info: { color: "var(--texto)", fondo: "transparent" },
};

/**
 * @param {string} caseId
 * @param {object} opts {alLimpiar: fn()} — para que la grilla actualice el contador
 */
export function abrirLog(caseId, { alLimpiar } = {}) {
  const visor = h("div", {
    class: "visor-log",
    // Se pone en foco para que las flechas y Page Down scrolleen sin tener que
    // hacer clic adentro primero.
    tabindex: "0",
  }, [h("div", { class: "tabla__vacia", text: "Cargando el registro…" })]);

  const pie = h("span", { style: { fontSize: "11.5px", color: "var(--texto-3)" } });
  let entradas = [];

  const botonCopiar = h("button", { class: "btn", text: "Copiar todo", onClick: () => copiar(botonCopiar, entradas) });
  const botonLimpiar = h("button", {
    class: "btn btn--rojo", text: "Limpiar registro",
    onClick: () => limpiar(caseId, cargar, alLimpiar),
  });

  const { cerrar, cuerpo } = abrirModal({
    titulo: `Registro de eventos — ${caseId}`,
    sub: "Todo lo que le pasó a esta fila, de la corrida más vieja a la más nueva.",
    cuerpo: visor,
    izquierda: pie,
    acciones: [botonCopiar, botonLimpiar, h("button", { class: "btn btn--primario", text: "Cerrar", onClick: () => cerrar() })],
  });
  cuerpo.style.minHeight = "300px";

  async function cargar() {
    try {
      const datos = await api.log(caseId);
      entradas = datos.entries || [];
      dibujar(visor, entradas, datos);
      pie.textContent = entradas.length
        ? `${datos.total} línea${datos.total === 1 ? "" : "s"}` +
          (datos.truncated ? ` · se muestran las últimas ${entradas.length}` : "")
        : "";
      botonCopiar.disabled = !entradas.length;
      botonLimpiar.disabled = !entradas.length;
    } catch (e) {
      poner(visor, h("div", { class: "aviso aviso--error" }, [
        h("div", { class: "aviso__cuerpo" }, [
          h("div", { class: "aviso__titulo", text: "No se pudo leer el registro" }),
          h("div", { text: e.message }),
        ]),
      ]));
    }
  }

  cargar();
  return { cerrar, recargar: cargar };
}

function dibujar(visor, entradas, datos) {
  if (!entradas.length) {
    poner(visor, h("div", { class: "tabla__vacia" }, [
      "Sin eventos registrados.",
      h("div", { style: { marginTop: "6px", fontSize: "11.5px" }, text:
        "Esta fila todavía no se ejecutó, o su registro se limpió." }),
    ]));
    return;
  }

  // Se agrupa por run: sin la separación, veinte líneas de tres corridas
  // distintas se leen como una sola y no se ve dónde empezó el reintento.
  const bloques = [];
  let actual = null;
  for (const entrada of entradas) {
    if (!actual || actual.run_id !== entrada.run_id) {
      actual = { run_id: entrada.run_id, flow: entrada.flow, ts: entrada.ts, lineas: [] };
      bloques.push(actual);
    }
    actual.lineas.push(entrada);
  }

  poner(visor, ...bloques.map((bloque) => h("div", {}, [
    h("div", { class: "log__separador" }, [
      h("span", { class: "mono", text: bloque.flow || "(sin flujo)" }),
      h("span", { style: { color: "var(--texto-4)" }, text: fecha(bloque.ts) }),
      h("span", { class: "mono", style: { color: "var(--texto-4)", marginLeft: "auto" },
                  text: bloque.run_id.slice(0, 8) }),
    ]),
    ...bloque.lineas.map(linea),
  ])));

  // Al final, que es donde está lo que pasó último.
  visor.scrollTop = visor.scrollHeight;
}

function linea(entrada) {
  const nivel = NIVEL[entrada.level] || NIVEL.info;
  return h("div", {
    class: "log__linea",
    style: { color: nivel.color, background: nivel.fondo },
  }, [
    h("span", { class: "log__hora", text: entrada.t || hora(entrada.ts) }),
    entrada.node_id
      ? h("span", { class: "log__nodo", text: entrada.node_id })
      : h("span", { class: "log__nodo" }),
    h("span", { class: "log__mensaje", text: entrada.message }),
  ]);
}

function hora(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0")).join(":");
}

function fecha(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const hoy = new Date();
  const mismoDia = d.toDateString() === hoy.toDateString();
  return mismoDia ? `hoy ${hora(ts)}` : `${d.getDate()}/${d.getMonth() + 1} ${hora(ts)}`;
}

/**
 * Copia el registro como texto plano.
 *
 * El mismo formato que la app vieja —`[hora] NIVEL: mensaje`— porque es lo que
 * la gente pega en un ticket o en un chat, y cambiarlo rompería la costumbre sin
 * ganar nada.
 */
async function copiar(boton, entradas) {
  const texto = entradas
    .map((e) => `[${e.t || hora(e.ts)}] ${(e.level || "info").toUpperCase()}: ${e.message}`)
    .join("\n");

  const original = boton.textContent;
  try {
    await navigator.clipboard.writeText(texto);
    boton.textContent = "✓ Copiado";
  } catch {
    // Sin permiso de portapapeles —o sin HTTPS en algunos navegadores— se cae a
    // seleccionar el texto, que es peor pero funciona en todos lados.
    const area = h("textarea", { value: texto, style: { position: "fixed", top: "-1000px" } });
    document.body.appendChild(area);
    area.select();
    boton.textContent = document.execCommand("copy") ? "✓ Copiado" : "No se pudo copiar";
    area.remove();
  }
  setTimeout(() => { boton.textContent = original; }, 1500);
}

function limpiar(caseId, recargar, alLimpiar) {
  confirmar({
    titulo: `Limpiar el registro de ${caseId}`,
    texto:
      "Se borran las líneas del registro de esta fila. El historial de " +
      "ejecuciones no se toca: cada run sigue guardado con su traza completa, " +
      "así que la evidencia de un fallo no se pierde.",
    botonTexto: "Limpiar",
    alConfirmar: async () => {
      await api.limpiarLog(caseId);
      await recargar();
      if (alLimpiar) alLimpiar();
    },
  });
}

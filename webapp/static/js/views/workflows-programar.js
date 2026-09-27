/**
 * Programar un flujo: que corra solo, cada cierto tiempo o a una hora (#11).
 *
 * Va en su propio modal y no en Propiedades a propósito: Propiedades edita la
 * cabecera del archivo y se aplica recién con "Guardar", y la programación
 * vive en la base de la instalación (`webapp/programaciones.py`) y se guarda
 * en el acto. Mezclarlas haría que "Aplicar" pareciera programar algo que en
 * realidad espera a otro botón.
 *
 * El programador corre del lado del servidor: el navegador puede estar
 * cerrado. Esta pantalla sólo configura y muestra qué pasó.
 */

import { h, poner } from "../dom.js";
import { api } from "../api.js";
import { abrirModal } from "../components/modal.js";
import { aviso } from "../components/aviso.js";

const DIAS = [["lun", "Lu"], ["mar", "Ma"], ["mie", "Mi"], ["jue", "Ju"], ["vie", "Vi"], ["sab", "Sá"], ["dom", "Do"]];

function fecha(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("es-AR", {
    weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function campo(nombre, control, ayuda) {
  return h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: nombre })]),
    h("div", { class: "campo__control" }, [control, ayuda ? h("div", { class: "campo__ayuda", text: ayuda }) : null]),
  ]);
}

/** Lo que pasó con la programación: próxima, última, resultado, salteadas. */
function panelDeEstado(p) {
  const e = (p && p.estado) || {};
  if (!p) return null;
  const clase = e.resultado === "err" ? "badge badge--error"
    : e.resultado === "ok" ? "badge badge--ok" : "badge";
  const filas = [
    ["Cuándo", p.descripcion + (p.activa === false ? " · en pausa" : "")],
    ["Próxima", p.activa === false ? "— (en pausa)" : fecha(e.proxima)],
    ["Última", fecha(e.ultima)],
    ["Corridas", String(e.corridas || 0) + (e.salteadas ? ` · ${e.salteadas} salteada${e.salteadas === 1 ? "" : "s"} (la anterior seguía)` : "")],
  ];
  return h("div", { style: { padding: "10px 13px", borderBottom: "1px solid var(--borde)", fontSize: "12px" } }, [
    ...filas.map(([k, v]) => h("div", { style: { display: "flex", gap: "10px", lineHeight: "1.7" } }, [
      h("span", { style: { color: "var(--texto-3)", minWidth: "70px" }, text: k }), h("span", { text: v }),
    ])),
    e.resultado ? h("div", { style: { marginTop: "6px", display: "flex", gap: "8px", alignItems: "baseline" } }, [
      h("span", { class: clase, text: e.resultado }),
      h("span", { style: { color: "var(--texto-2)" }, text: e.mensaje || "" }),
    ]) : null,
  ]);
}

/**
 * Abre el modal para el flujo `nombre`. `alCambiar(p)` recibe la programación
 * guardada (o `null` si se quitó), para que la cabecera del flujo la muestre.
 */
export async function abrirProgramar(nombre, alCambiar = () => {}) {
  let actual = null;
  try {
    const { items } = await api.programaciones();
    actual = (items || []).find((p) => p.flujo === nombre) || null;
  } catch { /* sin lista, se arranca de cero y el guardar dirá qué pasa */ }

  const base = actual || { activa: true, modo: "intervalo", cada_minutos: 15, hora: "08:00", dias: "", case_id: "", fila: {}, actor: "" };

  const modo = h("select", { class: "selector" }, [
    h("option", { value: "intervalo", text: "Cada cierto tiempo" }),
    h("option", { value: "horario", text: "A una hora" }),
  ]);
  modo.value = base.modo;
  const cada = h("input", { class: "entrada", type: "number", min: "1", value: String(base.cada_minutos || 15),
                            style: { width: "90px" } });
  const hora = h("input", { class: "entrada", type: "time", value: base.hora || "08:00", style: { width: "120px" } });
  const elegidos = new Set((base.dias || "").split(",").filter(Boolean));
  const dias = DIAS.map(([clave, rotulo]) => {
    const caja = h("input", { type: "checkbox", checked: elegidos.has(clave) });
    caja.dataset.dia = clave;
    return h("label", { class: "fila-control", style: { cursor: "pointer", marginRight: "8px" } },
      [caja, h("span", { style: { fontSize: "12px" }, text: rotulo })]);
  });
  const activa = h("input", { type: "checkbox", checked: base.activa !== false });
  const caso = h("input", { class: "entrada entrada--mono", type: "text", value: base.case_id || "",
                            placeholder: `programado ${nombre}` });
  const fila = h("textarea", { class: "entrada entrada--area entrada--mono",
                               value: Object.keys(base.fila || {}).length ? JSON.stringify(base.fila, null, 2) : "",
                               placeholder: '{"id": "123"}' });

  const bloqueIntervalo = campo("Cada", h("div", { class: "fila-control" },
    [cada, h("span", { style: { fontSize: "12.5px" }, text: "minutos" })]),
    "Si la corrida anterior todavía sigue cuando toca la siguiente, se saltea y queda anotado.");
  const bloqueHorario = h("div", {}, [
    campo("Hora", hora, "La hora de esta máquina."),
    campo("Días", h("div", { style: { display: "flex", flexWrap: "wrap", gap: "4px 6px" } }, dias),
      "Sin ninguno marcado, todos los días."),
  ]);
  const mostrarModo = () => {
    bloqueIntervalo.style.display = modo.value === "intervalo" ? "" : "none";
    bloqueHorario.style.display = modo.value === "horario" ? "" : "none";
  };
  modo.addEventListener("change", mostrarModo);
  mostrarModo();

  const estado = h("div", {}, [panelDeEstado(actual)]);
  const error = h("div");

  const leer = () => {
    let valorFila = {};
    if (fila.value.trim()) {
      try { valorFila = JSON.parse(fila.value); } catch { throw new Error("La fila no es JSON válido."); }
    }
    return {
      activa: activa.checked,
      modo: modo.value,
      cada_minutos: Number(cada.value),
      hora: hora.value,
      dias: dias.map((l) => l.querySelector("input")).filter((c) => c.checked).map((c) => c.dataset.dia).join(","),
      case_id: caso.value.trim(),
      fila: valorFila,
      actor: "",
    };
  };

  const botonQuitar = h("button", {
    class: "btn", text: "Quitar programación", style: { color: "var(--rojo)", marginRight: "auto",
                                                      display: actual ? "" : "none" },
    onClick: async () => {
      try {
        await api.borrarProgramacion(nombre);
        alCambiar(null);
        cerrar();
      } catch (e) {
        poner(error, aviso("error", "No se pudo quitar", e.message));
      }
    },
  });

  const { cerrar } = abrirModal({
    titulo: `Programar "${nombre}"`,
    sub: "Corre solo, del lado del servidor, aunque no haya ninguna pantalla abierta.",
    cuerpo: h("div", {}, [
      estado,
      campo("Cuándo", modo),
      bloqueIntervalo,
      bloqueHorario,
      campo("Activa", h("label", { class: "fila-control", style: { cursor: "pointer" } },
        [activa, h("span", { style: { fontSize: "12.5px" }, text: "Correr según esta programación" })]),
        "Destildada queda en pausa, sin perder la configuración ni el historial."),
      campo("Caso", caso, "El case_id de cada corrida: con esto se las encuentra en Log. Vacío, el que se ve en gris."),
      campo("Fila", fila, "Opcional: el row con el que corre, como JSON. Vacío, corre sin fila."),
      error,
    ]),
    acciones: [
      botonQuitar,
      h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Guardar", onClick: async (ev) => {
        const boton = ev.currentTarget;
        poner(error);
        let datos;
        try { datos = leer(); } catch (e) { return poner(error, aviso("error", "Revisá los datos", e.message)); }
        boton.disabled = true;
        try {
          actual = await api.guardarProgramacion(nombre, datos);
          poner(estado, panelDeEstado(actual));
          botonQuitar.style.display = "";
          alCambiar(actual);
        } catch (e) {
          poner(error, aviso("error", "No se pudo guardar", e.message));
        } finally {
          boton.disabled = false;
        }
      } }),
    ],
  });
}


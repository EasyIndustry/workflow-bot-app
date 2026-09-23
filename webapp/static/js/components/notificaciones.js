/**
 * El botón de notificaciones del marco: avisa si hay un release nuevo del
 * núcleo o de la web app, y deja instalarlo sin ir a Config → Actualizaciones.
 *
 * Mismo patrón que el botón "Avisos" de una fuente en `views/sources.js`
 * (badge con contador, panel colgado del botón, se cierra al click afuera),
 * pero de la app entera y no de una fuente: vive en `shell.js`, en la barra
 * de pestañas, no adentro de ninguna vista.
 *
 * Se consulta **una vez**, al armar el shell — no hace polling. Si algo se
 * publicó mientras la pestaña seguía abierta, recargar alcanza, como para
 * cualquier otro dato de esta app que no tiene su propio socket; agregar un
 * intervalo hoy sería resolver un caso que todavía nadie pidió.
 *
 * Respeta la misma preferencia "incluir releases de prueba" que Config →
 * Actualizaciones (`../preferencias.js`): si está activada ahí, la campana
 * también avisa de un release de prueba nuevo, no sólo de uno final.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api } from "../api.js";
import { incluirPrueba } from "../preferencias.js";
import { primeraLinea } from "./markdown.js";
import { COMPONENTES_UPDATE, instalarRelease } from "../actualizar_componente.js";
import { alClickAfuera } from "./click-afuera.js";

export function crearNotificaciones() {
  let abiertas = false;
  let cargando = true;
  let error = null;
  // [{comp: de COMPONENTES_UPDATE, tag, prerelease, published_at, body}], sólo
  // los componentes con un release más nuevo que el instalado.
  let disponibles = [];
  let quitarClickAfuera = null;

  const contenedor = h("div", { class: "avisos" });

  function redibujar() {
    poner(contenedor, dibujar());
    if (quitarClickAfuera) { quitarClickAfuera(); quitarClickAfuera = null; }
    if (abiertas) {
      quitarClickAfuera = alClickAfuera(contenedor, () => { abiertas = false; redibujar(); });
    }
  }

  function dibujar() {
    const boton = h("button", {
      class: "btn" + (disponibles.length ? " btn--con-avisos" : ""),
      title: cargando
        ? "Buscando actualizaciones…"
        : (disponibles.length
          ? `Hay ${disponibles.length} actualización${disponibles.length === 1 ? "" : "es"} disponible${disponibles.length === 1 ? "" : "s"}`
          : "No hay actualizaciones nuevas"),
      onClick: () => { abiertas = !abiertas; redibujar(); },
    }, [
      icono(ICONOS.campana, 13, 2),
      disponibles.length ? h("span", { class: "badge badge--falta", text: String(disponibles.length) }) : null,
    ]);

    return [boton, abiertas ? panel() : null];
  }

  function panel() {
    return h("div", { class: "avisos__panel" }, [
      h("div", { class: "avisos__cabecera" }, [
        h("span", { text: "Actualizaciones" }),
        h("div", { style: { flex: "1" } }),
        h("button", { class: "btn btn--chico", title: "Cerrar", onClick: () => { abiertas = false; redibujar(); } },
          [icono(ICONOS.cerrar, 11, 2)]),
      ]),
      error
        ? h("div", { class: "avisos__lista", style: { padding: "10px", fontSize: "11.5px", color: "var(--texto-3)" }, text: error })
        : cuerpoPanel(),
    ]);
  }

  function cuerpoPanel() {
    if (cargando) return h("div", { class: "avisos__lista", style: { padding: "10px" } }, [
      h("div", { class: "cargando", style: { padding: "10px" }, text: "Buscando…" }),
    ]);
    if (!disponibles.length) return h("div", { class: "avisos__lista", style: { padding: "10px", fontSize: "11.5px", color: "var(--texto-3)" } }, [
      "Todo al día — ",
      h("a", { href: "#/config/actualizaciones", onClick: () => { abiertas = false; redibujar(); }, text: "Config → Actualizaciones" }),
      " para revisar a mano.",
    ]);
    return h("div", { class: "avisos__lista" }, disponibles.map(filaDisponible));
  }

  function filaDisponible(d) {
    const boton = h("button", {
      class: "btn btn--chico btn--primario", text: "Instalar",
      // No cierra el panel acá: `instalarRelease` va a deshabilitar este
      // mismo botón y escribirle "Validando…" mientras corre — si el panel
      // se redibujara antes, este nodo quedaría desprendido del DOM y esos
      // cambios no se verían en ningún lado. El modal de confirmación que
      // abre `instalarRelease` ya tapa el panel de todos modos; se cierra
      // solo cuando la instalación termina (`alTerminar`, más abajo).
      onClick: (e) => instalarRelease(d.comp, { tag: d.tag }, { boton: e.target, alTerminar: () => { abiertas = false; cargar(); } }),
    });
    return h("div", { class: "avisos__item" }, [
      h("span", { class: `avisos__punto ${d.prerelease ? "avisos__punto--falta" : "avisos__punto--ok"}` }),
      h("div", { style: { flex: "1", minWidth: "0" } }, [
        h("div", { class: "avisos__texto" }, [
          h("span", { style: { fontWeight: "600" }, text: d.comp.label }),
          " → ",
          h("span", { class: "mono", text: d.tag }),
          d.prerelease ? h("span", { class: "badge badge--falta", style: { marginLeft: "5px" }, text: "prueba" }) : null,
        ]),
        h("div", { class: "avisos__texto", style: { marginTop: "3px", color: "var(--texto-3)" }, text: primeraLinea(d.body) || "Sin notas." }),
      ]),
      boton,
    ]);
  }

  /**
   * El último release de cada componente que sea más nuevo que el
   * instalado, según la preferencia de prueba.
   *
   * Cada componente se revisa aislado: si el repo del núcleo es privado y
   * falta el token, ese `api.releases` tira 403 — y no tiene por qué tapar
   * el aviso de la web app, que sí contestó. `Promise.all` los ataría a los
   * dos al primero que falle; `allSettled` deja que cada componente valga
   * por su cuenta.
   */
  async function cargar() {
    cargando = true; error = null; redibujar();
    let estado;
    try {
      estado = await api.actualizaciones();
    } catch (e) {
      // Sin esto no hay ni con qué comparar: acá sí es un error de todo el
      // panel, no de un componente.
      error = e.message;
      disponibles = [];
      cargando = false;
      redibujar();
      return;
    }

    const resultados = await Promise.allSettled(COMPONENTES_UPDATE.map(async (comp) => {
      const instalado = estado.components[comp.id];
      // Uno solo: alcanza con saber si el más nuevo ya está instalado.
      const { releases } = await api.releases(comp.id, incluirPrueba(), 1, 1);
      const ultimo = (releases || [])[0];
      if (!ultimo || ultimo.tag === instalado.tag) return null;
      return { comp, tag: ultimo.tag, prerelease: ultimo.prerelease, body: ultimo.body };
    }));
    disponibles = resultados.filter((r) => r.status === "fulfilled" && r.value).map((r) => r.value);
    // Sin repo configurado, sin token en un repo privado, sin red: se
    // guarda para mostrarlo si la persona abre el panel, pero sólo cuando
    // **ningún** componente pudo revisarse — uno que sí contestó ya tiene
    // su propia fila, y repetir el error de al lado sería ruido.
    const fallidos = resultados.filter((r) => r.status === "rejected");
    if (fallidos.length === resultados.length) error = fallidos[0].reason?.message || "No se pudo revisar.";
    cargando = false;
    redibujar();
  }

  redibujar();
  cargar();

  return contenedor;
}

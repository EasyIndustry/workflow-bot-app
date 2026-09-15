/**
 * Inicio: qué tiene esta instalación y qué sigue.
 *
 * Es la pantalla a la que llega alguien que acaba de terminar el wizard: la
 * instalación existe, está vacía, y "Bot no sabe hacer nada" hasta que se le
 * instale un plugin y se le conecte una fuente. Cada tarjeta dice si ese paso
 * está hecho y adónde ir a hacerlo. Con la instalación en uso sigue sirviendo
 * como resumen; se llega desde la marca de la barra lateral.
 */

import { h, poner } from "../dom.js";
import { api } from "../api.js";
import { irA } from "../router.js";
import { aviso } from "../components/aviso.js";

let shell = null;

export async function montar(elShell) {
  shell = elShell;
  shell.ponerRotulo("INICIO");
  shell.limpiarLateral();
  poner(shell.extraLateral, h("div", { class: "lateral__nota" }, [
    "Este resumen se abre desde la marca de arriba, en cualquier momento.",
  ]));

  poner(shell.vista, h("div", { class: "cargando", text: "Cargando…" }));
  const r = await api.resumen();

  const pasos = [
    {
      hecho: r.plugins_installed > 0 || r.plugins > 1,
      titulo: "Instalar un plugin",
      texto: r.plugins_dir
        ? "Un plugin es lo que le da tools a los flujos: mover archivos, llamar a una API, esperar. Se instala un .py o un .zip; el núcleo lo valida antes de activarlo."
        : "Esta instalación no declara plugins_dir en boot.env: hay que agregarlo antes de poder instalar.",
      estado: r.plugins_installed ? `${r.plugins_installed} instalado${r.plugins_installed === 1 ? "" : "s"}` : "ninguno todavía",
      accion: "Ir a Plug ins", ir: () => irA("plugins"),
    },
    {
      hecho: r.sources > 0,
      titulo: "Conectar una fuente de datos",
      texto: "De dónde salen las filas que el bot procesa una por una: una API, por ahora. El formulario prueba la lectura con datos reales antes de guardar.",
      estado: r.sources ? `${r.sources} fuente${r.sources === 1 ? "" : "s"}` : "ninguna todavía",
      accion: "Conectar una fuente", ir: () => irA("plugins", "connections", "sources", "_nuevo"),
    },
    {
      hecho: r.workflows > 0,
      titulo: "Escribir un flujo",
      texto: "Qué se hace con cada fila, nodo por nodo. Se edita en tarjetas o como texto Mermaid, y se prueba con un dry run antes de ejecutarlo de verdad.",
      estado: r.workflows ? `${r.workflows} flujo${r.workflows === 1 ? "" : "s"}` : "ninguno todavía",
      accion: "Ir a Workflows", ir: () => irA("workflows"),
    },
    {
      hecho: r.key_exists,
      titulo: "Cargar los secretos",
      texto: "Tokens y claves de API se guardan cifrados y los flujos los referencian como {env.NOMBRE}. La llave de cifrado vive fuera de la base: es lo único que hay que respaldar.",
      estado: r.key_exists ? "llave de cifrado presente" : "todavía sin secretos",
      accion: "Ir a Secretos", ir: () => irA("config", "secretos"),
    },
  ];

  const hechos = pasos.filter((p) => p.hecho).length;

  poner(shell.vista, h("div", { class: "columna" }, [
    h("div", { style: { marginBottom: "16px" } }, [
      h("div", { class: "titulo", text: r.fresh ? "Bot quedó instalado. Todavía no sabe hacer nada." : "Esta instalación" }),
      h("div", { class: "subtitulo" }, [
        r.fresh
          ? "La base está creada y la configuración escrita. Lo que sigue son estos pasos, en este orden."
          : `${hechos} de ${pasos.length} pasos hechos. `,
        h("span", { class: "mono", text: r.root }),
      ]),
    ]),
    r.plugin_errors
      ? aviso("error", `${r.plugin_errors} plugin${r.plugin_errors === 1 ? "" : "s"} no cargó`, "Está en la lista de Plug ins con su error.")
      : null,
    ...pasos.map((p, i) => h("div", { class: "tarjeta", style: { display: "flex", gap: "14px", padding: "14px 16px", alignItems: "flex-start" } }, [
      h("div", {
        style: {
          flex: "0 0 26px", height: "26px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "12px", fontWeight: "600",
          background: p.hecho ? "var(--verde-fondo)" : "var(--fondo-panel)",
          color: p.hecho ? "var(--verde)" : "var(--texto-3)",
          border: `1px solid ${p.hecho ? "var(--verde-borde)" : "var(--borde)"}`,
        },
        text: p.hecho ? "✓" : String(i + 1),
      }),
      h("div", { style: { flex: "1", minWidth: "0" } }, [
        h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [
          h("div", { style: { fontWeight: "600", fontSize: "13px" }, text: p.titulo }),
          h("span", { class: "badge" + (p.hecho ? " badge--ok" : ""), text: p.estado }),
        ]),
        h("div", { style: { fontSize: "12px", color: "var(--texto-3)", marginTop: "4px", lineHeight: "1.5" }, text: p.texto }),
      ]),
      h("button", { class: "btn" + (!p.hecho && i === pasos.findIndex((q) => !q.hecho) ? " btn--primario" : ""), text: p.accion, onClick: p.ir }),
    ])),
    h("div", { class: "tabla__pie", text:
      `Ejecuta como "${r.default_actor}" salvo que un run nombre a otro actor. Quién puede qué se decide en Config → Seguridad.` }),
  ]));
}

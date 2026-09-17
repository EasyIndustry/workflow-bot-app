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
  const huecoDiagnostico = h("div");

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
    // El hueco donde entra el diagnóstico cuando termina de correr, más abajo.
    huecoDiagnostico,
    limites(r),
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

  mirarDiagnostico(huecoDiagnostico);
}

/**
 * Los límites de la instalación, con `fs_root` a la cabeza.
 *
 * Hasta ahora la única pantalla que nombraba un límite era el wizard, y una
 * vez instalado no había forma de ver contra qué carpeta está acotado el port
 * `fs`. En producción eso se descubrió con un flujo fallando por
 * "ruta fuera del árbol permitido" contra un `fs_root` mal escrito: el
 * mensaje culpa al flujo, y el valor que lo explicaba no se veía en ningún
 * lado.
 */
function fila(que, valor, detalle) {
  return h("div", {
    style: { display: "flex", gap: "12px", padding: "9px 0", borderBottom: "1px solid var(--borde-4)",
             alignItems: "baseline", flexWrap: "wrap" },
  }, [
    h("div", { style: { flex: "0 0 108px", fontSize: "11.5px", color: "var(--texto-3)" }, text: que }),
    h("div", { style: { flex: "1", minWidth: "0" } }, [
      h("div", { class: "mono", style: { fontSize: "11.5px", overflowWrap: "anywhere" }, text: valor }),
      detalle ? h("div", { style: { fontSize: "11px", color: "var(--texto-4)", marginTop: "2px" }, text: detalle }) : null,
    ]),
  ]);
}

function limites(r) {
  return h("div", { class: "tarjeta", style: { padding: "12px 16px 4px" } }, [
    h("div", { style: { fontWeight: "600", fontSize: "13px", marginBottom: "4px" }, text: "Hasta dónde llega" }),
    fila("Instalación", r.root, "boot.env, data/, plugins/ y workspace/ viven acá."),
    ...archivos(r),
    fila("Plugins", r.plugins_dir || "sin declarar",
      "Fuera de la caja: ningún flujo puede dejar código ahí."),
    // Lo que el núcleo niega siempre (core#26). Sin esto, alguien que ve una
    // raíz que contiene la instalación no tiene cómo saber que la base, la
    // llave y boot.env quedan afuera igual.
    ...(r.fs_negadas || []).length
      ? [fila("Nunca", (r.fs_negadas || []).join("
"),
          "Un flujo no las alcanza aunque caigan adentro de una raíz: la base y la llave, los plugins, y el archivo que declara estos límites.")]
      : [],
  ]);
}

/**
 * Las raíces del port `fs`, una fila por cada una.
 *
 * Desde core#23 pueden ser varias con alias —un workspace local y un share de
 * red a la vez—, y la de alias vacío es la de por defecto: la que resuelve
 * una ruta relativa. Mostrar sólo la primera diría media verdad, y no
 * mostrarlas diría "todo el disco", que es exactamente lo contrario.
 */
function archivos(r) {
  const raices = Object.entries(r.fs_roots || {});
  if (!raices.length) {
    return [fila("Archivos", "todo el disco",
      "boot.env no declara fs_root ni fs_roots, así que un flujo puede leer y escribir cualquier parte del disco.")];
  }
  if (raices.length === 1) {
    return [fila("Archivos", raices[0][1],
      "Un flujo con el port fs no sale de esta carpeta: fuera de acá devuelve \"ruta fuera del árbol permitido\".")];
  }
  return raices.map(([alias, ruta], i) => fila(
    i === 0 ? "Archivos" : "",
    ruta,
    alias
      ? `Un flujo la nombra como ${alias}:archivo.${i === 0 ? " Es también la raíz por defecto, la que resuelve una ruta relativa." : ""}`
      : "La raíz por defecto: es contra ésta que resuelve una ruta relativa."));
}

/**
 * El diagnóstico, en segundo plano y sólo si tiene algo que decir.
 *
 * Los chequeos ya existían en Config → Diagnóstico, y ahí estaba el aviso de
 * que `fs_root` apuntaba a una carpeta inexistente —en producción nadie fue a
 * mirarlo, y el problema apareció mucho después adentro de un run. No bloquea
 * el dibujo de Inicio: si el diagnóstico tarda o falla, la pantalla ya está.
 */
async function mirarDiagnostico(hueco) {
  let reporte;
  try {
    reporte = await api.doctor();
  } catch {
    return;  // Sin diagnóstico se sigue igual: no es lo que esta pantalla vino a hacer.
  }
  const problemas = (reporte.checks || []).filter((c) => c.level !== "ok");
  if (!problemas.length || !hueco.isConnected) return;

  const grave = problemas.some((c) => c.level === "error");
  poner(hueco, aviso(grave ? "error" : "falta",
    `${problemas.length} chequeo${problemas.length === 1 ? "" : "s"} de la instalación con algo que mirar`,
    h("div", {}, [
      h("div", { text: problemas.map((c) => `${c.name}: ${c.message}`).join(" · ") }),
      h("div", { style: { marginTop: "6px" } }, [
        h("a", { href: "#", text: "Ver el diagnóstico completo",
                 onClick: (e) => { e.preventDefault(); irA("config", "diagnostico"); } }),
      ]),
    ])));
}

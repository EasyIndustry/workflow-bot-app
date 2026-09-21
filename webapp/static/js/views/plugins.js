/**
 * Plug ins: la configuración y las colecciones de cada plugin instalado.
 *
 * Nada de esta pantalla conoce un plugin por nombre. La lista sale de
 * `GET /tools`, los campos de `Setting` y de `Resource.fields`, y lo que falta
 * configurar de `GET /config → missing`. Un plugin nuevo aparece acá con su
 * formulario sin tocar una línea de este archivo.
 */

import { h, poner, icono, ICONOS } from "../dom.js";
import { api, ErrorApi } from "../api.js";
import { irA } from "../router.js";
import { crearFormulario, crearCampo } from "../components/campo.js";
import { tabla } from "../components/tabla.js";
import { abrirModal, confirmar } from "../components/modal.js";
import { aviso } from "../components/aviso.js";

let catalogo = null;   // GET /tools
let config = null;     // GET /config
let instalacion = null; // GET /plugins/install-info: dónde se instala y qué hay ahí
let shell = null;

// Guardar redibuja la pantalla entera, así que un mensaje puesto en el DOM se
// borra con el redibujo. Se deja acá y lo consume el próximo `dibujarPlugin`.
let confirmacion = null;

// Lo mismo adentro del catálogo: instalar recarga la lista entera, así que el
// "Listo" de la fila no puede vivir en el DOM de la fila que se está tirando.
// Se anota por nombre de plugin y lo consume la fila nueva. Se vacía al abrir
// el modal: es el resultado de esta pasada, no de la anterior.
let instaladosEnCatalogo = {};

export async function montar(elShell, partes) {
  shell = elShell;
  shell.ponerRotulo("PLUG INS");

  [catalogo, config, instalacion] = await Promise.all([api.tools(), api.config(), api.infoInstalacion()]);

  const plugins = catalogo.plugins || [];
  const elegido = plugins.find((p) => p.name === partes[0]) || plugins.find((p) => p.name !== "core") || plugins[0];

  dibujarLateral(plugins, elegido);

  // #/plugins/{plugin}/{resource}/{clave|_nuevo} — el alta y la edición de un
  // item viven en su propia página, no en un modal: un source con quince
  // campos y un botón de "Probar" no entra cómodo en un modal, y la URL
  // permite volver a un item puntual con el back del navegador.
  if (partes.length >= 3 && partes[0] === elegido.name) {
    const recurso = (elegido.resources || []).find((r) => r.name === partes[1]);
    if (recurso) {
      const clave = partes[2] === "_nuevo" ? null : partes[2];
      return dibujarItem(elegido, recurso, clave);
    }
  }

  await dibujarPlugin(elegido);
}

/** Si el plugin vive en plugins_dir — o sea, si se puede desinstalar desde acá. */
const esInstalado = (plugin) => (instalacion.installed || []).some((i) => i.name === plugin.name);

/** Qué le falta a un plugin para poder trabajar. */
const faltantesDe = (plugin) => (config.missing || {})[plugin.name] || [];

function estadoDe(plugin) {
  if (plugin.source === "builtin") return { texto: "", clase: "badge", punto: "" };
  if (faltantesDe(plugin).length) return { texto: "falta configurar", clase: "badge badge--falta", punto: "item__punto--falta" };
  return { texto: "listo", clase: "badge badge--ok", punto: "item__punto--ok" };
}

// ── Barra lateral ───────────────────────────────────────────────────────

function dibujarLateral(plugins, elegido) {
  shell.limpiarLateral();

  const fila = (p) => {
    const estado = estadoDe(p);
    return h("div", {
      class: "item" + (p.name === elegido.name ? " item--activo" : ""),
      onClick: () => irA("plugins", p.name),
    }, [
      h("span", { class: "item__punto " + estado.punto }),
      h("span", { class: "item__texto", text: p.label || p.name }),
      h("span", { class: "item__meta", text: String((p.tools || []).length) }),
    ]);
  };

  const nucleo = plugins.filter((p) => p.source === "builtin");
  const resto = plugins.filter((p) => p.source !== "builtin");
  const rotos = (catalogo.errors || []);

  // Un plugin que no cargó se muestra en la misma lista donde se lo esperaba,
  // con su error al pasar el mouse — no en un log que nadie abre.
  const filaRota = (e) => h("div", {
    class: "item", title: e.error, style: { cursor: "help" },
    onClick: () => abrirErrorDeCarga(e),
  }, [
    h("span", { class: "item__punto item__punto--error" }),
    h("span", { class: "item__texto", text: e.name }),
    h("span", { class: "item__meta", text: "!" }),
  ]);

  poner(shell.cuerpoLateral,
    nucleo.length ? h("div", { class: "lateral__rotulo", style: { padding: "6px 4px" }, text: "NÚCLEO" }) : null,
    ...nucleo.map(fila),
    resto.length ? h("div", { class: "lateral__rotulo", style: { padding: "12px 4px 6px" }, text: "INSTALADOS" }) : null,
    ...resto.map(fila),
    rotos.length ? h("div", { class: "lateral__rotulo", style: { padding: "12px 4px 6px" }, text: "NO CARGARON" }) : null,
    ...rotos.map(filaRota),
    h("div", {
      class: "item item--dashed",
      title: "Los plugins curados del repo de la empresa: se eligen y se instalan desde acá",
      onClick: () => abrirCatalogo(),
    }, [h("span", { style: { fontSize: "13px", lineHeight: "1" }, text: "☁" }), h("span", { text: "Plugins en línea" })]),
    h("div", {
      class: "item item--dashed",
      title: instalacion.plugins_dir
        ? `Se copia a ${instalacion.plugins_dir} y se activa si el núcleo lo acepta`
        : "Esta instalación no declara plugins_dir en boot.env",
      onClick: () => abrirInstalar(),
    }, [h("span", { style: { fontSize: "13px", lineHeight: "1" }, text: "+" }), h("span", { text: "Instalar un archivo" })]),
    h("div", {
      class: "item item--dashed",
      title: "Las librerías Python que piden los plugins, el runtime donde se instalan y su versión",
      onClick: () => abrirLibrerias(),
    }, [h("span", { style: { fontSize: "13px", lineHeight: "1" }, text: "≡" }), h("span", { text: "Librerías" })]),
  );
}

// ── Librerías ───────────────────────────────────────────────────────────
//
// Un plugin puede pedir librerías Python para cómputo (numpy, trimesh) en su
// requirements.txt; la app las instala en el runtime del programa, sólo
// desde wheels con versión y hash fijos (webapp/librerias.py). Esta pantalla
// muestra qué pide cada plugin instalado, qué hay, y la versión del runtime
// contra la que cura el catálogo. Nada acá conoce un plugin por nombre.

async function abrirLibrerias() {
  const cuerpo = h("div", {}, [h("div", { class: "cargando", style: { padding: "22px" }, text: "Mirando el runtime…" })]);
  const { cerrar } = abrirModal({
    titulo: "Librerías",
    sub: "Lo que cada plugin declara en su requirements.txt y lo que hay en el runtime. Sólo wheels con versión y hash fijos; sin sdist.",
    cuerpo,
    acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() })],
  });

  async function cargar() {
    let datos;
    try {
      datos = await api.libreriasDePlugins();
    } catch (e) {
      poner(cuerpo, aviso("error", "No se pudo leer el runtime", e.message));
      return;
    }
    poner(cuerpo, ...pintarLibrerias(datos, cargar));
  }
  cargar();
}

function pintarLibrerias(datos, recargar) {
  const rt = datos.runtime || {};
  const partes = [
    h("div", { style: { padding: "12px 16px 8px", fontSize: "12.5px", lineHeight: "1.6" } }, [
      h("div", {}, [
        h("span", { style: { color: "var(--texto-3)" }, text: "Runtime: " }),
        h("span", { class: "mono", text: `Python ${rt.python || "?"}` }),
        rt.tag
          ? h("span", { class: "mono", style: { color: "var(--texto-3)" }, text: ` · release ${rt.tag}` })
          : h("span", { style: { color: "var(--texto-3)" }, text: " · en vivo (sin runtime-release.json: desarrollo o programa anterior)" }),
      ]),
      h("div", { class: "mono", style: { fontSize: "11px", color: "var(--texto-4)", overflowWrap: "anywhere" }, text: rt.executable || "" }),
      // Sin la marca del instalador, esto es el intérprete del repo o un
      // programa anterior: el catálogo cura contra el runtime del .exe, así
      // que instalar desde acá falla por una versión de Python que no es la
      // del plugin. Se dice antes de intentar, no después de que pip falle.
      rt.tag ? null : h("div", { style: { marginTop: "8px" } }, [
        aviso("falta", "Este no es el runtime del programa",
          `Las librerías de los plugins se instalan en el runtime que deja el instalador. Acá hay Python ${rt.python || "?"}: ` +
          `un plugin curado para el programa va a fallar con "no hay una wheel". Instalalas desde el Bot instalado.`),
      ]),
      h("div", { style: { marginTop: "6px", color: "var(--texto-3)" } }, [
        "Sin internet: copiá las wheels a ",
        h("span", { class: "mono", text: datos.wheels_dir }),
        datos.wheels.length ? ` (hay ${datos.wheels.length}).` : " (vacía).",
      ]),
    ]),
  ];

  if (!datos.plugins.length) {
    partes.push(h("div", { class: "tabla__vacia", text: "Ningún plugin instalado declara librerías." }));
    return partes;
  }
  for (const p of datos.plugins) partes.push(filaLibrerias(p, recargar));
  return partes;
}

function filaLibrerias(p, recargar) {
  const faltan = (p.requirements || []).filter((r) => !r.ok);
  const detalle = h("div", { style: { fontSize: "11.5px", color: "var(--rojo)", display: "none", whiteSpace: "pre-wrap" } });
  const listo = h("div", { style: { fontSize: "11.5px", color: "var(--verde)", display: "none", marginTop: "3px" } });
  const chkOffline = h("input", { type: "checkbox" });
  const boton = faltan.length
    ? h("button", { class: "btn btn--chico btn--primario", text: `Instalar ${faltan.length === 1 ? "la que falta" : `las ${faltan.length} que faltan`}` })
    : null;
  if (boton) {
    boton.addEventListener("click", async () => {
      boton.disabled = true;
      boton.textContent = "Instalando…";
      try {
        await api.instalarLibreriasDe(p.name, { offline: chkOffline.checked });
        confirmacion = `Se instalaron las librerías de "${p.name}".`;
        await recargar();
      } catch (e) {
        detalle.textContent = [e.message, ...(e.errores || [])].join("\n");
        detalle.style.display = "";
        boton.disabled = false;
        boton.textContent = "Reintentar";
      }
    });
  }
  const filas = (p.requirements || []).map((r) => h("div", { class: "mono", style: { fontSize: "11.5px", display: "flex", gap: "8px" } }, [
    h("span", { class: r.ok ? "badge badge--ok" : "badge badge--falta", text: r.ok ? "ok" : (r.installed ? "otra versión" : "falta") }),
    h("span", { text: `${r.name}==${r.required}` }),
    r.installed && !r.ok ? h("span", { style: { color: "var(--texto-3)" }, text: `(hay ${r.installed})` }) : null,
  ]));
  return h("div", { style: { display: "flex", gap: "12px", alignItems: "flex-start", padding: "9px 16px", borderTop: "1px solid var(--borde)" } }, [
    h("div", { style: { flex: "1", minWidth: "0" } }, [
      h("div", { style: { fontWeight: "600", fontSize: "13px", marginBottom: "4px" }, text: p.name }),
      ...(p.error ? [h("div", { class: "mono", style: { fontSize: "11.5px", color: "var(--rojo)", whiteSpace: "pre-wrap" }, text: p.error.join("\n") })] : filas),
      detalle,
    ]),
    boton ? h("div", { style: { display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end" } }, [
      boton,
      h("label", { class: "fila-control", style: { cursor: "pointer", fontSize: "11.5px" } }, [chkOffline, h("span", { text: "sin internet" })]),
    ]) : null,
  ]);
}

// ── Plugins en línea ────────────────────────────────────────────────────

/**
 * El catálogo curado: un repo de GitHub con un `plugins/<name>.json` por
 * plugin y el código al lado. El programa se instala sin plugins y de acá se
 * traen los que hacen falta. La rama se elige por instalación: `cured` es lo
 * curado; cualquier otra (`draft`) es trabajo sin terminar y se dice.
 */
async function abrirCatalogo() {
  instaladosEnCatalogo = {};
  const cuerpo = h("div", {}, [h("div", { class: "cargando", style: { padding: "22px" }, text: "Leyendo el catálogo…" })]);
  const { cerrar } = abrirModal({
    titulo: "Plugins en línea",
    sub: "Curados en el repo de la empresa. Instalar baja la rama elegida y valida el plugin antes de activarlo, igual que un archivo.",
    cuerpo,
    acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() })],
  });

  async function cargar() {
    let datos;
    try {
      datos = await api.catalogoPlugins();
    } catch (e) {
      poner(cuerpo, aviso("error", "No se pudo leer el catálogo", e.message));
      return;
    }
    poner(cuerpo, ...pintarCatalogo(datos, cargar, cerrar));
  }
  cargar();
}

function pintarCatalogo(datos, recargar, cerrarModal) {
  const esCurada = datos.branch === "cured";
  const selectorRama = h("select", { class: "selector", style: { width: "auto" } },
    datos.branches.map((b) => h("option", { value: b, text: b === "cured" ? "cured · curados" : `${b} · sin terminar` })));
  selectorRama.value = datos.branch;
  const campoRepo = h("input", { class: "entrada mono", value: datos.repo, style: { maxWidth: "320px", fontSize: "12px" },
    title: "owner/repo en GitHub" });
  const aplicar = async () => {
    try {
      await api.configurarCatalogoPlugins(campoRepo.value.trim(), selectorRama.value);
      await recargar();
    } catch (e) {
      poner(error, h("div", { class: "aviso__cuerpo" }, [h("div", { class: "aviso__titulo", text: e.message })]));
      error.style.display = "";
    }
  };
  selectorRama.addEventListener("change", aplicar);
  campoRepo.addEventListener("keydown", (e) => { if (e.key === "Enter") aplicar(); });
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "0 16px 10px" } });

  const partes = [
    h("div", { style: { display: "flex", alignItems: "center", gap: "9px", padding: "12px 16px 8px", flexWrap: "wrap" } }, [
      h("span", { style: { fontSize: "12px", color: "var(--texto-3)" }, text: "Repo" }), campoRepo,
      h("span", { style: { fontSize: "12px", color: "var(--texto-3)" }, text: "Rama" }), selectorRama,
      h("button", { class: "btn btn--chico", text: "Aplicar", onClick: aplicar }),
    ]),
    error,
  ];
  if (!esCurada) {
    partes.push(h("div", { style: { margin: "0 16px 10px" } }, [
      aviso("falta", `La rama "${datos.branch}" es trabajo sin terminar`,
        "Lo que se instale de acá puede fallar o cambiar. Para producción, la rama cured."),
    ]));
  }
  if (datos.error) {
    partes.push(h("div", { style: { margin: "0 16px 10px" } }, [aviso("error", "No se pudo leer el catálogo", datos.error)]));
  }
  if (!datos.entries.length && !datos.error) {
    partes.push(h("div", { class: "tabla__vacia", text: `La rama "${datos.branch}" no tiene plugins.` }));
  }

  const filas = datos.entries.map((e) => filaCatalogo(e, datos, recargar, cerrarModal));
  partes.push(h("div", { style: { padding: "0 16px 12px" } }, filas));
  return partes;
}

function filaCatalogo(entrada, datos, recargar, cerrarModal) {
  const prov = entrada.provenance;
  const estado = !entrada.installed
    ? h("span", { class: "badge", text: "no instalado" })
    : prov
      ? h("span", { class: entrada.hay_nueva ? "badge badge--falta" : "badge badge--ok",
                    title: `commit ${prov.commit || "?"}`,
                    text: `instalado · v${prov.version || "?"} · ${prov.branch || "?"}` })
      : h("span", { class: "badge badge--ok", text: "instalado (a mano)" });
  // La ficha del catálogo no publica versión (workflow-bot-plugins#2), así
  // que lo comparable es el commit que tocó esa carpeta por última vez. Dice
  // "cambió desde que lo instalaste", que es la pregunta real antes de
  // reinstalar.
  const novedad = entrada.hay_nueva
    ? h("span", { class: "badge badge--falta", style: { marginLeft: "6px" },
                  title: [`el catálogo va por ${entrada.upstream.head}`,
                          entrada.upstream.fecha ? `del ${entrada.upstream.fecha.slice(0, 10)}` : "",
                          `${entrada.upstream.adelante} commit${entrada.upstream.adelante === 1 ? "" : "s"} desde el que tenés`,
                          "Actualizar baja lo de ahora."].filter(Boolean).join("\n"),
                  text: "hay una versión nueva" })
    : null;
  const boton = h("button", {
    class: "btn btn--chico" + (!entrada.installed || entrada.hay_nueva ? " btn--primario" : ""),
    text: !entrada.installed ? "Instalar" : entrada.hay_nueva ? "Actualizar" : "Reinstalar",
    disabled: !entrada.installable,
    title: entrada.installable ? `Baja la rama ${datos.branch} e instala ${entrada.path}` : "Entrada de índice sin código: no hay nada que instalar desde acá",
  });
  const detalle = h("div", { style: { fontSize: "11.5px", color: "var(--rojo)", display: "none", whiteSpace: "pre-wrap" } });
  const hecho = instaladosEnCatalogo[entrada.name];
  const listo = h("div", { style: { fontSize: "11.5px", color: "var(--verde)", display: hecho ? "" : "none", marginTop: "3px" },
                           text: hecho || "" });
  // Si el plugin trae librerías, "sin internet" las toma sólo de la carpeta
  // wheels/ (del plugin o de la instalación) en vez de salir a PyPI.
  const chkOffline = h("input", { type: "checkbox" });

  boton.addEventListener("click", async () => {
    boton.disabled = true;
    boton.textContent = "Instalando…";
    try {
      const r = await api.instalarDesdeCatalogo(entrada.name, { offline: chkOffline.checked });
      // Se queda en el catálogo. Antes cerraba el modal y saltaba a la ficha
      // del plugin: si estabas instalando tres seguidos, después de cada uno
      // había que volver a abrir "Plugins en línea" y buscar dónde ibas. El
      // resultado se dice acá, en la fila, y la lista se recarga para que el
      // estado y el aviso de versión nueva queden al día.
      instaladosEnCatalogo[entrada.name] = `Listo: v${r.installed.plugin.version}`
        + `, ${r.installed.plugin.tools.length} tool${r.installed.plugin.tools.length === 1 ? "" : "s"}.`;
      confirmacion = `Se instaló "${r.installed.name}" v${r.installed.plugin.version} desde ${datos.repo} (${datos.branch}).`;
      await recargar();
    } catch (e) {
      detalle.textContent = [e.message, ...(e.errores || [])].join("\n");
      detalle.style.display = "";
      boton.disabled = false;
      boton.textContent = !entrada.installed ? "Instalar" : entrada.hay_nueva ? "Actualizar" : "Reinstalar";
    }
  });

  return h("div", { style: { display: "flex", gap: "12px", alignItems: "flex-start", padding: "9px 0", borderTop: "1px solid var(--borde)" } }, [
    h("div", { style: { flex: "1", minWidth: "0" } }, [
      h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, [
        h("span", { style: { fontWeight: "600", fontSize: "13px" }, text: entrada.name }),
        estado,
        novedad,
      ]),
      h("div", { style: { fontSize: "12px", color: "var(--texto-2)", marginTop: "3px" }, text: entrada.description }),
      h("div", { class: "mono", style: { fontSize: "11px", color: "var(--texto-4)", marginTop: "3px" },
        text: [`ports: ${(entrada.ports || []).join(", ") || "—"}`, entrada.compatible_core ? `core ${entrada.compatible_core}` : "", entrada.compatible_runtime ? `runtime ${entrada.compatible_runtime}` : "", entrada.path || entrada.source].filter(Boolean).join(" · ") }),
      detalle,
      listo,
    ]),
    h("div", { style: { display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end" } }, [
      boton,
      entrada.installable
        ? h("label", { class: "fila-control", style: { cursor: "pointer", fontSize: "11.5px" }, title: "Las librerías del plugin, si pide alguna, sólo desde la carpeta wheels/" },
            [chkOffline, h("span", { text: "sin internet" })])
        : null,
    ]),
  ]);
}

function abrirErrorDeCarga(e) {
  const { cerrar } = abrirModal({
    titulo: `${e.name} no cargó`,
    sub: e.source,
    cuerpo: h("pre", { class: "mono", style: { margin: "12px 16px", whiteSpace: "pre-wrap", fontSize: "11.5px" }, text: e.error }),
    acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() })],
  });
}

// ── Instalar ────────────────────────────────────────────────────────────

/**
 * Instalar es dejar el plugin en `plugins_dir`: un .py, una carpeta con
 * __init__.py o un .zip. Antes de activarlo el servidor lo carga en otro
 * proceso, y si el núcleo no lo acepta no se copia nada. Dos orígenes, un
 * mismo camino: un archivo de esta computadora, o una ruta de la máquina que
 * corre el servidor — que es lo que usa un agente que acaba de escribirlo.
 */
function abrirInstalar() {
  if (!instalacion.plugins_dir) {
    const { cerrar } = abrirModal({
      titulo: "No hay dónde instalar",
      sub: "boot.env no declara plugins_dir.",
      cuerpo: h("div", { style: { padding: "12px 16px", fontSize: "12.5px", lineHeight: "1.5" } }, [
        "Los plugins viven en una carpeta propia, fuera de ", h("span", { class: "mono", text: "fs_root" }),
        ", para que ningún flujo pueda dejar código listo para correr en el próximo arranque. ",
        "Se agrega ", h("span", { class: "mono", text: "plugins_dir=<carpeta>" }),
        " a boot.env, se crea la carpeta, y se reinicia el servidor.",
      ]),
      acciones: [h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() })],
    });
    return;
  }

  let modo = "archivo";
  const error = h("div", { class: "aviso aviso--error", style: { display: "none", margin: "12px 16px 0" } });
  const inputArchivo = h("input", { type: "file", accept: ".py,.zip", class: "entrada" });
  const campoRuta = crearCampo({ name: "path", type: "str", label: "Ruta en el servidor", required: true,
    doc: "Un .py, una carpeta con __init__.py o un .zip, en la máquina que corre el servidor. Se copia: borrar el original después no rompe nada." }, "");
  const campoNombre = crearCampo({ name: "name", type: "str", label: "Nombre",
    doc: "Opcional. Con qué nombre de módulo queda instalado; si no, el del archivo o la carpeta." }, "");
  const chkReemplazar = h("input", { type: "checkbox" });
  const chkOffline = h("input", { type: "checkbox" });

  const filaArchivo = h("div", { class: "campo" }, [
    h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Archivo" })]),
    h("div", { class: "campo__control" }, [
      inputArchivo,
      h("div", { class: "campo__ayuda", text: "Un .py suelto, o un .zip con la carpeta del plugin (con su __init__.py)." }),
    ]),
  ]);

  const pestanas = h("div", { class: "grupo-botones", style: { margin: "12px 16px 0" } });
  const pintarPestanas = () => {
    poner(pestanas,
      h("button", { class: "btn" + (modo === "archivo" ? " btn--activo" : ""), text: "Subir un archivo", onClick: () => { modo = "archivo"; pintarPestanas(); } }),
      h("button", { class: "btn" + (modo === "ruta" ? " btn--activo" : ""), text: "Desde el servidor", onClick: () => { modo = "ruta"; pintarPestanas(); } }),
    );
    filaArchivo.style.display = modo === "archivo" ? "" : "none";
    campoRuta.elemento.style.display = modo === "ruta" ? "" : "none";
  };
  pintarPestanas();

  const cuerpo = h("div", {}, [
    error,
    h("div", { style: { padding: "12px 16px 0", fontSize: "12px", color: "var(--texto-3)" } }, [
      "Se copia a ", h("span", { class: "mono", text: instalacion.plugins_dir }),
      ". Antes de activarlo el núcleo lo carga en otro proceso: si pide un port que no existe, tiene ids duplicados o revienta al importar, no se instala y se ve por qué.",
    ]),
    pestanas,
    filaArchivo,
    campoRuta.elemento,
    campoNombre.elemento,
    h("div", { class: "campo" }, [
      h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Si ya existe" })]),
      h("div", { class: "campo__control" }, [
        h("label", { class: "fila-control", style: { cursor: "pointer" } }, [chkReemplazar, h("span", { style: { fontSize: "12.5px" }, text: "Reemplazar el instalado con ese nombre" })]),
        h("div", { class: "campo__ayuda", text: "Sin esto, instalar un nombre que ya existe falla. Con esto, el anterior se aparta y vuelve si el nuevo no carga." }),
      ]),
    ]),
    h("div", { class: "campo" }, [
      h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Librerías" })]),
      h("div", { class: "campo__control" }, [
        h("label", { class: "fila-control", style: { cursor: "pointer" } }, [chkOffline, h("span", { style: { fontSize: "12.5px" }, text: "Sin internet: sólo desde la carpeta wheels/" })]),
        h("div", { class: "campo__ayuda", text: "Si el plugin trae requirements.txt, sus librerías se instalan en el runtime antes de validarlo: sólo wheels con versión y hash fijos. Sin internet, se toman de wheels/ del plugin o de la instalación." }),
      ]),
    ]),
  ]);

  const botonInstalar = h("button", { class: "btn btn--primario", text: "Instalar" });
  const { cerrar } = abrirModal({
    titulo: "Instalar un plugin",
    sub: "Un plugin pide ports para hacer I/O; las librerías de cómputo que declare en requirements.txt se instalan con él.",
    cuerpo,
    izquierda: h("button", { class: "btn", text: "Plantilla para escribir uno", onClick: () => { cerrar(); abrirPlantilla(); } }),
    acciones: [
      h("button", { class: "btn", text: "Cancelar", onClick: () => cerrar() }),
      botonInstalar,
    ],
  });

  botonInstalar.addEventListener("click", async () => {
    const opciones = { name: campoNombre.leer().trim() || undefined, replace: chkReemplazar.checked, offline: chkOffline.checked };
    botonInstalar.disabled = true;
    botonInstalar.textContent = "Validando…";
    try {
      let resultado;
      if (modo === "archivo") {
        const archivo = inputArchivo.files && inputArchivo.files[0];
        if (!archivo) throw new Error("Elegí un archivo.");
        resultado = await api.instalarPluginArchivo(archivo, opciones);
      } else {
        const ruta = campoRuta.leer().trim();
        if (!ruta) throw new Error("Escribí la ruta.");
        resultado = await api.instalarPluginPorRuta(ruta, opciones);
      }
      cerrar();
      confirmacion = `Se instaló "${resultado.installed.name}" v${resultado.installed.plugin.version} con ${resultado.installed.plugin.tools.length} tool${resultado.installed.plugin.tools.length === 1 ? "" : "s"}.`;
      irA("plugins", resultado.installed.name);
      await montar(shell, [resultado.installed.name]);
    } catch (e) {
      error.style.display = "";
      poner(error, h("div", { class: "aviso__cuerpo" }, [
        h("div", { class: "aviso__titulo", text: e.message }),
        ...(e.errores || []).map((linea) => h("div", { class: "mono", style: { fontSize: "11.5px", whiteSpace: "pre-wrap" }, text: linea })),
      ]));
      botonInstalar.disabled = false;
      botonInstalar.textContent = "Instalar";
    }
  });
}

/** El esqueleto de un plugin, generado desde el contrato: lo mismo que el MCP da a un agente. */
function abrirPlantilla() {
  const campoNombre = crearCampo({ name: "name", type: "str", label: "Nombre", required: true,
    doc: "Nombre de módulo: letras, números y guión bajo." }, "mio");
  const ports = instalacion.ports || ["http", "fs", "process", "clock"];
  const chks = Object.fromEntries(ports.map((p) => [p, h("input", { type: "checkbox", checked: p === "http" })]));
  const salida = h("pre", { class: "mono", style: { display: "none", margin: "12px 16px 0", padding: "10px", border: "1px solid var(--borde)", background: "var(--fondo-panel)", fontSize: "11px", maxHeight: "320px", overflow: "auto", whiteSpace: "pre" } });
  const pie = h("div", { style: { display: "none", padding: "8px 16px 0", fontSize: "11.5px", color: "var(--texto-3)" } });

  const { cerrar } = abrirModal({
    titulo: "Plantilla de un plugin",
    sub: "Generada desde el contrato del núcleo, así no puede quedar vieja. Un agente la pide igual por MCP (plugin_template).",
    cuerpo: h("div", {}, [
      campoNombre.elemento,
      h("div", { class: "campo" }, [
        h("div", { class: "campo__etiqueta" }, [h("div", { class: "campo__nombre", text: "Ports que va a usar" })]),
        h("div", { class: "campo__control" }, ports.map((p) => h("label", { class: "fila-control", style: { cursor: "pointer" } }, [chks[p], h("span", { class: "mono", style: { fontSize: "12px" }, text: p })]))),
      ]),
      salida,
      pie,
    ]),
    acciones: [
      h("button", { class: "btn", text: "Cerrar", onClick: () => cerrar() }),
      h("button", { class: "btn btn--primario", text: "Generar", onClick: async () => {
        try {
          const r = await api.plantillaPlugin(campoNombre.leer().trim(), ports.filter((p) => chks[p].checked));
          salida.textContent = r.code;
          salida.style.display = "";
          poner(pie, `Guardar como ${r.filename}, completar los TODO, y volver acá a "Instalar un plugin" → Desde el servidor con la ruta. `, r.siguiente_paso);
          pie.style.display = "";
        } catch (e) {
          salida.textContent = e.message;
          salida.style.display = "";
        }
      }}),
    ],
  });
}

function desinstalar(plugin) {
  confirmar({
    titulo: `Desinstalar "${plugin.name}"`,
    texto: "Se saca el archivo de la carpeta de plugins y sus tools dejan de existir: los flujos que los usen pasan a marcar error. " +
      "Sus settings e items quedan en la base, por si vuelve a instalarse.",
    alConfirmar: async () => {
      await api.desinstalarPlugin(plugin.name);
      confirmacion = `Se desinstaló "${plugin.name}".`;
      irA("plugins");
      await montar(shell, []);
    },
  });
}

// ── Pantalla del plugin ─────────────────────────────────────────────────

async function dibujarPlugin(plugin) {
  const estado = estadoDe(plugin);
  const faltan = faltantesDe(plugin);

  const partes = [
    h("div", { class: "cabecera", style: { marginBottom: "16px" } }, [
      h("div", { style: { minWidth: "0" } }, [
        h("div", { style: { display: "flex", alignItems: "center", gap: "9px" } }, [
          h("div", { class: "titulo", text: plugin.label || plugin.name }),
          h("span", { class: "chip-id", text: plugin.name }),
          // El núcleo no lleva badge: diría "núcleo" al lado de un título que
          // ya dice Núcleo y de un chip que ya dice core.
          estado.texto ? h("span", { class: estado.clase, text: estado.texto }) : null,
        ]),
        plugin.doc ? h("div", { class: "subtitulo", text: plugin.doc }) : null,
        h("div", { class: "mono", style: { fontSize: "11px", color: "var(--texto-4)", marginTop: "5px" },
                   text: `v${plugin.version || "0.0.0"} · ${plugin.source}` }),
      ]),
      esInstalado(plugin)
        ? h("button", { class: "btn", text: "Desinstalar", title: `Vive en ${instalacion.plugins_dir}`, onClick: () => desinstalar(plugin) })
        : null,
    ]),
  ];

  if (confirmacion) {
    partes.push(aviso("ok", confirmacion, null));
    confirmacion = null;
  }

  if (faltan.length) {
    partes.push(aviso("falta", `Falta ${faltan.length === 1 ? "1 valor obligatorio" : `${faltan.length} valores obligatorios`}`,
      h("div", {}, [
        `Los ${(plugin.tools || []).length} tools de este plugin fallan al ejecutar hasta que se complete: `,
        h("span", { class: "mono", text: faltan.map((f) => f.label || f.key).join(", ") }),
        ".",
      ])));
  }

  partes.push(...seccionSettings(plugin, faltan));
  for (const recurso of plugin.resources || []) partes.push(await seccionResource(plugin, recurso));
  partes.push(...seccionAcciones(plugin));
  partes.push(...seccionTools(plugin));
  partes.push(notaDelEsquema());

  poner(shell.vista, h("div", { class: "columna" }, partes.filter(Boolean)));
}

// ── Configuración ───────────────────────────────────────────────────────

function seccionSettings(plugin, faltan) {
  const settings = plugin.settings || [];

  if (!settings.length) {
    return [
      h("div", { class: "seccion" }, [h("span", { text: "Configuración" })]),
      h("div", { class: "tarjeta" }, [
        h("div", { class: "tabla__vacia" }, [
          "Este plugin no declara ningún setting.",
          h("br"),
          "No hay nada que configurar.",
        ]),
      ]),
    ];
  }

  const claves = faltan.map((f) => f.key);
  // Los settings se agrupan por `group`, que lo declara el plugin.
  const grupos = new Map();
  for (const s of settings) {
    const g = s.group || "";
    if (!grupos.has(g)) grupos.set(g, []);
    grupos.get(g).push(s);
  }

  const formularios = [];
  const tarjeta = h("div", { class: "tarjeta" });
  for (const [nombre, delGrupo] of grupos) {
    if (nombre) {
      tarjeta.appendChild(h("div", { class: "tarjeta__cabecera", text: nombre.toUpperCase() }));
    }
    const form = crearFormulario(delGrupo, config.values || {}, { faltantes: claves });
    formularios.push(form);
    tarjeta.appendChild(form.elemento);
  }

  const mensaje = h("span", { style: { fontSize: "11.5px" } });
  const guardar = h("button", { class: "btn btn--primario", text: "Guardar", onClick: async () => {
    guardar.disabled = true;
    mensaje.textContent = "";
    mensaje.style.color = "";
    try {
      const valores = Object.assign({}, ...formularios.map((f) => f.leer()));
      await api.guardarConfig(valores);
      // PATCH /config devuelve `values` sin los defaults del manifest, que el
      // GET sí trae. Se relee para no quedar con una vista incompleta.
      config = await api.config();
      confirmacion = "Configuración guardada.";
      await dibujarPlugin(plugin);
      dibujarLateral(catalogo.plugins, plugin);
    } catch (e) {
      mensaje.textContent = e.message;
      mensaje.style.color = "var(--rojo)";
      guardar.disabled = false;
    }
  }});

  tarjeta.appendChild(h("div", { class: "tarjeta__pie" }, [guardar, mensaje]));

  return [h("div", { class: "seccion" }, [h("span", { text: "Configuración" })]), tarjeta];
}

// ── Colecciones ─────────────────────────────────────────────────────────

async function seccionResource(plugin, recurso) {
  let datos;
  try {
    datos = await api.resource(plugin.name, recurso.name);
  } catch (e) {
    return h("div", {}, [
      h("div", { class: "seccion" }, [h("span", { text: recurso.label })]),
      aviso("error", "No se pudo leer la colección", e.message),
    ]);
  }

  const claveDe = recurso.key_field || "name";
  const items = datos.items || [];

  // Se muestran las tres primeras columnas del esquema, más la clave. Ver los
  // demás campos es abrir el item: una tabla con doce columnas no se lee.
  const columnas = [
    { clave: claveDe, label: "Nombre", ancho: "230px", peso: "600" },
    ...(recurso.fields || []).slice(0, 3).map((f) => ({
      clave: f.name, label: f.label || f.name, mono: true,
      ancho: f.type === "enum" ? "110px" : null,
      render: (fila) => {
        if (fila._error) return "—";
        const v = fila[f.name];
        if (v === undefined || v === null || v === "") return "—";
        return typeof v === "object" ? JSON.stringify(v) : String(v);
      },
    })),
    {
      clave: "_acciones", label: "", ancho: "122px",
      render: (fila) => h("div", { style: { display: "flex", gap: "6px" } }, [
        h("button", { class: "btn btn--chico", text: "Editar",
                      onClick: () => irA("plugins", plugin.name, recurso.name, String(fila[claveDe])) }),
        h("button", { class: "btn btn--chico", title: "Eliminar", style: { color: "var(--rojo)" },
                      onClick: () => confirmar({
                        titulo: `Eliminar ${recurso.item_label || "el item"}`,
                        texto: `Se elimina "${fila[claveDe]}". Los flujos que lo llamen por ese nombre van a fallar.`,
                        alConfirmar: async () => {
                          await api.borrarItem(plugin.name, recurso.name, fila[claveDe]);
                          confirmacion = `Se eliminó "${fila[claveDe]}".`;
                          await dibujarPlugin(plugin);
                        },
                      }) }, [icono(ICONOS.basura, 12, 2)]),
      ]),
    },
  ];

  const conError = items.filter((i) => i._error);

  return h("div", {}, [
    h("div", { class: "seccion" }, [
      h("span", {}, [recurso.label, h("span", { class: "seccion__suave", text: " — colección del plugin" })]),
      h("button", { class: "btn btn--primario", text: `+ ${recurso.item_label || "Nuevo"}`,
                    onClick: () => irA("plugins", plugin.name, recurso.name, "_nuevo") }),
    ]),
    conError.length
      ? aviso("error", `${conError.length} item(s) no se pudieron leer`,
              conError.map((i) => `${i[claveDe]}: ${i._error}`).join(" · "))
      : null,
    tabla(columnas, items, {
      vacio: h("div", {}, [
        `Todavía no hay ${recurso.label.toLowerCase()}.`,
        recurso.doc ? h("div", { style: { marginTop: "6px", fontSize: "11.5px" }, text: recurso.doc }) : null,
      ]),
    }),
    // El doc va abajo sólo cuando hay filas: con la tabla vacía ya lo dice el
    // propio vacío, y aparecía dos veces.
    recurso.doc && items.length ? h("div", { class: "tabla__pie", text: recurso.doc }) : null,
  ]);
}

/**
 * Qué Action sirve para "probar" el formulario de este resource antes de
 * guardarlo — como hacía el wizard viejo con una fuente.
 *
 * No hay un vínculo explícito en el esquema entre una Action y un Resource:
 * `Action.resource` significa otra cosa (corre sobre un item ya guardado, el
 * botón sale en su fila del ABM — es el caso de "test" sobre una conexión ya
 * guardada). Una Action *suelta* (sin `resource`) sirve para probar antes de
 * guardar sólo si el formulario del resource le puede dar todo lo que pide:
 * cada param obligatorio tiene que ser un campo real de este resource.
 *
 * Un plugin puede declarar más de una Action así — "sources" y "actions" acá
 * mismo comparten nombres de campo (url, method, headers…) y cada uno tiene
 * la suya. Entre las candidatas gana la que más se parece al formulario
 * (índice de Jaccard entre sus params y los campos del resource), así que
 * "actions" no termina probándose con la Action pensada para "sources" sólo
 * porque también tiene "url". Con eso alcanza para encontrarla sin que esta
 * pantalla conozca "connections" ni un nombre de Action por nombre.
 */
function accionDePrueba(plugin, recurso) {
  const campos = new Set((recurso.fields || []).map((f) => f.name));
  let mejor = null;
  let mejorPuntaje = 0;

  for (const a of plugin.actions || []) {
    if (a.resource) continue;
    const params = a.params || [];
    if (!params.length) continue;
    if (!params.every((p) => !p.required || campos.has(p.name))) continue;

    const nombres = new Set(params.map((p) => p.name));
    const compartidos = [...nombres].filter((n) => campos.has(n)).length;
    if (!compartidos) continue;
    const union = new Set([...nombres, ...campos]).size;
    const puntaje = compartidos / union;

    if (puntaje > mejorPuntaje) {
      mejor = a;
      mejorPuntaje = puntaje;
    }
  }
  return mejor;
}

/** Params de la Action que no son un campo del resource: hay que pedirlos aparte. */
function accionExtras(accion, recurso) {
  const campos = new Set((recurso.fields || []).map((f) => f.name));
  return (accion.params || []).filter((p) => !campos.has(p.name));
}

/** Los valores del formulario (y del mini-formulario de extras) que la Action pide. */
function paramsParaAccion(form, accion, extrasForm) {
  const valores = { ...form.leer(), ...(extrasForm ? extrasForm.leer() : {}) };
  const params = {};
  for (const p of accion.params) {
    if (valores[p.name] !== undefined) params[p.name] = valores[p.name];
  }
  return params;
}

// ── Acciones sueltas, y la vista que declaran ───────────────────────────

/**
 * Las Actions que no son el botón "Probar" de ninguna colección.
 *
 * Hasta acá una Action sólo tenía lugar adentro del formulario de un item
 * (`accionDePrueba`), así que una que no es "probar esto antes de guardar" —
 * comparar contra otro Bot, migrar, listar lo que hay del otro lado— no se
 * podía disparar desde ningún lado: existía en el manifest y no en la pantalla.
 *
 * Cuáles quedan acá se decide por descarte y no por una marca nueva en el
 * esquema: las que `accionDePrueba` ya eligió para alguna colección se dibujan
 * allá, y el resto acá. Así no hay que tocar el núcleo para que una Action
 * tenga dónde vivir, y ninguna aparece dos veces.
 */
function seccionAcciones(plugin) {
  const comoPrueba = new Set(
    (plugin.resources || [])
      .map((r) => accionDePrueba(plugin, r))
      .filter(Boolean)
      .map((a) => a.name));
  const sueltas = (plugin.actions || []).filter((a) => !a.resource && !comoPrueba.has(a.name));
  if (!sueltas.length) return [];

  return [
    h("div", { class: "seccion" }, [h("span", { text: "Acciones" })]),
    ...sueltas.map((accion) => tarjetaDeAccion(plugin, accion)),
  ];
}

function tarjetaDeAccion(plugin, accion) {
  const form = (accion.params || []).length ? crearFormulario(accion.params) : null;
  const resultado = h("div", { style: { marginTop: "10px" } });

  // `cual` deja que la vista de un resultado dispare **otra** Action del mismo
  // plugin —comparar y después migrar lo tildado— sin que esta pantalla sepa
  // cómo se llama ninguna: el nombre lo pone el resultado.
  const correr = async (params, cual = accion.name) => {
    poner(resultado, h("div", { class: "cargando", text: "Ejecutando…" }));
    try {
      const resp = await api.ejecutarAccion(plugin.name, cual, params);
      poner(resultado, dibujarResultadoDeAccion(resp.result, plugin, correr));
    } catch (e) {
      poner(resultado, aviso("error", "No se pudo ejecutar", e.message));
    }
  };

  const boton = h("button", {
    class: accion.dangerous ? "btn" : "btn btn--primario",
    text: accion.label || accion.name,
    style: accion.dangerous ? { color: "var(--rojo)" } : null,
    onClick: () => {
      let params = {};
      try {
        if (form) params = form.leer();
      } catch (e) {
        return poner(resultado, aviso("error", "Falta completar algo", e.message));
      }
      // Igual que cuando la dispara una selección: una Action `dangerous`
      // pregunta antes. Sin esto, la misma Action confirmaba si se llegaba
      // desde una tabla y no confirmaba si se apretaba su propio botón — que
      // es el camino más fácil de apretar sin querer.
      if (!accion.dangerous) return correr(params);
      confirmar({
        titulo: accion.label || accion.name,
        texto: accion.doc || "Esta acción escribe. No se puede deshacer desde acá.",
        botonTexto: "Sí, hacerlo",
        alConfirmar: () => correr(params),
      });
    },
  });

  return h("div", { class: "tarjeta", style: { padding: "13px 16px", marginBottom: "8px" } }, [
    accion.doc ? h("div", { class: "campo__ayuda", style: { marginBottom: "9px" }, text: accion.doc }) : null,
    form ? form.elemento : null,
    h("div", { style: { marginTop: "9px" } }, [boton]),
    resultado,
  ].filter(Boolean));
}

/**
 * El resultado de una Action, dibujado como la propia Action lo declara.
 *
 * `outputs.vista` es lo que deja que un plugin arme una pantalla útil sin que
 * esta vista lo conozca por nombre y sin escribirle una pantalla a medida a
 * cada uno. Va en el **resultado** y no en el manifest a propósito: las
 * columnas de una comparación dependen de lo que se comparó, así que no se
 * pueden declarar antes de correrla.
 *
 * Todo lo que el plugin manda se dibuja como texto: `h()` nunca usa
 * `innerHTML`, así que un valor con `<` no ejecuta nada.
 *
 * `_nota` y `_elegible` son las dos claves reservadas de una fila. Van con `_`
 * porque el núcleo ya marca así lo suyo en los items de una colección
 * (`_updated_at`, `_error`), y una fila puede ser justamente uno de esos items
 * pasado tal cual. Si alguna vez se filtra `_*` en bloque en algún lado, esto
 * se apaga sin avisar.
 */
function dibujarVista(vista, plugin, correr) {
  const filas = Array.isArray(vista.filas) ? vista.filas : [];
  const claveDe = vista.clave || "clave";
  const seleccion = vista.seleccion || null;
  const elegidas = new Set();

  const columnas = (vista.columnas || []).map((c) => ({
    clave: c.campo, label: c.label || c.campo, ancho: c.ancho || null,
    render: (fila) => {
      const v = fila[c.campo];
      if (v === undefined || v === null || v === "") return "—";
      const texto = typeof v === "object" ? JSON.stringify(v) : String(v);
      // La nota del plugin va pegada a su fila, en la primera columna: es
      // donde explica por qué una fila no se puede elegir — el caso de un
      // item con campos secretos, que no se puede comparar con nada.
      if (c === (vista.columnas || [])[0] && fila._nota) {
        return h("div", {}, [
          h("div", { text: texto }),
          h("div", { class: "campo__ayuda", style: { marginTop: "2px" }, text: fila._nota }),
        ]);
      }
      return texto;
    },
  }));

  // La Action de seguimiento, para saber si pide confirmación. `dangerous` ya
  // existía en el esquema; acá se usa para lo que es —"esto escribe en otra
  // máquina"— y el `aviso` queda para lo propio de esta selección. Son dos
  // cosas distintas a propósito: el aviso se lee **mientras** se tilda, la
  // confirmación es el último paso. Dos diálogos seguidos no harían esto más
  // seguro; entrenarían a pasar de largo los dos.
  const destinoDeLaSeleccion = seleccion
    ? (plugin.actions || []).find((a) => a.name === seleccion.accion)
    : null;

  const disparar = () => {
    if (!elegidas.size) return;
    correr({ ...(seleccion.params || {}), [seleccion.param]: [...elegidas] }, seleccion.accion);
  };

  const boton = seleccion
    ? h("button", {
        class: "btn btn--primario", text: seleccion.etiqueta || "Aplicar", disabled: true,
        onClick: () => {
          if (!destinoDeLaSeleccion || !destinoDeLaSeleccion.dangerous) return disparar();
          confirmar({
            titulo: seleccion.etiqueta || destinoDeLaSeleccion.label,
            texto: `Se van a escribir ${elegidas.size} en la otra punta, pisando lo que haya.`,
            botonTexto: "Sí, hacerlo",
            alConfirmar: disparar,
          });
        },
      })
    : null;

  const refrescarBoton = () => {
    if (!boton) return;
    boton.disabled = elegidas.size === 0;
    boton.textContent = elegidas.size
      ? `${seleccion.etiqueta || "Aplicar"} (${elegidas.size})`
      : (seleccion.etiqueta || "Aplicar");
  };

  if (seleccion) {
    columnas.unshift({
      clave: "_elegir", label: "", ancho: "34px",
      render: (fila) => {
        if (fila._elegible === false) return "";
        const caja = h("input", {
          type: "checkbox",
          onChange: (e) => {
            if (e.target.checked) elegidas.add(fila[claveDe]);
            else elegidas.delete(fila[claveDe]);
            refrescarBoton();
          },
        });
        return caja;
      },
    });
  }

  const partes = [
    vista.titulo ? h("div", { class: "campo__ayuda", style: { marginBottom: "7px" }, text: vista.titulo }) : null,
    h("div", { style: { overflow: "auto" } }, [
      tabla(columnas, filas, { vacio: vista.vacio || "No hay nada que mostrar." }),
    ]),
  ];

  if (seleccion) {
    // El aviso va **arriba** del botón y siempre visible, no en un modal de
    // confirmación: lo que hay que entender acá —que se pisa lo del otro lado,
    // que un secreto no se pudo comparar— tiene que estar a la vista mientras
    // alguien tilda, no aparecer cuando ya decidió.
    partes.push(h("div", { style: { marginTop: "10px" } }, [
      seleccion.aviso ? aviso("falta", seleccion.aviso, null) : null,
      h("div", { style: { marginTop: "8px" } }, [boton]),
    ].filter(Boolean)));
  }

  return h("div", {}, partes.filter(Boolean));
}

/** El resultado de una Action: su vista declarada, o el aviso de siempre. */
function dibujarResultadoDeAccion(resultado, plugin, correr) {
  if (resultado.status !== "ok") {
    return aviso("error", "No salió bien", resultado.message || "Sin detalle.");
  }
  const vista = resultado.outputs && resultado.outputs.vista;
  if (vista && vista.tipo === "tabla") {
    const correrOtra = async (params, nombre) => {
      const otra = (plugin.actions || []).find((a) => a.name === nombre);
      if (!otra) return;
      await correr(params, nombre);
    };
    return h("div", {}, [
      resultado.message ? aviso("ok", resultado.message, null) : null,
      h("div", { style: { marginTop: resultado.message ? "10px" : "0" } },
        [dibujarVista(vista, plugin, correrOtra)]),
    ].filter(Boolean));
  }
  return dibujarResultadoDePrueba(resultado);
}

/** El resultado de una Action, mostrado como filas si las trae, o como aviso. */
function dibujarResultadoDePrueba(resultado) {
  if (resultado.status !== "ok") {
    return aviso("error", "La prueba falló", resultado.message || "Sin detalle.");
  }

  const filas = resultado.outputs.rows;
  if (!Array.isArray(filas)) {
    const otros = Object.keys(resultado.outputs).length
      ? h("pre", { class: "mono", style: { fontSize: "11px", whiteSpace: "pre-wrap", margin: "7px 0 0" },
                   text: JSON.stringify(resultado.outputs, null, 2) })
      : null;
    return aviso("ok", resultado.message || "Prueba exitosa", otros);
  }

  const total = resultado.outputs.total ?? filas.length;
  // Hasta 7 columnas y 5 filas: esto confirma que los datos son los
  // esperados, no reemplaza la grilla real de la fuente.
  const columnas = Object.keys(filas[0] || {}).slice(0, 7).map((c) => ({
    clave: c, label: c, ancho: "130px",
    render: (fila) => {
      const v = fila[c];
      if (v === undefined || v === null || v === "") return "—";
      return typeof v === "object" ? JSON.stringify(v) : String(v);
    },
  }));

  return h("div", {}, [
    aviso("ok", `${filas.length} fila${filas.length === 1 ? "" : "s"} leída${filas.length === 1 ? "" : "s"} de ${total}`, null),
    h("div", { style: { overflow: "auto", marginTop: "8px" } }, [
      tabla(columnas, filas.slice(0, 5), { vacio: "Sin filas." }),
    ]),
  ]);
}

/** La columna que más se parece a un identificador, como sugerencia. */
function adivinarClave(columnas) {
  const preferidas = ["id", "id_externo", "case_id", "codigo", "clave", "key"];
  const exacta = columnas.find((c) => preferidas.includes(c.toLowerCase()));
  if (exacta) return exacta;
  const contiene = columnas.find((c) => /(^|_)id($|_)/i.test(c));
  return contiene || columnas[0] || "";
}

/**
 * Completa el campo "key_field" del formulario con una sugerencia sacada de
 * las filas que trajo la prueba — lo mismo que hacía el wizard viejo. Sólo si
 * está vacío: no le pisa a nadie una elección ya hecha a mano.
 */
function sugerirClaveDesdeFilas(form, filas) {
  if (!Array.isArray(filas) || !filas.length) return;
  const campo = form.campos.find((c) => c.clave === "key_field");
  if (!campo) return;
  const entrada = campo.elemento.querySelector(".entrada");
  if (!entrada || entrada.value.trim()) return;
  entrada.value = adivinarClave(Object.keys(filas[0]));
}

/** El alta y la edición de un item, en su propia página: mismo formulario, dos esquemas. */
async function dibujarItem(plugin, recurso, clave) {
  const claveDe = recurso.key_field || "name";
  const esNuevo = clave === null;
  const volver = () => irA("plugins", plugin.name);

  let item = null;
  if (!esNuevo) {
    let datos;
    try {
      datos = await api.resource(plugin.name, recurso.name);
    } catch (e) {
      return poner(shell.vista, aviso("error", "No se pudo leer la colección", e.message));
    }
    item = (datos.items || []).find((i) => String(i[claveDe]) === clave) || null;
    if (!item) {
      return poner(shell.vista, aviso("error", `No existe "${clave}"`,
        `No hay ningún ${(recurso.item_label || "item").toLowerCase()} con ese nombre en ${recurso.label}.`));
    }
  }

  const campoClave = crearCampo(
    { name: claveDe, type: "str", label: "Nombre", required: true,
      doc: esNuevo
        ? "Es la clave: los flujos llaman a esto por su nombre."
        : "La clave no se edita. Renombrar sería dar de alta otro y borrar este, y los flujos que lo usen dejarían de encontrarlo." },
    esNuevo ? "" : item[claveDe]);
  if (!esNuevo) campoClave.elemento.querySelector("input").disabled = true;

  const form = crearFormulario(recurso.fields || [], item || {});
  const error = h("div", { class: "aviso aviso--error", style: { display: "none" } });
  const resultado = h("div", { style: { marginTop: "12px" } });

  const accion = accionDePrueba(plugin, recurso);
  // Params que la Action pide y el resource no tiene como campo propio — por
  // ejemplo "vars", los valores para resolver un {id_externo} incrustado en la
  // URL o el payload. En un run real salen del contexto del caso; acá los da
  // quien está probando, así que necesitan su propio mini-formulario.
  const extras = accion ? accionExtras(accion, recurso) : [];
  const extrasForm = extras.length ? crearFormulario(extras) : null;

  const botonProbar = accion ? h("button", {
    class: "btn", text: "Probar",
    title: `Ejecuta la Action "${accion.label}" con lo que hay cargado, sin guardar nada.`,
    onClick: async () => {
      poner(resultado, h("div", { class: "cargando", text: "Probando…" }));
      let params;
      try {
        params = paramsParaAccion(form, accion, extrasForm);
      } catch (e) {
        return poner(resultado, aviso("error", "No se pudo probar", e.message));
      }
      try {
        const resp = await api.ejecutarAccion(plugin.name, accion.name, params);
        poner(resultado, dibujarResultadoDePrueba(resp.result));
        if (resp.result.status === "ok") sugerirClaveDesdeFilas(form, resp.result.outputs.rows);
      } catch (e) {
        poner(resultado, aviso("error", "No se pudo probar", e.message));
      }
    },
  }) : null;

  const botonGuardar = h("button", {
    class: "btn btn--primario", text: esNuevo ? "Guardar" : "Guardar cambios",
    onClick: async () => {
      error.style.display = "none";
      try {
        const claveVal = campoClave.leer().trim();
        if (!claveVal) throw new Error("El nombre es obligatorio.");
        await api.guardarItem(plugin.name, recurso.name, claveVal, form.leer());
        confirmacion = esNuevo ? `Se creó "${claveVal}".` : `Se guardó "${claveVal}".`;
        volver();
      } catch (e) {
        error.style.display = "";
        poner(error, h("div", { class: "aviso__cuerpo", text: e.message }));
      }
    },
  });

  poner(shell.vista, h("div", { class: "columna" }, [
    h("button", { class: "btn btn--chico", text: "← Volver", style: { marginBottom: "9px" }, onClick: volver }),
    h("div", { class: "cabecera", style: { marginBottom: "14px" } }, [
      h("div", { style: { minWidth: "0" } }, [
        h("div", { class: "titulo", text: esNuevo ? (recurso.item_label || "Nuevo") : clave }),
        h("div", { class: "subtitulo", text:
          `${plugin.name} › ${recurso.name} · los campos salen del esquema que declara el plugin` }),
      ]),
    ]),
    error,
    h("div", { class: "tarjeta" }, [campoClave.elemento, form.elemento]),
    extrasForm ? h("div", { class: "seccion" }, [h("span", { text: "Para probar" })]) : null,
    extrasForm ? h("div", { class: "tarjeta" }, [extrasForm.elemento]) : null,
    h("div", { style: { display: "flex", gap: "8px", marginTop: "12px" } },
      [botonGuardar, botonProbar, h("button", { class: "btn", text: "Cancelar", onClick: volver })].filter(Boolean)),
    resultado,
  ]));
}

// ── Tools y nota final ──────────────────────────────────────────────────

function seccionTools(plugin) {
  const ids = plugin.tools || [];
  return [
    h("div", { class: "seccion" }, [h("span", { text: "Tools que aporta" })]),
    h("div", {}, [
      h("div", { class: "fichas" }, ids.map((id) => h("span", { class: "ficha", text: id }))),
      h("div", { class: "tabla__pie" },
        ["Los flujos los referencian por este id. Si se desinstala el plugin, los flujos que los usen aparecen en el diagnóstico."]),
    ]),
  ];
}

function notaDelEsquema() {
  return h("div", { style: { marginTop: "18px", paddingTop: "11px",
                             borderTop: "1px solid var(--borde-2)", fontSize: "11.5px",
                             color: "var(--texto-3)", lineHeight: "1.55" } }, [
    "Ni los campos ni las colecciones de esta pantalla están escritos en el front: salen de ",
    h("span", { class: "mono", text: "GET /tools" }),
    " — cada plugin declara sus settings y sus resources con el tipo, si son obligatorios y su ayuda.",
  ]);
}

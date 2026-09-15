/*
  El wizard: cuatro pasos, un estado, sin framework.

  Cada paso declara `entrar` (qué pedir al servidor al llegar) y `puedeSeguir`
  (si el botón se habilita). El resto es render.
*/

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const estado = {
  paso: 1,
  ruta: "",
  sugerida: "",
  revision: null,
  chequeos: [],
  plan: null,
  instalado: null,
  trabajando: false,
};

const TOTAL = 4;

async function api(ruta, cuerpo) {
  const opciones = cuerpo
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) }
    : {};
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json().catch(() => ({ error: "respuesta ilegible del instalador" }));
  if (!respuesta.ok) throw new Error(datos.error || `error ${respuesta.status}`);
  return datos;
}

function texto(padre, etiqueta, clase, contenido) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (contenido !== undefined) el.textContent = contenido;
  padre.appendChild(el);
  return el;
}

function aviso(padre, nivel, titulo, detalle) {
  const caja = texto(padre, "div", `aviso ${nivel}`);
  texto(caja, "span", "icono", { ok: "✓", warn: "!", error: "✕", info: "i" }[nivel] || "i");
  const cuerpo = texto(caja, "div");
  texto(cuerpo, "b", null, titulo);
  if (detalle) texto(cuerpo, "div", "detalle", detalle);
  return cuerpo;
}

/* ── Pasos ─────────────────────────────────────────────────────────── */

const PASOS = {
  1: {
    async entrar() {
      if (!estado.sugerida) {
        const s = await api("/api/sugerencia");
        estado.sugerida = s.ruta;
        $("#usarSugerida").textContent = s.ruta;
        if (!estado.ruta) {
          estado.ruta = s.ruta;
          $("#ruta").value = s.ruta;
        }
      }
      await revisarRuta();
    },
    puedeSeguir: () => estado.revision?.valida && !estado.revision.instalacion_previa.length,
  },

  2: {
    async entrar() {
      $("#chequeos").textContent = "Revisando…";
      const r = await api("/api/maquina", { ruta: estado.ruta });
      estado.chequeos = r.chequeos;
      pintarChequeos();
    },
    // Un warn no bloquea; un error sí. Instalar sobre una máquina a la que le
    // falta algo produce una instalación rota que parece sana.
    puedeSeguir: () => estado.chequeos.length && !estado.chequeos.some((c) => c.nivel === "error"),
  },

  3: {
    async entrar() {
      estado.plan = await api("/api/plan", { ruta: estado.ruta });
      pintarLimites();
    },
    puedeSeguir: () => !!estado.plan,
  },

  4: {
    async entrar() {
      pintarResumen();
    },
    puedeSeguir: () => !estado.instalado,
  },
};

/* ── Paso 1 ────────────────────────────────────────────────────────── */

let temporizador = null;

function revisarPronto() {
  clearTimeout(temporizador);
  temporizador = setTimeout(revisarRuta, 250);
}

async function revisarRuta() {
  estado.ruta = $("#ruta").value;
  try {
    estado.revision = await api("/api/revisar", { ruta: estado.ruta });
  } catch (e) {
    estado.revision = { valida: false, problemas: [e.message], instalacion_previa: [] };
  }
  pintarRevision();
  refrescarBotones();
}

function pintarRevision() {
  const caja = $("#revision");
  caja.textContent = "";
  const r = estado.revision;
  if (!r) return;

  for (const problema of r.problemas) aviso(caja, "error", problema);

  if (r.instalacion_previa?.length) {
    aviso(
      caja, "error",
      "Ya hay una instalación de Bot en esa carpeta",
      `Se encontró: ${r.instalacion_previa.join(", ")}. Elegí otra carpeta, o movela a un lado antes de instalar.`
    );
    return;
  }

  if (!r.valida) return;

  if (r.crea_carpetas) {
    aviso(caja, "info", "Se va a crear la carpeta", r.ruta);
  } else if (r.vacia) {
    aviso(caja, "ok", "La carpeta existe y está vacía", r.ruta);
  } else {
    aviso(
      caja, "warn",
      "La carpeta existe y tiene cosas adentro",
      "No se borra nada: Bot agrega lo suyo al lado. Aun así conviene una carpeta propia."
    );
  }
}

/* ── Paso 2 ────────────────────────────────────────────────────────── */

function pintarChequeos() {
  const caja = $("#chequeos");
  caja.textContent = "";
  for (const c of estado.chequeos) {
    const cuerpo = aviso(caja, c.nivel, `${c.nombre} — ${c.mensaje}`);
    for (const linea of c.detalle) texto(cuerpo, "div", "detalle mono", linea);
    if (c.arreglo && c.nivel !== "ok") texto(cuerpo, "div", "arreglo", c.arreglo);
  }
}

/* ── Paso 3 ────────────────────────────────────────────────────────── */

function pintarLimites() {
  const caja = $("#limites");
  caja.textContent = "";
  for (const l of estado.plan.limites) {
    const fila = texto(caja, "div", "limite");
    texto(fila, "div", "que", l.que);
    texto(fila, "span", `pastilla ${l.estado}`, l.estado);
    texto(fila, "div", "detalle", l.detalle);
  }

  const p = estado.plan;
  const nombre = p.raiz.split(/[\\/]/).pop();
  $("#arbol").innerHTML =
    `${escapar(nombre)}/\n` +
    `├── boot.env      <span class="comentario">cómo arranca</span>\n` +
    `├── data/         <span class="comentario">la base y la llave · fuera de la caja</span>\n` +
    `└── workspace/    <span class="comentario">la caja · lo único que los flujos tocan</span>`;
}

function escapar(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ── Paso 4 ────────────────────────────────────────────────────────── */

function pintarResumen() {
  const dl = $("#resumen");
  dl.textContent = "";
  const p = estado.plan;
  const filas = [
    ["Carpeta", p.raiz],
    ["Base de datos", p.base],
    ["Espacio de trabajo", p.caja],
    ["Plugins", p.plugins],
  ];
  for (const [clave, valor] of filas) {
    const fila = texto(dl, "div");
    texto(fila, "dt", null, clave);
    texto(fila, "dd", null, valor);
  }
}

async function instalar() {
  trabajando(true, "Instalando…");
  try {
    estado.instalado = await api("/api/instalar", { ruta: estado.ruta });
    pintarResultado();
  } catch (e) {
    mostrarError(e.message);
  } finally {
    trabajando(false);
  }
}

function pintarResultado() {
  $("#antesDeInstalar").classList.add("oculto");
  const caja = $("#resultado");
  caja.classList.remove("oculto");
  caja.textContent = "";

  const r = estado.instalado;

  const listo = texto(caja, "div", "listo");
  texto(listo, "span", "tilde", "✓");
  texto(listo, "h1", null, "Bot quedó instalado");

  texto(caja, "p", "bajada",
    "La base está creada y la configuración de arranque escrita. " +
    "Todavía no hay ningún plugin, así que Bot no sabe hacer nada: eso se instala desde la app, " +
    "que se abre con el botón de abajo.");

  texto(caja, "h2", null, "Guardá esto");
  const cuerpo = aviso(caja, "warn",
    "La llave de cifrado es lo único que no se puede recuperar",
    "Con ella se cifran las contraseñas y claves de API que cargues. " +
    "Si se pierde el archivo, esos secretos no se pueden volver a leer — ni siquiera con un backup de la base, " +
    "porque la llave se guarda aparte justamente para eso.");
  texto(cuerpo, "div", "detalle mono", r.creado.llave);

  texto(caja, "h2", null, "Quedó así");
  const dl = texto(caja, "dl", "resumen");
  const filas = [
    ["Carpeta", r.raiz],
    ["Base de datos", r.creado.base],
    ["Espacio de trabajo", r.creado.caja],
    ["Plugins", r.creado.plugins],
    ["Actores", r.actores.map((a) => `${a.name} (${a.kind})`).join(", ")],
  ];
  for (const [clave, valor] of filas) {
    const fila = texto(dl, "div");
    texto(fila, "dt", null, clave);
    texto(fila, "dd", null, valor);
  }

  texto(caja, "h2", null, "Para abrirlo otro día");
  texto(caja, "p", "bajada",
    r.anotada_en
      ? "La instalación quedó anotada: \"Abrir Bot\" en el menú Inicio —o python -m webapp— la abre sin preguntar."
      : "No se pudo anotar la instalación en la configuración del usuario: para abrirla hay que nombrarla.");
  texto(caja, "code", "comando", `python -m webapp --root "${r.raiz}"`);

  texto(caja, "h2", null, "Para verificarlo desde la consola");
  texto(caja, "code", "comando", `python -m backend.core --root "${r.raiz}" doctor`);

  if (r.sobrantes?.length) {
    texto(caja, "h2", null, "Atención");
    aviso(caja, "warn", "Hay claves de arranque que el núcleo no reconoce", r.sobrantes.join(", "));
  }
}

/* ── Navegación ────────────────────────────────────────────────────── */

async function ir(paso) {
  limpiarError();
  estado.paso = paso;

  $$(".paso").forEach((s) => s.classList.toggle("actual", +s.dataset.paso === paso));
  $$(".pasos li").forEach((li) => {
    const n = +li.dataset.paso;
    li.classList.toggle("actual", n === paso);
    li.classList.toggle("hecho", n < paso);
  });

  trabajando(true);
  try {
    await PASOS[paso].entrar();
  } catch (e) {
    mostrarError(e.message);
  } finally {
    trabajando(false);
  }
}

function refrescarBotones() {
  const listo = !!estado.instalado;
  // Instalado: "Atrás" pasa a ser "Cerrar" y el principal abre la app.
  $("#atras").disabled = estado.trabajando || (estado.paso === 1 && !listo);
  $("#atras").textContent = listo ? "Cerrar" : "Atrás";
  $("#siguiente").disabled = estado.trabajando || !PASOS[estado.paso].puedeSeguir();
  $("#siguiente").textContent = listo
    ? "Abrir Bot"
    : estado.paso === TOTAL
      ? "Instalar"
      : "Siguiente";
  if (listo) $("#siguiente").disabled = estado.trabajando;
}

function trabajando(si, etiqueta) {
  estado.trabajando = si;
  refrescarBotones();
  // Después de refrescar, que si no la etiqueta se pisa con la del estado.
  if (si && etiqueta) $("#siguiente").textContent = etiqueta;
}

function mostrarError(mensaje) {
  const caja = $("#error");
  caja.textContent = mensaje;
  caja.classList.remove("oculto");
}

function limpiarError() {
  $("#error").classList.add("oculto");
}

/* ── Arranque ──────────────────────────────────────────────────────── */

$("#ruta").addEventListener("input", revisarPronto);

$("#usarSugerida").addEventListener("click", (e) => {
  e.preventDefault();
  $("#ruta").value = estado.sugerida;
  revisarRuta();
});

$("#atras").addEventListener("click", () => {
  if (estado.instalado) return cerrar();
  ir(Math.max(1, estado.paso - 1));
});

/**
 * Después de instalar, el botón principal abre la app: el instalador lanza
 * la webapp contra la carpeta recién creada, espera a que responda, y esta
 * pestaña pasa a ser la app. El instalador se apaga solo después.
 */
async function abrirBot() {
  trabajando(true, "Abriendo Bot…");
  try {
    const r = await api("/api/abrir", { ruta: estado.instalado.raiz });
    // Apagar el instalador ya, antes de navegar: después de cambiar de página
    // no hay quién lo llame.
    api("/api/salir", {}).catch(() => {});
    window.location.replace(r.url);
  } catch (e) {
    mostrarError(e.message);
    trabajando(false);
  }
}

async function cerrar() {
  await api("/api/salir", {});
  document.body.innerHTML =
    '<p style="padding:40px;color:#5f6368">Listo. Ya podés cerrar esta pestaña.</p>';
}

$("#siguiente").addEventListener("click", async () => {
  if (estado.instalado) return abrirBot();
  if (estado.paso === TOTAL) return instalar();
  ir(estado.paso + 1);
});

ir(1);

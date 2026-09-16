/**
 * La única puerta al backend.
 *
 * Ningún otro módulo hace `fetch`. Así el manejo de errores, la base de la URL
 * y la forma de las respuestas están en un solo lugar — que es lo que permitió
 * borrar el front viejo sin tocar el núcleo.
 */

const BASE = "/api/core";

/** Un error que ya trae el mensaje del backend, listo para mostrar. */
export class ErrorApi extends Error {
  constructor(mensaje, status) {
    super(mensaje);
    this.name = "ErrorApi";
    this.status = status;
  }
}

async function pedir(ruta, { metodo = "GET", cuerpo, form } = {}) {
  let respuesta;
  try {
    // `form` es un FormData (subir un archivo): el navegador pone el
    // Content-Type con su boundary; ponerlo a mano lo rompe.
    respuesta = await fetch(BASE + ruta, {
      method: metodo,
      headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
      body: form ? form : (cuerpo ? JSON.stringify(cuerpo) : undefined),
    });
  } catch (e) {
    // El servidor no está, o se cayó a mitad. Decirlo así y no "Failed to fetch".
    throw new ErrorApi("No se pudo hablar con el servidor. ¿Está levantado?", 0);
  }

  const texto = await respuesta.text();
  let datos = null;
  try {
    datos = texto ? JSON.parse(texto) : null;
  } catch {
    // Una respuesta que no es JSON con 200 es un bug del servidor; con error,
    // suele ser una página de error de otra capa.
    if (respuesta.ok) throw new ErrorApi("El servidor devolvió algo que no es JSON", 200);
  }

  if (!respuesta.ok) {
    // FastAPI pone el mensaje en `detail`, y ese texto ya está escrito para que
    // lo lea una persona: se muestra tal cual, no se traduce ni se resume.
    let detalle = datos && (datos.detail || datos.message);
    let errores = [];
    // Un `detail` con forma {message, errors} (instalar un plugin): el mensaje
    // va como siempre y la lista queda aparte para mostrarla línea por línea.
    if (detalle && typeof detalle === "object") {
      errores = detalle.errors || [];
      detalle = detalle.message || JSON.stringify(detalle);
    }
    const error = new ErrorApi(detalle || `Error ${respuesta.status}`, respuesta.status);
    error.errores = errores;
    throw error;
  }
  return datos;
}

const codificar = (s) => encodeURIComponent(s);

export const api = {
  // Catálogo y salud
  tools: () => pedir("/tools"),
  doctor: () => pedir("/doctor"),
  // Qué tiene la instalación, en una mirada; y si está recién hecha.
  resumen: () => pedir("/overview"),

  // Configuración de la instancia
  config: () => pedir("/config"),
  guardarConfig: (values) => pedir("/config", { metodo: "PATCH", cuerpo: { values } }),

  // Variables y secretos. No hay un `get` de un secreto: el almacén es
  // write-only, así que el valor no existe del lado del navegador.
  env: () => pedir("/env"),
  guardarEnv: (nombre, value, secret) =>
    pedir(`/env/${codificar(nombre)}`, { metodo: "PUT", cuerpo: { value, secret } }),
  borrarEnv: (nombre) => pedir(`/env/${codificar(nombre)}`, { metodo: "DELETE" }),
  almacenamiento: () => pedir("/storage"),
  // El visor de la base: sólo lectura, y el servidor ya tapó los secretos.
  tablas: () => pedir("/storage/tables"),
  filasDeTabla: (tabla, { limit = 50, offset = 0 } = {}) =>
    pedir(`/storage/tables/${codificar(tabla)}?limit=${limit}&offset=${offset}`),

  // Plugins: instalar es dejar el archivo en plugins_dir, validado antes en
  // otro proceso, y recargar la instancia. Ver webapp/plugin_install.py.
  infoInstalacion: () => pedir("/plugins/install-info"),
  instalarPluginPorRuta: (path, { name, replace = false, offline = false } = {}) =>
    pedir("/plugins/install/path", { metodo: "POST", cuerpo: { path, name: name || null, replace, offline } }),
  instalarPluginArchivo: (archivo, { name, replace = false, offline = false } = {}) => {
    const form = new FormData();
    form.append("file", archivo, archivo.name);
    if (name) form.append("name", name);
    form.append("replace", replace ? "true" : "false");
    form.append("offline", offline ? "true" : "false");
    return pedir("/plugins/install/upload", { metodo: "POST", form });
  },
  desinstalarPlugin: (nombre) => pedir(`/plugins/${codificar(nombre)}`, { metodo: "DELETE" }),
  plantillaPlugin: (name, ports = []) => pedir("/plugins/template", { metodo: "POST", cuerpo: { name, ports } }),
  // Plugins en línea: el catálogo curado en GitHub (repo + rama por
  // instalación). Instalar baja la rama y pasa por el mismo camino que un
  // archivo subido. Ver webapp/plugin_catalog.py.
  catalogoPlugins: () => pedir("/plugins/catalog"),
  configurarCatalogoPlugins: (repo, branch) =>
    pedir("/plugins/catalog/config", { metodo: "PUT", cuerpo: { repo, branch } }),
  instalarDesdeCatalogo: (name, { offline = false } = {}) =>
    pedir("/plugins/catalog/install", { metodo: "POST", cuerpo: { name, offline } }),
  // Librerías Python que piden los plugins (requirements.txt) y el runtime
  // donde se instalan. Ver webapp/librerias.py.
  libreriasDePlugins: () => pedir("/plugins/libraries"),
  instalarLibreriasDe: (name, { offline = false } = {}) =>
    pedir("/plugins/libraries/install", { metodo: "POST", cuerpo: { name, offline } }),

  // Actualizaciones del núcleo (backend/) y de la web app (webapp/): releases
  // de GitHub, con el repo de cada componente guardado por instalación. Ver
  // webapp/updates.py. `componente` es "core" o "webapp".
  actualizaciones: () => pedir("/updates"),
  configurarActualizaciones: (repos) => pedir("/updates/config", { metodo: "PUT", cuerpo: repos }),
  releases: (componente, conPrueba = true) =>
    pedir(`/updates/releases?component=${componente}&prerelease=${conPrueba ? "true" : "false"}`),
  instalarRelease: (componente, tag) =>
    pedir("/updates/install/tag", { metodo: "POST", cuerpo: { tag, component: componente } }),
  instalarReleaseArchivo: (componente, archivo, tag = "") => {
    const form = new FormData();
    form.append("file", archivo, archivo.name);
    form.append("tag", tag);
    form.append("component", componente);
    return pedir("/updates/install/upload", { metodo: "POST", form });
  },
  revertirComponente: (componente) => pedir(`/updates/revert?component=${componente}`, { metodo: "POST" }),
  descartarAnterior: (componente) => pedir(`/updates/previous?component=${componente}`, { metodo: "DELETE" }),
  reiniciar: () => pedir("/updates/restart", { metodo: "POST" }),

  // Actores: quién ejecuta y qué puede. Identidad y política, no autenticación.
  // Sin `borrar`: la baja es lógica (enabled=false), porque los runs apuntan al
  // actor por nombre.
  usuarios: () => pedir("/users"),
  crearUsuario: (cuerpo) => pedir("/users", { metodo: "POST", cuerpo }),
  actualizarUsuario: (nombre, cuerpo) => pedir(`/users/${codificar(nombre)}`, { metodo: "PATCH", cuerpo }),
  agente: () => pedir("/agent"),
  agentProveedores: () => pedir("/agent/providers"),
  agentProveedorConfig: (id) => pedir(`/agent/providers/${codificar(id)}/config`),
  guardarAgentProveedorConfig: (id, notas) =>
    pedir(`/agent/providers/${codificar(id)}/config`, { metodo: "PUT", cuerpo: { notas } }),

  // Herramientas siempre permitidas (--allowedTools): una lista por
  // instalación — ver webapp/agent_settings.py.
  agentHerramientasPermitidas: () => pedir("/agent/allowed-tools"),
  guardarAgentHerramientasPermitidas: (value) =>
    pedir("/agent/allowed-tools", { metodo: "PUT", cuerpo: { value } }),

  // Colecciones de un plugin
  resource: (plugin, resource) => pedir(`/resources/${codificar(plugin)}/${codificar(resource)}`),
  guardarItem: (plugin, resource, clave, item) =>
    pedir(`/resources/${codificar(plugin)}/${codificar(resource)}/${codificar(clave)}`,
          { metodo: "PUT", cuerpo: { item } }),
  borrarItem: (plugin, resource, clave) =>
    pedir(`/resources/${codificar(plugin)}/${codificar(resource)}/${codificar(clave)}`,
          { metodo: "DELETE" }),

  // Acciones sueltas de un plugin ("probar", "previsualizar"): no son parte de
  // ningún run, las dispara una persona desde la pantalla del plugin.
  ejecutarAccion: (plugin, action, params = {}) =>
    pedir(`/actions/${codificar(plugin)}/${codificar(action)}`, { metodo: "POST", cuerpo: { params } }),

  // Fuentes de datos: viven en el resource `sources` del plugin `connections`
  // (webapp/connections/plugin.py) — no hay un endpoint propio de "fuentes".
  // El ABM ya lo cubre lo genérico (`resource`/`guardarItem`/`borrarItem`);
  // traer una página de filas es la misma Action `preview` que ya prueba el
  // formulario antes de guardar.
  fuentes: async () => (await pedir("/resources/connections/sources")).items,
  fuente: (nombre) => pedir(`/resources/connections/sources/${codificar(nombre)}`),
  filasDeFuente: (cfg, { search = "", filters = {}, limit, offset = 0 } = {}) =>
    pedir("/actions/connections/preview", {
      metodo: "POST",
      cuerpo: {
        params: {
          url: cfg.url, method: cfg.method, headers: cfg.headers, payload: cfg.payload,
          results_path: cfg.results_path, page_param: cfg.page_param,
          page_size_param: cfg.page_size_param, page_size: cfg.page_size,
          total_path: cfg.total_path,
          search: search || undefined, filters, limit: limit || cfg.page_size || 100, offset,
        },
      },
    }),
  borrarFuente: (nombre) =>
    pedir(`/resources/connections/sources/${codificar(nombre)}`, { metodo: "DELETE" }),

  // Workflows
  workflows: () => pedir("/workflows"),
  workflow: (nombre) => pedir(`/workflows/${codificar(nombre)}`),
  grafo: (nombre) => pedir(`/workflows/${codificar(nombre)}/graph`),
  guardarWorkflow: (nombre, cuerpo) =>
    pedir(`/workflows/${codificar(nombre)}`, { metodo: "PUT", cuerpo }),
  borrarWorkflow: (nombre) => pedir(`/workflows/${codificar(nombre)}`, { metodo: "DELETE" }),
  // El DSL lo lee y lo escribe el núcleo, no el front: la gramática vive en un
  // solo lugar. Ver core/flow/serializer.py.
  parsear: (content) => pedir("/flow/parse", { metodo: "POST", cuerpo: { content } }),
  serializar: (grafo) => pedir("/flow/serialize", {
    metodo: "POST",
    cuerpo: {
      nodes: grafo.nodes || {},
      edges: grafo.edges || [],
      start_node: grafo.start_node || null,
      meta: grafo.meta || {},
    },
  }),

  // Ejecución e historial
  validar: (cuerpo) => pedir("/validate", { metodo: "POST", cuerpo }),
  ejecutar: (cuerpo) => pedir("/run", { metodo: "POST", cuerpo }),
  runs: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return pedir("/runs" + (q ? `?${q}` : ""));
  },
  run: (id) => pedir(`/runs/${codificar(id)}`),
  // Lo que está corriendo ahora: case_id, flujo, segundos y —si el núcleo lo
  // cuenta— el paso en curso. La grilla lo consulta mientras haya algo en vuelo.
  enVuelo: () => pedir("/runs/en-vuelo"),
  // Correr sin esperar: vuelve un ticket; `ticket()` dice en cola / en vuelo /
  // terminado con el run. Es lo que usan otro Bot (plugin `bots`) o un agente remoto.
  correrSinEsperar: (cuerpo) => pedir("/runs", { metodo: "POST", cuerpo }),
  ticket: (ticket) => pedir(`/runs/ticket/${codificar(ticket)}`),

  // Registro de eventos de una fila. Acumulado entre runs, que es como lo
  // muestra el modal del botón Log de la grilla.
  log: (caseId, limit = 500) => pedir(`/logs/${codificar(caseId)}?limit=${limit}`),
  limpiarLog: (caseId) => pedir(`/logs/${codificar(caseId)}`, { metodo: "DELETE" }),
};

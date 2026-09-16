/**
 * Agente: cómo conectar un agente MCP a esta instalación, y el wizard para
 * instalar/loguear un proveedor de CLI.
 *
 * `backend/mcp` es un servidor por stdio — lo levanta el cliente del agente
 * (Claude Desktop, Claude Code, Cursor, Codex, cualquiera que hable MCP), no
 * esta webapp. Por eso esta pantalla no tiene un estado "conectado": es la
 * receta para que ese cliente lo levante él mismo.
 *
 * El wizard de instalar/loguear corre en una terminal real (xterm.js contra
 * un proceso del lado del servidor) que vive en `agent_terminal.js`, no acá:
 * es un panel flotante que sobrevive a que el usuario cambie de pestaña
 * mientras un login OAuth tarda. Esta vista sólo dispara `abrir()` y refleja
 * el estado (¿hay una sesión de este proveedor corriendo ahora?) — el
 * servidor sólo corre los argv fijos que declara `agent_providers.py`; esta
 * vista nunca arma un comando, sólo elige cuál proveedor y cuál modo.
 *
 * Cada proveedor es un acordeón: clic en la fila para ver su configuración
 * particular (el bloque JSON/TOML para pegar a mano, si `formato_config` no
 * es vacío) y dejar notas propias (modelo, skills, lo que sea — guardado por
 * proveedor vía `agent_provider_config.py`). Para Claude Code, Codex y
 * Antigravity ni hace falta copiar nada: `mcp_registration.py` escribe la
 * conexión sola apenas termina un install/login exitoso.
 *
 * Con un solo proveedor instalado, entrar acá lo abre directo (su acordeón ya
 * desplegado) en vez de obligar a buscarlo en la lista — es el único que
 * importa una vez que ya se eligió. Con cero o con más de uno, la pantalla
 * arranca en la lista, que es la única elección que tiene sentido mostrar.
 */

import { h, poner } from "../dom.js";
import { api } from "../api.js";
import { aviso } from "../components/aviso.js";
import * as agentTerminal from "../agent_terminal.js";

let shell = null;

export async function montar(elShell) {
  shell = elShell;
  shell.ponerRotulo("AGENTE");
  shell.limpiarLateral();

  poner(shell.vista, h("div", { class: "cargando", text: "Cargando…" }));

  let conexion;
  let proveedores;
  try {
    [conexion, proveedores] = await Promise.all([api.agente(), api.agentProveedores()]);
  } catch (e) {
    poner(shell.vista, aviso("error", "No se pudo leer la configuración", e.message || String(e)));
    return;
  }

  agentTerminal.escuchar((estado) => {
    // Una sesión se cerró (o abrió) en algún proveedor: puede haber cambiado
    // "instalado", así que se vuelve a armar la pantalla entera. Sólo llega
    // acá si esta vista sigue siendo la última montada — `escuchar` reemplaza
    // el callback anterior en vez de acumularlos.
    if (!estado.activa) montar(shell);
  });

  await dibujarPantalla(conexion, proveedores.providers || [], Boolean(proveedores.winget));
}

// ── Clientes MCP que no son "proveedores" (no hay CLI que instalar/loguear) ─

const OTROS_CLIENTES = [
  { nombre: "Claude Desktop", donde: "Config → Developer → Edit Config" },
  { nombre: "Cursor", donde: "`.cursor/mcp.json`, en el proyecto o en tu carpeta de usuario" },
];

function seccionOtrosClientes(datos) {
  const bloqueJson = JSON.stringify({ mcpServers: { bot: datos.connection } }, null, 2);
  return [
    h("div", { class: "seccion" }, [h("span", { text: "OTROS CLIENTES MCP" })]),
    h("div", { class: "campo__ayuda" }, [
      "No tienen una CLI que esta pantalla pueda instalar o loguear — pegales esto a mano.",
    ]),
    h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [bloqueJson]),
    botonCopiar(() => bloqueJson),
    ...OTROS_CLIENTES.map((c) =>
      h("div", { style: { display: "flex", gap: "12px", padding: "6px 0" } }, [
        h("span", { style: { fontWeight: "600", width: "140px", flex: "0 0 140px" }, text: c.nombre }),
        h("span", { class: "campo__ayuda", style: { margin: 0 }, text: c.donde }),
      ]),
    ),
  ];
}

// ── Bloque de config particular de un proveedor (JSON o TOML) ───────────
//
// Cada proveedor lee la conexión en un lugar y una sintaxis distinta — Claude
// Code y "Manual" en JSON (`mcpServers`), Codex en TOML (`.codex/config.toml`,
// confirmado contra developers.openai.com/codex) — por eso el formato sale de
// `p.formato_config` (agent_providers.py) en vez de asumir uno solo. Antigravity
// no tiene ninguno documentado (`formato_config: ""`): sólo sabe `agy mcp add`.

function bloqueToml(conexion) {
  const escapar = (s) => String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const args = conexion.args.map((a) => `"${escapar(a)}"`).join(", ");
  return [
    "[mcp_servers.bot]",
    `command = "${escapar(conexion.command)}"`,
    `args = [${args}]`,
    `cwd = "${escapar(conexion.cwd)}"`,
  ].join("\n");
}

function bloqueConfigProveedor(p, conexion) {
  if (p.formato_config === "toml") {
    return [
      h("div", { class: "campo__ayuda" }, [
        "Codex no lee `.mcp.json` — busca esto en ",
        h("span", { class: "mono", text: "~/.codex/config.toml" }),
        " (o ",
        h("span", { class: "mono", text: ".codex/config.toml" }),
        " en la raíz del proyecto, si Codex confía en esta carpeta).",
      ]),
      h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [bloqueToml(conexion)]),
      botonCopiar(() => bloqueToml(conexion)),
    ];
  }
  if (p.formato_config === "json") {
    const bloque = JSON.stringify({ mcpServers: { bot: conexion } }, null, 2);
    return [
      h("pre", { class: "bloque-codigo" }, [bloque]),
      botonCopiar(() => bloque),
    ];
  }
  return [];
}

// ── Pantalla ─────────────────────────────────────────────────────────────
//
// Con exactamente un proveedor instalado, no tiene sentido mostrar una lista
// para elegir entre uno: se le abre el acordeón ya desplegado. Con cero o con
// más de uno, la lista es la elección real y arranca cerrada.

function proveedorParaAbrirDirecto(proveedores) {
  const instalados = proveedores.filter((p) => p.automatizable && p.instalado);
  return instalados.length === 1 ? instalados[0].id : null;
}

async function dibujarPantalla(datos, proveedores, hayWinget = false) {
  const abrirDirecto = proveedorParaAbrirDirecto(proveedores);

  let herramientasPermitidas = "";
  try {
    herramientasPermitidas = (await api.agentHerramientasPermitidas()).allowed_tools || "";
  } catch { /* si falla, la sección arranca vacía y guardar la vuelve a intentar */ }

  const columna = h("div", { class: "agente-layout" }, [
    h("div", { style: { marginBottom: "16px" } }, [
      h("div", { class: "titulo", text: "Agente" }),
      h("div", { class: "subtitulo" }, [
        "Cualquier agente que hable MCP puede leer y escribir workflows, y " +
          "autorar, validar e instalar plugins acá. Lo levanta el cliente del " +
          "agente, no esta pantalla — no hay un \"conectado\" que mostrar, sólo " +
          "la configuración para pegar en el tuyo.",
      ]),
    ]),

    !datos.mcp_instalado
      ? aviso(
          "falta",
          "Falta el paquete mcp",
          "python -m webapp.mcp_servidor no va a arrancar hasta instalarlo en este entorno: pip install mcp",
        )
      : null,

    h("div", { class: "seccion" }, [h("span", { text: "PROVEEDORES DE CLI" })]),
    h("div", { class: "campo__ayuda" }, [
      "Instalá y logueá el CLI de un proveedor — se abre en un panel de terminal flotante, " +
        "que sigue corriendo aunque cambies de pestaña. Corre en esta misma máquina, con tus " +
        "propios permisos de usuario — nunca con sudo ni admin. Hacé clic en un proveedor para " +
        "ver su configuración particular y dejar notas.",
    ]),
    h("div", { class: "tarjeta", style: { marginTop: "8px" } },
      proveedores.map((p) => filaProveedor(p, datos.connection, hayWinget, p.id === abrirDirecto)),
    ),

    ...seccionOtrosClientes(datos),

    h("div", { class: "seccion" }, [h("span", { text: "ROOT DE ESTA INSTALACIÓN" })]),
    h("div", { class: "campo__ayuda" }, [
      "No va en ninguna configuración de conexión: cada tool del MCP lo recibe " +
        "como argumento propio, en cada llamada (salvo Codex, que ya lo tiene como ",
      h("span", { class: "mono", text: "cwd" }),
      "). Pasáselo igual al agente —en su prompt, o donde tu cliente permita fijar " +
        "contexto— para que trabaje contra ",
      h("span", { class: "mono", text: "esta" }),
      " instalación y no contra un checkout de desarrollo.",
    ]),
    h("pre", { class: "bloque-codigo", style: { marginTop: "8px" } }, [datos.root]),
    botonCopiar(() => datos.root),

    h("div", { class: "seccion" }, [h("span", { text: "HERRAMIENTAS SIEMPRE PERMITIDAS" })]),
    h("div", { class: "campo__ayuda" }, [
      "Se auto-aprueban en toda sesión nueva, sin volver a preguntar — es " +
        "`--allowedTools` del CLI. Separadas por coma; un patrón entre paréntesis las acota " +
        "más, ej. ",
      h("span", { class: "mono", text: 'Bash(git *)' }),
      ".",
    ]),
    seccionHerramientasPermitidas(herramientasPermitidas),
  ]);

  poner(shell.vista, columna);
}

function seccionHerramientasPermitidas(valorInicial) {
  const input = h("input", {
    class: "entrada entrada--mono", type: "text", value: valorInicial,
    placeholder: "ej: Bash, WebFetch",
  });
  const btnGuardar = h("button", { class: "btn btn--chico", text: "Guardar" });
  const estado = h("span", { class: "campo__ayuda", style: { margin: "0 0 0 8px" } });

  const guardar = async () => {
    btnGuardar.disabled = true;
    estado.textContent = "Guardando…";
    try {
      const guardado = await api.guardarAgentHerramientasPermitidas(input.value.trim());
      input.value = guardado.allowed_tools;
      estado.textContent = "✓ Guardado — vale desde la próxima sesión.";
    } catch (e) {
      estado.textContent = "✕ " + (e.message || String(e));
    } finally {
      btnGuardar.disabled = false;
    }
  };
  btnGuardar.addEventListener("click", guardar);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); guardar(); } });

  return h("div", { class: "fila-control", style: { marginTop: "8px" } }, [input, btnGuardar, estado]);
}

function filaProveedor(p, conexion, hayWinget, abrirDirecto) {
  const sesion = agentTerminal.sesionDe(p.id);
  const botones = [];
  if (sesion) {
    // Ya hay una terminal corriendo para este proveedor (puede estar
    // escondida en el panel flotante): reabrirla, no arrancar otra.
    const btnVer = h("button", { class: "btn btn--chico btn--azul", text: "Ver terminal" });
    btnVer.addEventListener("click", (e) => { e.stopPropagation(); agentTerminal.verPanel(); });
    botones.push(btnVer);
  } else if (p.id === "manual") {
    // Cualquier CLI por su id de winget: es lo que hace útil a esta fila. Sin
    // winget en la máquina no hay con qué, y se dice en vez de ofrecer el botón.
    const idPaquete = h("input", {
      class: "entrada entrada--mono", type: "text", placeholder: "id de winget, ej. Anthropic.ClaudeCode",
      style: { width: "240px" }, disabled: !hayWinget,
      title: hayWinget ? "" : "Esta máquina no tiene winget",
    });
    const btn = h("button", { class: "btn btn--chico", text: "Instalar", disabled: !hayWinget });
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (idPaquete.value.trim()) agentTerminal.abrir(shell, "manual", "install", idPaquete.value.trim());
    });
    idPaquete.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); btn.click(); } });
    botones.push(idPaquete, btn);
  } else if (p.automatizable) {
    if (!p.instalado) {
      const btn = h("button", {
        class: "btn btn--chico",
        text: "Instalar",
        disabled: !p.se_puede_instalar,
        title: p.se_puede_instalar ? "" : "Hace falta PowerShell (o bash) en esta máquina para correr el instalador del proveedor",
      });
      btn.addEventListener("click", (e) => { e.stopPropagation(); agentTerminal.abrir(shell, p.id, "install"); });
      botones.push(btn);
    } else {
      const btnLogin = h("button", { class: "btn btn--chico btn--azul", text: "Iniciar sesión" });
      btnLogin.addEventListener("click", (e) => { e.stopPropagation(); agentTerminal.abrir(shell, p.id, "login"); });
      botones.push(btnLogin);
    }
  }

  const flecha = h("span", { class: "acordeon__flecha", text: abrirDirecto ? "▾" : "▸" });
  const panel = h("div", { class: "acordeon__panel", hidden: !abrirDirecto });
  let cargado = false;

  const encabezado = h("div", {
    class: "campo campo--clickeable",
    style: { alignItems: "center" },
    onClick: () => alternarPanel(),
  }, [
    flecha,
    h("div", { class: "campo__etiqueta", style: { width: "160px", flex: "0 0 160px" } }, [
      h("div", { class: "campo__nombre", text: p.label }),
    ]),
    h("div", { class: "campo__control" }, [
      h("span", {
        class: "badge " + (p.instalado ? "badge--ok" : "badge--falta"),
        text: p.automatizable ? (p.instalado ? "instalado" : "no instalado") : "sin automatizar",
      }),
      h("div", { class: "campo__ayuda", text: p.doc }),
    ]),
    h("div", { style: { display: "flex", gap: "6px" }, onClick: (e) => e.stopPropagation() }, botones),
  ]);

  function alternarPanel() {
    panel.hidden = !panel.hidden;
    flecha.textContent = panel.hidden ? "▸" : "▾";
    if (!panel.hidden && !cargado) {
      cargado = true;
      poner(panel, ...panelProveedor(p, conexion));
    }
  }

  if (abrirDirecto) {
    cargado = true;
    poner(panel, ...panelProveedor(p, conexion));
  }

  return h("div", { class: "acordeon" }, [encabezado, panel]);
}

function panelProveedor(p, conexion) {
  const notasArea = h("textarea", {
    class: "entrada entrada--area", placeholder: "Modelo a usar, qué le sirve mejor, cualquier recordatorio…",
  });
  const btnGuardarNotas = h("button", { class: "btn btn--chico", text: "Guardar" });
  const estadoNotas = h("span", { class: "campo__ayuda", style: { margin: "0 0 0 8px" } });

  api.agentProveedorConfig(p.id)
    .then((cfg) => { notasArea.value = cfg.notas || ""; })
    .catch(() => { estadoNotas.textContent = "No se pudieron leer las notas guardadas."; });

  btnGuardarNotas.addEventListener("click", async () => {
    btnGuardarNotas.disabled = true;
    estadoNotas.textContent = "Guardando…";
    try {
      await api.guardarAgentProveedorConfig(p.id, notasArea.value);
      estadoNotas.textContent = "✓ Guardado";
    } catch (e) {
      estadoNotas.textContent = "✕ " + (e.message || String(e));
    } finally {
      btnGuardarNotas.disabled = false;
    }
  });

  const bloques = [];

  if (p.auto_registro) {
    bloques.push(aviso(
      "ok",
      "Se registra sola",
      "Al instalar o iniciar sesión arriba, esta instalación queda dada de alta como servidor MCP " +
        "de este proveedor — no hace falta pegar nada a mano.",
    ));
  }

  const bloqueConfig = bloqueConfigProveedor(p, conexion);
  if (bloqueConfig.length) {
    bloques.push(
      h("div", { class: "seccion", style: { marginTop: p.auto_registro ? "10px" : "0" } }, [
        h("span", { text: p.auto_registro ? "O PEGALA A MANO" : "CONFIGURACIÓN DE CONEXIÓN" }),
      ]),
      ...bloqueConfig,
    );
  }

  bloques.push(
    h("div", { class: "seccion", style: { marginTop: "10px" } }, [h("span", { text: "NOTAS / SKILLS" })]),
    h("div", { class: "fila-control", style: { marginTop: "4px", alignItems: "flex-start" } }, [notasArea]),
    h("div", { style: { marginTop: "4px" } }, [btnGuardarNotas, estadoNotas]),
  );

  return bloques;
}

// ── Compartido ────────────────────────────────────────────────────────

function botonCopiar(obtenerTexto) {
  const boton = h("button", { class: "btn", style: { marginTop: "8px" }, text: "Copiar" });
  boton.addEventListener("click", () => copiar(boton, obtenerTexto()));
  return boton;
}

async function copiar(boton, texto) {
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

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import agent_providers  # noqa: E402


def test_los_proveedores_conocidos_estan():
    ids = {p.id for p in agent_providers.PROVEEDORES}
    assert ids == {"claude-code", "codex", "antigravity", "manual"}


def test_manual_no_es_automatizable():
    """Manual no declara ni instalar ni login: no hay proceso que la terminal pueda correr."""
    manual = agent_providers.proveedor("manual")
    assert manual.instalar == () and manual.login == ()
    filas = {f["id"]: f for f in agent_providers.estado()}
    assert filas["manual"]["automatizable"] is False
    assert filas["manual"]["auto_registro"] is False


def test_ningun_comando_usa_shell():
    """`instalar`/`login` son siempre argv — nunca una línea armada a mano."""
    for p in agent_providers.PROVEEDORES:
        assert isinstance(p.instalar, tuple) and all(isinstance(a, str) for a in p.instalar)
        assert isinstance(p.login, tuple) and all(isinstance(a, str) for a in p.login)


def test_proveedor_por_id():
    assert agent_providers.proveedor("codex").label == "Codex CLI"
    assert agent_providers.proveedor("no-existe") is None


def test_estado_reporta_instalado_segun_el_path(monkeypatch):
    def fake_which(nombre):
        return "/usr/bin/claude" if nombre == "claude" else None

    monkeypatch.setattr(agent_providers.shutil, "which", lambda nombre, path=None: fake_which(nombre))
    monkeypatch.setattr(agent_providers, "_path_del_registro", lambda: "")
    monkeypatch.setattr(agent_providers.Path, "is_file", lambda self: False)

    filas = {f["id"]: f for f in agent_providers.estado()}
    assert filas["claude-code"]["instalado"] is True
    assert filas["codex"]["instalado"] is False
    # Sin powershell/bash en el PATH (el fake sólo conoce "claude") no hay con
    # qué correr el instalador del vendor, y se dice antes de ofrecer el botón.
    assert filas["codex"]["se_puede_instalar"] is False


def test_ninguno_necesita_node_ni_claude_code_powershell():
    """
    En una PC de planta no hay npm. Y Claude Code no puede ir por el `irm | iex`
    del vendor: Defender lo marca como troyano por heurística cuando lo lanza
    este servidor — se baja y verifica desde Python (webapp/instalar_agente.py).
    """
    for p in agent_providers.PROVEEDORES:
        assert "npm" not in p.instalar
    claude = agent_providers.proveedor("claude-code")
    assert "powershell" not in claude.instalar[0].lower()
    # winget si la máquina lo tiene; si no, la bajada verificada. Nunca `irm | iex`.
    if agent_providers.ruta_de_winget():
        assert claude.instalar[2:4] == ("--id", "Anthropic.ClaudeCode")
    else:
        assert claude.instalar == agent_providers._INSTALADOR_VERIFICADO_CLAUDE


def test_winget_cuando_esta_y_solo_la_fuente_winget(monkeypatch):
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: r"C:\WindowsApps\winget.exe")
    comando = agent_providers._instalar_windows("OpenAI.Codex", ("respaldo",))
    assert comando[:4] == (r"C:\WindowsApps\winget.exe", "install", "--id", "OpenAI.Codex")
    # Sin `--source winget`, una tienda (msstore) rota frenaba la instalación
    # aunque el paquete estuviera en la fuente que sí andaba.
    assert comando[comando.index("--source") + 1] == "winget"
    assert "--disable-interactivity" in comando
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: None)
    assert agent_providers._instalar_windows("OpenAI.Codex", ("respaldo",)) == ("respaldo",)


def test_el_instalador_verificado_de_claude_va_por_ruta_de_script():
    """`-m webapp.instalar_agente` fallaba: la terminal corre parada en la carpeta de datos, sin `webapp` importable."""
    ruta = agent_providers._INSTALADOR_VERIFICADO_CLAUDE[1]
    assert ruta.endswith("instalar_agente.py") and pathlib.Path(ruta).is_file()
    assert agent_providers._INSTALADOR_VERIFICADO_CLAUDE[2] == "claude-code"


def test_manual_instala_cualquier_paquete_de_winget_con_id_valido(monkeypatch):
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: "winget")
    assert "Google.AntigravityCLI" in agent_providers.comando_winget_paquete("Google.AntigravityCLI")
    for malo in ("", "con espacios", "a;b", "x" * 200):
        with pytest.raises(ValueError):
            agent_providers.comando_winget_paquete(malo)
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: None)
    with pytest.raises(ValueError, match="winget"):
        agent_providers.comando_winget_paquete("OpenAI.Codex")


def test_recien_instalado_se_encuentra_aunque_el_path_no_lo_tenga(monkeypatch, tmp_path):
    """
    El instalador del vendor agrega su carpeta al PATH del usuario, pero este
    servidor ya estaba corriendo con el PATH viejo: sin mirar la carpeta
    conocida, "Iniciar sesión" fallaba con "claude no se encuentra".
    """
    monkeypatch.setattr(agent_providers.shutil, "which", lambda _n, path=None: None)
    monkeypatch.setattr(agent_providers, "_path_del_registro", lambda: "")
    binario = tmp_path / "claude.exe"
    binario.write_bytes(b"")
    claude = agent_providers.proveedor("claude-code")
    monkeypatch.setattr(agent_providers, "PROVEEDORES", (
        agent_providers.Proveedor(**{**claude.__dict__, "rutas_probables": (str(binario),)}),
    ))
    p = agent_providers.PROVEEDORES[0]

    assert agent_providers.ruta_del_binario(p) == str(binario)
    assert agent_providers.comando_login(p) == (str(binario),)
    assert agent_providers.estado()[0]["instalado"] is True

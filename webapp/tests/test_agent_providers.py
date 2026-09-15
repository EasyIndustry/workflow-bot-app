from __future__ import annotations

import pathlib
import sys

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
    assert claude.instalar[1:] == ("-m", "webapp.instalar_agente", "claude-code")
    assert "powershell" not in claude.instalar[0].lower()


def test_codex_y_agy_van_por_winget_cuando_esta(monkeypatch):
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: r"C:\WindowsApps\winget.exe")
    comando = agent_providers._instalar_windows("OpenAI.Codex", "irm x | iex")
    assert comando[:4] == (r"C:\WindowsApps\winget.exe", "install", "--id", "OpenAI.Codex")
    assert "--disable-interactivity" in comando
    monkeypatch.setattr(agent_providers, "ruta_de_winget", lambda: None)
    assert agent_providers._instalar_windows("OpenAI.Codex", "irm x | iex")[0] == "powershell"


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

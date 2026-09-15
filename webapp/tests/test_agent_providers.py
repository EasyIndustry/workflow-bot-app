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

    monkeypatch.setattr(agent_providers.shutil, "which", fake_which)

    filas = {f["id"]: f for f in agent_providers.estado()}
    assert filas["claude-code"]["instalado"] is True
    assert filas["codex"]["instalado"] is False
    # Sin npm en el PATH (el fake sólo conoce "claude"), Claude Code/Codex no
    # se pueden instalar — antigravity no depende de npm, así que no le pega.
    assert filas["codex"]["se_puede_instalar"] is False

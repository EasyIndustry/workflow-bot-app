from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.core.instance import Instance  # noqa: E402

from webapp import agent_sessions  # noqa: E402


def test_sin_sesion_previa_coincide_con_cualquier_maquina(tmp_path):
    inst = Instance(tmp_path)
    try:
        assert agent_sessions.sesion_de(inst, "agente-mcp") is None
        assert agent_sessions.coincide_con_esta_maquina(inst, "agente-mcp") is True
    finally:
        inst.close()


def test_registrar_y_leer(tmp_path):
    inst = Instance(tmp_path)
    try:
        agent_sessions.registrar_login(inst, "agente-mcp", "claude-code")
        item = agent_sessions.sesion_de(inst, "agente-mcp")
        assert item["provider"] == "claude-code"
        assert item["hostname"] == agent_sessions.hostname_actual()
        assert agent_sessions.coincide_con_esta_maquina(inst, "agente-mcp") is True
    finally:
        inst.close()


def test_detecta_una_maquina_distinta(tmp_path, monkeypatch):
    inst = Instance(tmp_path)
    try:
        monkeypatch.setattr(agent_sessions, "hostname_actual", lambda: "pc-de-alguien")
        agent_sessions.registrar_login(inst, "agente-mcp", "claude-code")

        monkeypatch.setattr(agent_sessions, "hostname_actual", lambda: "otra-pc")
        assert agent_sessions.coincide_con_esta_maquina(inst, "agente-mcp") is False
    finally:
        inst.close()


def test_actores_distintos_no_se_pisan(tmp_path):
    inst = Instance(tmp_path)
    try:
        agent_sessions.registrar_login(inst, "agente-mcp", "claude-code")
        agent_sessions.registrar_login(inst, "otro-agente", "codex")

        assert agent_sessions.sesion_de(inst, "agente-mcp")["provider"] == "claude-code"
        assert agent_sessions.sesion_de(inst, "otro-agente")["provider"] == "codex"
    finally:
        inst.close()

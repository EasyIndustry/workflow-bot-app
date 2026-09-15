from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.core.instance import Instance  # noqa: E402

from webapp import agent_provider_config  # noqa: E402


def test_vacio_si_nunca_se_guardo_nada(tmp_path):
    inst = Instance(tmp_path)
    try:
        assert agent_provider_config.obtener(inst, "claude-code") == {"notas": ""}
    finally:
        inst.close()


def test_guardar_y_leer(tmp_path):
    inst = Instance(tmp_path)
    try:
        agent_provider_config.guardar(inst, "codex", "  usa gpt-5, buenísimo para refactors  ")
        assert agent_provider_config.obtener(inst, "codex")["notas"] == "usa gpt-5, buenísimo para refactors"
    finally:
        inst.close()


def test_proveedores_distintos_no_se_pisan(tmp_path):
    inst = Instance(tmp_path)
    try:
        agent_provider_config.guardar(inst, "codex", "nota de codex")
        agent_provider_config.guardar(inst, "claude-code", "nota de claude")

        assert agent_provider_config.obtener(inst, "codex")["notas"] == "nota de codex"
        assert agent_provider_config.obtener(inst, "claude-code")["notas"] == "nota de claude"
    finally:
        inst.close()

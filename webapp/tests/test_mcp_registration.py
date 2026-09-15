from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import tomllib  # noqa: E402

from webapp import mcp_registration  # noqa: E402

CONEXION = {
    "command": "C:/python.exe",
    "args": ["-m", "backend.mcp"],
    "cwd": "C:/instalacion",
    "env": {"PYTHONPATH": "C:/instalacion"},
}


def test_proveedor_desconocido_no_hace_nada(tmp_path):
    assert mcp_registration.registrar("no-existe", tmp_path, CONEXION) is None


def test_manual_no_tiene_auto_registro(tmp_path):
    assert mcp_registration.registrar("manual", tmp_path, CONEXION) is None


def test_claude_code_crea_mcp_json(tmp_path):
    mensaje = mcp_registration.registrar("claude-code", tmp_path, CONEXION)
    assert "mcp.json" in mensaje

    datos = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert datos["mcpServers"]["bot"] == CONEXION


def test_claude_code_mergea_sin_pisar_otros_servers(tmp_path):
    ruta = tmp_path / ".mcp.json"
    ruta.write_text(json.dumps({"mcpServers": {"otro": {"command": "algo"}}}), encoding="utf-8")

    mcp_registration.registrar("claude-code", tmp_path, CONEXION)

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["mcpServers"]["otro"] == {"command": "algo"}
    assert datos["mcpServers"]["bot"] == CONEXION


def test_codex_crea_config_toml(tmp_path):
    mensaje = mcp_registration.registrar("codex", tmp_path, CONEXION)
    assert "config.toml" in mensaje

    ruta = tmp_path / ".codex" / "config.toml"
    datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    assert datos["mcp_servers"]["bot"]["command"] == CONEXION["command"]
    assert datos["mcp_servers"]["bot"]["args"] == CONEXION["args"]
    assert datos["mcp_servers"]["bot"]["cwd"] == CONEXION["cwd"]
    # env además de cwd: Claude Code ignora cwd en .mcp.json y sin PYTHONPATH
    # `backend` no se importa desde una instalación; Codex recibe lo mismo.
    assert datos["mcp_servers"]["bot"]["env"] == CONEXION["env"]


def test_codex_mergea_sin_pisar_otras_tablas(tmp_path):
    ruta = tmp_path / ".codex" / "config.toml"
    ruta.parent.mkdir(parents=True)
    ruta.write_text('[mcp_servers.otro]\ncommand = "algo"\n', encoding="utf-8")

    mcp_registration.registrar("codex", tmp_path, CONEXION)

    datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    assert datos["mcp_servers"]["otro"]["command"] == "algo"
    assert datos["mcp_servers"]["bot"]["command"] == CONEXION["command"]


def test_antigravity_corre_agy_mcp_add(tmp_path, monkeypatch):
    """
    Nunca toca el `agy` real de la máquina que corre los tests: `subprocess.run`
    se reemplaza por un fake que sólo registra cómo se lo llamó.
    """
    llamadas = []

    class ResultadoFake:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(comando, **kwargs):
        llamadas.append(comando)
        return ResultadoFake()

    monkeypatch.setattr(mcp_registration.subprocess, "run", fake_run)

    mensaje = mcp_registration.registrar("antigravity", tmp_path, CONEXION)

    assert "✓" in mensaje
    assert llamadas[0][:3] == ["agy", "mcp", "add"]
    assert "PYTHONPATH=C:/instalacion" in llamadas[0]
    assert llamadas[0][-4:] == ["bot", "C:/python.exe", "-m", "backend.mcp"]


def test_antigravity_binario_ausente_no_revienta(tmp_path, monkeypatch):
    def fake_run(comando, **kwargs):
        raise FileNotFoundError("agy no está en el PATH")

    monkeypatch.setattr(mcp_registration.subprocess, "run", fake_run)

    mensaje = mcp_registration.registrar("antigravity", tmp_path, CONEXION)
    assert "⚠" in mensaje

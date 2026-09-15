"""
Tests de `installer/source/plugins.py` — validar e instalar, para el bucket
curado y para lo que arme un agente vía MCP.

Cada llamada pasa `root=tmp_path`: sin eso, `validar()` corre la CLI contra el
`backend/` del propio repo y le crea un `data/bot.db` real ahí — exactamente
lo que un test no puede hacer.
"""

from __future__ import annotations

import pytest

from installer.source import plugins


def _plugin_valido(base, nombre: str, *, ports: tuple[str, ...] = (), version: str = "1.0.0"):
    carpeta = base / nombre
    carpeta.mkdir(parents=True)
    (carpeta / "__init__.py").write_text(
        "from backend.core.contract import Plugin, PluginManifest\n\n"
        f"MANIFEST = PluginManifest(name={nombre!r}, label={nombre!r}, "
        f"version={version!r}, ports={ports!r})\n"
        "PLUGIN = Plugin(manifest=MANIFEST, tools=[])\n",
        encoding="utf-8",
    )
    return carpeta


def _plugin_sin_init(base, nombre: str):
    carpeta = base / nombre
    carpeta.mkdir(parents=True)
    (carpeta / "plugin.py").write_text("PLUGIN = None\n", encoding="utf-8")
    return carpeta


def _plugin_con_port_inexistente(base, nombre: str):
    carpeta = base / nombre
    carpeta.mkdir(parents=True)
    (carpeta / "__init__.py").write_text(
        "from backend.core.contract import Plugin, PluginManifest\n\n"
        f"MANIFEST = PluginManifest(name={nombre!r}, label={nombre!r}, "
        'ports=("no_existe",))\n'
        "PLUGIN = Plugin(manifest=MANIFEST, tools=[])\n",
        encoding="utf-8",
    )
    return carpeta


# ── validar ────────────────────────────────────────────────────────────


def test_valida_un_plugin_correcto(tmp_path):
    origen = _plugin_valido(tmp_path / "origen", "candidato_ok", version="2.3.0")
    r = plugins.validar(origen, root=tmp_path)
    assert r.ok
    assert r.nombre == "candidato_ok"
    assert r.version == "2.3.0"


def test_una_carpeta_sin_init_no_es_un_plugin(tmp_path):
    origen = _plugin_sin_init(tmp_path / "origen", "sin_init")
    r = plugins.validar(origen, root=tmp_path)
    assert not r.ok
    assert "__init__.py" in r.errores[0]


def test_una_carpeta_que_no_existe(tmp_path):
    r = plugins.validar(tmp_path / "no_existe", root=tmp_path)
    assert not r.ok
    assert "no existe" in r.errores[0]


def test_un_plugin_que_pide_un_port_inexistente(tmp_path):
    origen = _plugin_con_port_inexistente(tmp_path / "origen", "port_raro")
    r = plugins.validar(origen, root=tmp_path)
    assert not r.ok
    assert "no_existe" in r.errores[0]


# ── instalar ───────────────────────────────────────────────────────────


def test_instalar_copia_y_deja_la_procedencia(tmp_path):
    origen = _plugin_valido(tmp_path / "origen", "instalado_ok", version="1.2.0")
    destino = tmp_path / "plugins"

    resultado = plugins.instalar(origen, destino, fuente="agent", root=tmp_path)

    assert resultado["name"] == "instalado_ok"
    assert resultado["version"] == "1.2.0"
    assert resultado["source"] == "agent"
    assert (destino / "instalado_ok" / "__init__.py").is_file()

    proc = plugins.procedencia(destino, "instalado_ok")
    assert proc["source"] == "agent"
    assert proc["version"] == "1.2.0"
    assert proc["name"] == "instalado_ok"


def test_instalar_desde_el_bucket_queda_igual_de_instalado(tmp_path):
    """
    Curado o generado por un agente: mismo primitivo, mismo resultado. Sólo
    cambia el string de `fuente`, nunca la validación ni dónde termina.
    """
    origen = _plugin_valido(tmp_path / "origen", "del_bucket")
    destino = tmp_path / "plugins"

    resultado = plugins.instalar(origen, destino, fuente="bucket", root=tmp_path)

    assert resultado["path"] == str(destino / "del_bucket")
    assert plugins.procedencia(destino, "del_bucket")["source"] == "bucket"


def test_instalar_un_plugin_invalido_no_toca_plugins_dir(tmp_path):
    origen = _plugin_con_port_inexistente(tmp_path / "origen", "invalido")
    destino = tmp_path / "plugins"

    with pytest.raises(plugins.PluginInvalido):
        plugins.instalar(origen, destino, fuente="agent", root=tmp_path)

    # Ni la carpeta se llegó a crear: nada a medias.
    assert not (destino / "invalido").exists()


def test_reinstalar_reemplaza_entero_sin_dejar_restos(tmp_path):
    destino = tmp_path / "plugins"

    v1 = _plugin_valido(tmp_path / "v1", "actualizable", version="1.0.0")
    plugins.instalar(v1, destino, fuente="bucket", root=tmp_path)
    (destino / "actualizable" / "marca_vieja.txt").write_text("v1", encoding="utf-8")

    v2 = _plugin_valido(tmp_path / "v2", "actualizable", version="2.0.0")
    resultado = plugins.instalar(v2, destino, fuente="bucket", root=tmp_path)

    assert resultado["version"] == "2.0.0"
    # El archivo que sólo estaba en la v1 no sobrevive: se reemplazó entero,
    # no se mezclaron los contenidos de las dos carpetas.
    assert not (destino / "actualizable" / "marca_vieja.txt").exists()
    assert not (destino / "actualizable.instalando").exists()


def test_procedencia_de_un_plugin_no_instalado_es_none(tmp_path):
    assert plugins.procedencia(tmp_path / "plugins", "fantasma") is None

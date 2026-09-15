"""
Los tests del instalador escriben instalaciones de verdad en `tmp_path`, y
`instalar()` anota la última en la carpeta de configuración del usuario. Acá se
redirige esa carpeta a un tmp: un test no puede dejar rastro en ~/.config del
que lo corre, ni pisar la instalación que tiene anotada.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def config_de_usuario_aislada(tmp_path, monkeypatch):
    carpeta = tmp_path / "config-usuario"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(carpeta))
    monkeypatch.setenv("LOCALAPPDATA", str(carpeta))
    return carpeta

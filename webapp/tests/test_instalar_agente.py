"""
`webapp.instalar_agente`: Claude Code bajado y verificado desde Python, en vez
del `irm | iex` que Defender marca como troyano por heurística. Sin red: las
URLs se responden desde un dict, y `claude install` es un fake que anota cómo
se lo llamó.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import instalar_agente as ia  # noqa: E402

BINARIO = b"MZ-falso-claude"
PLAT = ia._plataforma()


def _red(checksum=None, version="2.1.272"):
    checksum = checksum or hashlib.sha256(BINARIO).hexdigest()
    respuestas = {
        f"{ia.BASE}/latest": version.encode(),
        f"{ia.BASE}/{version}/manifest.json": json.dumps({"platforms": {PLAT: {"checksum": checksum}}}).encode(),
        f"{ia.BASE}/{version}/{PLAT}/claude.exe": BINARIO,
        f"{ia.BASE}/{version}/{PLAT}/claude": BINARIO,
    }
    return lambda url: respuestas[url]


def _correr_fake(llamadas, firma=("Valid", "CN=Anthropic, PBC, O=Anthropic, PBC")):
    def correr(comando, **kw):
        llamadas.append(comando)
        if comando[0] == "powershell":
            return SimpleNamespace(returncode=0, stdout="\n".join(firma) + "\n")
        return SimpleNamespace(returncode=0, stdout="")
    return correr


def test_baja_verifica_y_corre_claude_install(tmp_path):
    llamadas = []
    codigo = ia.instalar_claude_code(abrir=_red(), correr=_correr_fake(llamadas), destino=tmp_path, imprimir=lambda *_: None)
    assert codigo == 0
    instal = [c for c in llamadas if c[0] != "powershell"]
    assert len(instal) == 1 and instal[0][1:] == ["install", "latest"]
    assert instal[0][0].startswith(str(tmp_path))
    # El binario temporal se borra al terminar, como hace el script oficial.
    assert list(tmp_path.iterdir()) == []


def test_checksum_distinto_no_instala_ni_deja_el_archivo(tmp_path):
    llamadas = []
    with pytest.raises(ia.InstalacionError, match="SHA256"):
        ia.instalar_claude_code(abrir=_red(checksum="00" * 32), correr=_correr_fake(llamadas), destino=tmp_path, imprimir=lambda *_: None)
    assert llamadas == [] and list(tmp_path.iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="la firma Authenticode se mira sólo en Windows")
def test_firma_invalida_o_de_otro_no_instala(tmp_path):
    for firma in (("NotSigned", ""), ("Valid", "CN=Otro, O=Otro")):
        llamadas = []
        with pytest.raises(ia.InstalacionError, match="firma"):
            ia.instalar_claude_code(abrir=_red(), correr=_correr_fake(llamadas, firma), destino=tmp_path, imprimir=lambda *_: None)
        assert all(c[0] == "powershell" for c in llamadas)


def test_version_rara_corta_antes_de_bajar(tmp_path):
    def abrir(url):
        return b"<html>error</html>"
    with pytest.raises(ia.InstalacionError, match="versi"):
        ia.instalar_claude_code(abrir=abrir, correr=lambda *a, **k: None, destino=tmp_path, imprimir=lambda *_: None)


def test_main_valida_el_argumento(capsys):
    assert ia.main([]) == 2
    assert ia.main(["otro"]) == 2

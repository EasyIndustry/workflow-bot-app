"""
Las raíces de archivos editables desde la app (`webapp/limites.py`).

Lo que se prueba es lo que hace peligrosa a esta pantalla: desde core#22 una
raíz declarada que no existe impide arrancar, así que guardar algo inválido
desde el navegador dejaría la instalación sin levantar. Todo lo que no
arrancaría tiene que morir antes de escribir el archivo.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.core.instance import Instance  # noqa: E402
from webapp import limites  # noqa: E402

# Armado con `chr(92)` a propósito: escrito como literal, una barra de más o de
# menos convierte el caso en otro sin que se note, y es justo el detalle que se
# está probando.
BARRA = chr(92)
UNC_SIN_COMPARTIDO = BARRA * 2 + "servidor"


@pytest.fixture
def instalacion(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "plugins").mkdir()
    (tmp_path / "boot.env").write_text(
        f"root={tmp_path}\nplugins_dir={tmp_path / 'plugins'}\n"
        f"fs_root={tmp_path / 'workspace'}\nprocess_allowlist=\ndefault_actor=local\n",
        encoding="utf-8-sig")
    inst = Instance(tmp_path)
    yield inst, tmp_path
    inst.close()


def _guardar(inst, raiz, raices):
    return limites.guardar(inst, raiz, raices)


def test_una_sola_raiz_se_escribe_como_fs_root(instalacion):
    """El caso común no tiene por qué hablar de alias."""
    inst, raiz = instalacion
    otra = raiz / "otra"
    otra.mkdir()

    _guardar(inst, raiz, [{"alias": "", "ruta": str(otra)}])

    escrito = (raiz / "boot.env").read_text(encoding="utf-8-sig")
    assert f"fs_root={otra}" in escrito
    # `render` documenta todas las claves, así que `# fs_roots=` aparece
    # comentado; lo que no tiene que haber es una activa.
    assert "\nfs_roots=" not in escrito


def test_varias_raices_se_escriben_con_alias_y_se_releen(instalacion):
    inst, raiz = instalacion
    share = raiz / "share"
    share.mkdir()

    r = _guardar(inst, raiz, [{"alias": "casa", "ruta": str(raiz / "workspace")},
                              {"alias": "origen", "ruta": str(share)}])

    assert r["restart_required"] is True
    # Releerlo con el núcleo es la prueba que importa: que el archivo escrito
    # vuelva a entrar tal cual, que es donde ya se nos escapó una raíz una vez.
    from backend.core import boot
    leido = boot.load(raiz)
    assert leido.fs_roots == {"casa": str(raiz / "workspace"), "origen": str(share)}
    assert not boot.fatal(leido)


def test_una_raiz_que_no_existe_no_se_guarda(instalacion):
    """Es la que dejaría la instalación sin arrancar."""
    inst, raiz = instalacion
    antes = (raiz / "boot.env").read_text(encoding="utf-8-sig")

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": str(raiz / "no-existe")}])

    assert "no existe" in " ".join(exc.value.detalle)
    assert (raiz / "boot.env").read_text(encoding="utf-8-sig") == antes


def test_una_raiz_que_contiene_la_base_no_se_guarda(instalacion):
    """
    `data/` tiene la base y la llave de cifrado. Una raíz que la contenga la
    deja al alcance de cualquier flujo con el port fs, que es exactamente lo
    que la instalación acotada evita. El núcleo no lo puede chequear solo:
    `data/` no es un valor declarado en boot.env cuando se usa el default.
    """
    inst, raiz = instalacion

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": str(raiz)}])

    assert "base" in " ".join(exc.value.detalle).lower()


def test_un_unc_sin_recurso_compartido_se_explica(instalacion):
    """
    El nombre del servidor a secas no es una ruta absoluta para pathlib: queda reescrita contra la
    raíz de la instalación, y el error habla de una carpeta que no aparece en
    ningún lado. Se ataja con el motivo verdadero.
    """
    inst, raiz = instalacion

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": UNC_SIN_COMPARTIDO}])

    assert "compartido" in " ".join(exc.value.detalle)


def test_un_alias_repetido_o_con_separadores_no_pasa(instalacion):
    inst, raiz = instalacion
    otra = raiz / "otra"
    otra.mkdir()

    with pytest.raises(limites.LimitesError):
        limites.normalizar([{"alias": "a", "ruta": str(otra)}, {"alias": "a", "ruta": str(otra)}])
    with pytest.raises(limites.LimitesError):
        limites.normalizar([{"alias": "con,coma", "ruta": str(otra)}])


def test_la_segunda_raiz_necesita_alias(instalacion):
    """Sin nombre no hay forma de referirla desde un flujo."""
    otra = "/tmp/x"
    with pytest.raises(limites.LimitesError) as exc:
        limites.normalizar([{"alias": "", "ruta": "/tmp/a"}, {"alias": "", "ruta": otra}])
    assert "alias" in " ".join(exc.value.detalle)


def test_guardar_deja_el_boot_env_anterior_al_lado(instalacion):
    inst, raiz = instalacion
    otra = raiz / "otra"
    otra.mkdir()
    antes = (raiz / "boot.env").read_text(encoding="utf-8-sig")

    _guardar(inst, raiz, [{"alias": "", "ruta": str(otra)}])

    assert (raiz / limites.RESPALDO).read_text(encoding="utf-8-sig") == antes


def test_leer_dice_cuando_no_hay_ningun_limite(instalacion):
    """Sin raíces un flujo alcanza todo el disco, y la pantalla tiene que decirlo."""
    inst, raiz = instalacion
    import dataclasses
    inst.boot = dataclasses.replace(inst.boot, fs_root=None, fs_roots=None)

    assert limites.leer(inst, raiz)["sin_limite"] is True


def test_con_varias_raices_la_primera_se_guarda_con_nombre(instalacion):
    """
    El alias vacío se escribe como `fs_roots==ruta`, y un núcleo anterior a
    v0.3.1-beta.4 descarta ese par al releer: la instalación arrancaba con una
    raíz de menos y la segunda pasaba a resolver las rutas relativas, sin un
    solo error. La app y el núcleo se actualizan por separado, así que la
    pantalla no puede depender de cuál está abajo.
    """
    inst, raiz = instalacion
    share = raiz / "share"
    share.mkdir()

    r = _guardar(inst, raiz, [{"alias": "", "ruta": str(raiz / "workspace")},
                              {"alias": "origen", "ruta": str(share)}])

    assert r["raices"][0]["alias"] == limites.PRIMERA_POR_DEFECTO
    escrito = (raiz / "boot.env").read_text(encoding="utf-8-sig")
    assert "fs_roots==" not in escrito
    # Y la primera sigue siendo la primera: es la que resuelve lo relativo.
    from backend.core import boot
    assert next(iter(boot.load(raiz).fs_roots_efectivos.values())) == str(raiz / "workspace")


def test_una_unidad_sin_barra_no_se_guarda(instalacion):
    """
    `D:` sin la barra es "la carpeta actual de esa unidad", y cambia según
    desde dónde arranque el proceso. En una instalación real pasó la
    validación resolviendo a una carpeta inocua y, al reiniciar, resolvió a la
    raíz de la instalación —con plugins/ adentro— y el núcleo se negó a
    arrancar. Nunca es lo que alguien quiso escribir.
    """
    inst, raiz = instalacion

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": "D:"}])

    assert "sin la barra" in " ".join(exc.value.detalle)


def test_una_ruta_relativa_no_se_guarda(instalacion):
    inst, raiz = instalacion

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": "workspace"}])

    assert "ruta completa" in " ".join(exc.value.detalle)


def test_la_unidad_entera_que_contiene_la_instalacion_no_se_guarda(instalacion):
    """Con la barra ya es válida como ruta, pero se traga data/ y plugins/."""
    inst, raiz = instalacion
    unidad = raiz.drive + BARRA  # la unidad donde vive esta instalación

    with pytest.raises(limites.LimitesError) as exc:
        _guardar(inst, raiz, [{"alias": "", "ruta": unidad}])

    assert "contiene" in " ".join(exc.value.detalle)

"""
Los pasos del instalador, sin HTTP.

El caso que más importa es `test_la_base_queda_fuera_de_la_caja`: es la razón
por la que la instalación tiene dos zonas y no una.
"""

from __future__ import annotations

import pytest

from backend.core import boot
from backend.core.instance import Instance
from backend.core.ports import PortError
from installer.source import pasos


# ── Paso 1: dónde ───────────────────────────────────────────────────────


def test_una_carpeta_nueva_es_valida(tmp_path):
    r = pasos.revisar_destino(str(tmp_path / "Bot"))
    assert r["valida"]
    assert r["crea_carpetas"]
    assert r["problemas"] == []


def test_una_ruta_relativa_se_rechaza():
    """Relativa se resolvería contra el cwd, y la instalación cambiaría de lugar."""
    r = pasos.revisar_destino("Bot/instalacion")
    assert not r["valida"]
    assert "absoluta" in r["problemas"][0]


def test_una_ruta_vacia_se_rechaza():
    assert not pasos.revisar_destino("")["valida"]
    assert not pasos.revisar_destino("   ")["valida"]


def test_un_archivo_no_es_destino(tmp_path):
    archivo = tmp_path / "cosa.txt"
    archivo.write_text("x")
    r = pasos.revisar_destino(str(archivo))
    assert not r["valida"]
    assert "archivo" in r["problemas"][0]


def test_una_carpeta_sin_permiso_no_revienta():
    """
    Un `exists()` sobre una ruta prohibida levanta PermissionError. Un
    instalador no puede romperse mientras alguien escribe en un campo de texto.
    """
    r = pasos.revisar_destino("/root/prohibido/bot")
    assert not r["valida"]
    assert r["problemas"]  # dice algo, en vez de propagar la excepción


def test_detecta_una_instalacion_previa(tmp_path):
    destino = tmp_path / "Bot"
    destino.mkdir()
    (destino / boot.ARCHIVO).write_text("")
    assert pasos.revisar_destino(str(destino))["instalacion_previa"] == [boot.ARCHIVO]


def test_una_carpeta_con_cosas_no_bloquea(tmp_path):
    """No se borra nada: Bot agrega lo suyo al lado."""
    destino = tmp_path / "Bot"
    destino.mkdir()
    (destino / "algo.txt").write_text("x")
    r = pasos.revisar_destino(str(destino))
    assert r["valida"]
    assert not r["vacia"]
    assert r["instalacion_previa"] == []


# ── Paso 2: la máquina ──────────────────────────────────────────────────


def test_los_chequeos_traen_los_tres(tmp_path):
    nombres = [c["nombre"] for c in pasos.revisar_maquina(str(tmp_path))]
    assert nombres == ["Python", "Cifrado", "Escritura"]


def test_sin_carpeta_elegida_la_escritura_avisa_pero_no_falla():
    escritura = pasos.revisar_maquina("")[-1]
    assert escritura["nivel"] == "warn"


def test_la_escritura_se_prueba_escribiendo(tmp_path):
    """`os.access` miente sobre discos de red y ACL de Windows."""
    assert pasos.revisar_maquina(str(tmp_path))[-1]["nivel"] == "ok"


# ── Paso 3: la caja ─────────────────────────────────────────────────────


def test_el_plan_no_crea_nada(tmp_path):
    destino = tmp_path / "Bot"
    pasos.plan(str(destino))
    assert not destino.exists()


def test_el_plan_declara_lo_abierto_y_lo_acotado(tmp_path):
    limites = {l["que"]: l["estado"] for l in pasos.plan(str(tmp_path / "Bot"))["limites"]}
    assert limites["Archivos"] == "acotado"
    assert limites["Base y llave"] == "acotado"
    assert limites["Programas"] == "acotado"
    assert limites["Plugins"] == "acotado"
    # Lo único que queda abierto, y la pantalla lo dice.
    assert limites["Red"] == "abierto"


def test_el_plan_incluye_la_carpeta_de_plugins(tmp_path):
    destino = tmp_path / "Bot"
    assert pasos.plan(str(destino))["plugins"] == str(destino / pasos.PLUGINS)


# ── Paso 4: instalar ────────────────────────────────────────────────────


def test_instalar_deja_la_instalacion_lista(tmp_path):
    r = pasos.instalar(str(tmp_path / "Bot"))
    raiz = tmp_path / "Bot"

    assert (raiz / boot.ARCHIVO).is_file()
    assert (raiz / "data" / "bot.db").is_file()
    assert (raiz / pasos.CAJA).is_dir()
    # Orden por kind, name: "agent" < "human" < "system".
    assert [a["name"] for a in r["actores"]] == ["agente-mcp", "local", "system"]
    assert r["sobrantes"] == []


def test_la_llave_se_genera_durante_la_instalacion(tmp_path):
    """
    Se fuerza en el alta para poder mostrarla. Que aparezca sola tres semanas
    después, sin que nadie sepa que hay que respaldarla, es peor.
    """
    r = pasos.instalar(str(tmp_path / "Bot"))
    assert r["llave_existe"]
    assert (tmp_path / "Bot" / "data" / "secret.key").is_file()


def test_fs_root_queda_absoluto(tmp_path):
    """
    Relativo se resolvería contra el cwd del proceso y la caja terminaría en
    otro lado. Encontrado en el QA de Windows de la primera instalación
    """
    r = pasos.instalar(str(tmp_path / "Bot"))
    escrito = (tmp_path / "Bot" / boot.ARCHIVO).read_text()
    assert f"fs_root={tmp_path / 'Bot' / pasos.CAJA}" in escrito
    assert r["arranque"]["fs_root"] == str(tmp_path / "Bot" / pasos.CAJA)


def test_instalar_crea_la_carpeta_de_plugins(tmp_path):
    r = pasos.instalar(str(tmp_path / "Bot"))
    raiz = tmp_path / "Bot"

    assert (raiz / pasos.PLUGINS).is_dir()
    assert r["arranque"]["plugins_dir"] == str(raiz / pasos.PLUGINS)


def test_plugins_dir_queda_fuera_de_la_caja(tmp_path):
    """
    Mismo motivo que la base: si un flujo con el port `fs` pudiera escribir en
    `plugins/`, un flujo comprometido podría dejar un plugin nuevo listo para
    el próximo arranque.
    """
    pasos.instalar(str(tmp_path / "Bot"))
    instancia = Instance(tmp_path / "Bot")
    try:
        fs = instancia.adapters["fs"]
        fs.write_text(str(tmp_path / "Bot" / pasos.CAJA / "a.txt"), "adentro")

        with pytest.raises(PortError, match="fuera del árbol permitido"):
            fs.read_text(str(tmp_path / "Bot" / pasos.PLUGINS / "cualquiera.py"))
    finally:
        instancia.close()


def test_no_se_instala_encima_de_otra(tmp_path):
    pasos.instalar(str(tmp_path / "Bot"))
    with pytest.raises(pasos.InstalacionError, match="Ya hay una instalación"):
        pasos.instalar(str(tmp_path / "Bot"))


def test_no_se_instala_en_un_destino_invalido(tmp_path):
    with pytest.raises(pasos.InstalacionError):
        pasos.instalar("relativa")


def test_la_base_queda_fuera_de_la_caja(tmp_path):
    """
    El motivo de las dos zonas.

    Un plugin no puede pedir los ports `storage` ni `crypto` —el núcleo se lo
    impide—, pero si la base viviera dentro de `fs_root` la alcanzaría por la
    puerta del filesystem y la separación se caería por abajo.
    """
    pasos.instalar(str(tmp_path / "Bot"))
    instancia = Instance(tmp_path / "Bot")
    try:
        fs = instancia.adapters["fs"]

        fs.write_text(str(tmp_path / "Bot" / pasos.CAJA / "a.txt"), "adentro")

        for prohibido in ("data/bot.db", "data/secret.key", boot.ARCHIVO):
            with pytest.raises(PortError, match="fuera del árbol permitido"):
                fs.read_text(str(tmp_path / "Bot" / prohibido))
    finally:
        instancia.close()


def test_la_instalacion_pasa_el_doctor_del_nucleo(tmp_path):
    """Instalar y que `doctor` diga que falta algo sería instalar mal."""
    from backend.core.doctor import run_checks

    pasos.instalar(str(tmp_path / "Bot"))
    instancia = Instance(tmp_path / "Bot")
    try:
        report = run_checks(
            root=tmp_path / "Bot",
            registry=instancia.registry,
            config=instancia.effective_config(),
            workflows=instancia.workflows.list(),
        )
        assert not report.errors, [c.name for c in report.errors]
    finally:
        instancia.close()


def test_ningun_programa_se_puede_ejecutar(tmp_path):
    """
    Lo que la pantalla de límites promete, hecho cumplir.

    La tupla vacía es "ningún ejecutable" y la clave ausente es "cualquiera".
    El instalador escribe la primera, y el viaje render()/load() tiene que
    conservarla: si en el medio se convirtiera en ausente, el sandbox se
    abriría solo y la pantalla estaría mintiendo.
    """
    from backend.adapters.process_subprocess import SubprocessAdapter

    pasos.instalar(str(tmp_path / "Bot"))

    escrito = (tmp_path / "Bot" / boot.ARCHIVO).read_text()
    assert "\nprocess_allowlist=\n" in escrito, "tiene que quedar presente y vacía, no comentada"

    releido = boot.load(tmp_path / "Bot", {})
    assert releido.process_allowlist == ()

    with pytest.raises(PortError, match="no está en la lista"):
        SubprocessAdapter(allowlist=releido.process_allowlist).run(["echo", "hola"])


def test_el_arranque_escrito_no_tiene_observaciones(tmp_path):
    """
    Se valida antes de escribir, no después: un boot.env con un valor que no
    hace lo que dice es peor que no tenerlo, porque parece configuración.
    """
    pasos.instalar(str(tmp_path / "Bot"))
    assert boot.validar(boot.load(tmp_path / "Bot", {})) == []


def test_la_instalacion_pasa_el_doctor_completo(tmp_path):
    """
    Con `boot` y `crypto`, que son los dos chequeos que más importan en una
    máquina nueva y que no corren si el llamador no los pasa.
    """
    from backend.core.doctor import run_checks

    pasos.instalar(str(tmp_path / "Bot"))
    instancia = Instance(tmp_path / "Bot")
    try:
        report = run_checks(
            root=tmp_path / "Bot",
            registry=instancia.registry,
            config=instancia.effective_config(),
            workflows=instancia.workflows.list(),
            boot=instancia.boot,
            crypto=instancia.crypto,
        )
        assert not report.errors, [c.name for c in report.errors]
        nombres = [c.name for c in report.checks]
        assert {"Arranque", "Almacenamiento", "Cifrado"} <= set(nombres)
    finally:
        instancia.close()


def test_boot_env_se_escribe_con_bom(tmp_path):
    """
    Windows es el destino, y ahí las herramientas obvias —Notepad, `type` de
    PowerShell 5.1— leen UTF-8 sin BOM como cp1252 y muestran los acentos
    rotos. `python -m backend.core init` escribe con BOM; el instalador tiene
    que escribir igual, o el mismo archivo tendría dos codificaciones según
    quién lo creó.
    """
    pasos.instalar(str(tmp_path / "Bot"))
    crudo = (tmp_path / "Bot" / boot.ARCHIVO).read_bytes()

    assert crudo.startswith(b"\xef\xbb\xbf")
    # Y el núcleo lo relee sin tropezarse con el BOM.
    assert boot.load(tmp_path / "Bot", {}).process_allowlist == ()


def test_el_chequeo_de_cifrado_no_se_conforma_con_importar(monkeypatch, tmp_path):
    """
    El caso real: `cryptography` presente pero con `_cffi_backend` faltando.

    La primera versión hacía `import cryptography` y daba verde; la instalación
    reventaba después, al generar la llave. Un chequeo que aprueba una
    instalación rota es peor que no tenerlo.
    """
    from cryptography.fernet import Fernet

    def revienta(*_a, **_k):
        raise ModuleNotFoundError("No module named '_cffi_backend'")

    monkeypatch.setattr(Fernet, "generate_key", staticmethod(revienta))

    cifrado = pasos.revisar_maquina(str(tmp_path))[1]
    assert cifrado["nombre"] == "Cifrado"
    assert cifrado["nivel"] == "error"
    assert "_cffi_backend" in " ".join(cifrado["detalle"])


def test_el_chequeo_de_cifrado_aprueba_uno_que_funciona(tmp_path):
    cifrado = pasos.revisar_maquina(str(tmp_path))[1]
    assert cifrado["nivel"] == "ok"
    assert "cryptography" in cifrado["mensaje"]


# ── plugins/ y el puntero a la instalación ──────────────────────────────


def test_los_plugins_quedan_fuera_de_la_caja(tmp_path):
    """
    La otra dirección del mismo argumento que `data/`: plugins/ es código que el
    núcleo carga al arrancar, y un flujo con el port fs no puede poder escribir ahí.
    """
    pasos.instalar(str(tmp_path / "Bot"))
    raiz = tmp_path / "Bot"
    assert (raiz / pasos.PLUGINS).is_dir()
    cargado = boot.load(raiz, {})
    assert cargado.plugins_dir == raiz / pasos.PLUGINS
    caja = (raiz / pasos.CAJA).resolve()
    assert caja not in cargado.plugins_dir.resolve().parents
    assert cargado.plugins_dir.resolve() != caja

    instancia = Instance(raiz)
    try:
        with pytest.raises(PortError, match="fuera del árbol permitido"):
            instancia.adapters["fs"].write_text(str(raiz / pasos.PLUGINS / "malo.py"), "PLUGIN = 1")
    finally:
        instancia.close()


def test_el_plan_nombra_la_carpeta_de_plugins(tmp_path):
    p = pasos.plan(str(tmp_path / "Bot"))
    assert p["plugins"] == str(tmp_path / "Bot" / pasos.PLUGINS)
    assert any(l["que"] == "Plugins" and l["estado"] == "acotado" for l in p["limites"])


def test_instalar_anota_la_instalacion_para_abrir_bot(tmp_path, config_de_usuario_aislada):
    from webapp import ubicacion

    r = pasos.instalar(str(tmp_path / "Bot"))
    assert r["anotada_en"]
    assert ubicacion.ultima() == (tmp_path / "Bot").resolve()
    # Y la webapp, sin que nadie le diga nada, arranca contra esa carpeta.
    programa = tmp_path / "programa"
    programa.mkdir()
    assert ubicacion.resolver_root(programa) == (tmp_path / "Bot").resolve()


def test_el_comando_de_la_webapp_apunta_a_la_instalacion(tmp_path):
    comando = pasos.comando_webapp(tmp_path / "Bot", 8010)
    assert comando[1:3] == ["-m", "webapp"]
    assert "--root" in comando and str(tmp_path / "Bot") in comando
    assert "--port" in comando and "8010" in comando
    assert "--no-abrir" in comando


def test_abrir_sin_instalacion_falla_antes_de_lanzar_nada(tmp_path):
    with pytest.raises(pasos.InstalacionError, match="no hay una instalación"):
        pasos.abrir_webapp(str(tmp_path / "nada"), 8010)


def test_una_instalacion_de_prueba_no_cambia_cual_abre_el_bot(tmp_path, monkeypatch):
    """
    Crear una instalación descartable no puede pisar "la última instalación"
    del usuario: si después se borra la carpeta, el Bot arranca contra la
    carpeta del programa y ni los límites se pueden guardar. Pasó en desarrollo.
    """
    llamadas = []
    monkeypatch.setattr(pasos.ubicacion, "registrar", lambda raiz: llamadas.append(raiz) or raiz)

    pasos.instalar(str(tmp_path / "prueba"), registrar=False)
    assert llamadas == []

    pasos.instalar(str(tmp_path / "real"))
    assert len(llamadas) == 1

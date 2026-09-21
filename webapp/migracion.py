"""
Comparar el contenido de esta instalación contra otro Bot.

El origen es **siempre este Bot**, leído de su propia base y sin pasar por HTTP.
No es una simplificación: es lo que hace posible migrar de verdad. Un secreto no
sale por la API de nadie (ver #3), así que el único que puede leer los secretos
de una instalación es la instalación misma. Por eso la migración empuja —corre
en el origen, lee lo suyo local y lo escribe en el destino— en vez de tirar. De
paso, cada Bot cifra con su propia llave al guardar y no hay que copiar ninguna.

**El diff no toca un secreto.** Los campos que la colección declara `secret`
quedan fuera de la comparación por construcción: de los dos lados valen `None`,
así que compararlos sería comparar dos tapas. Lo que se puede decir de un item
así es que no se puede decir nada — el estado `indeterminado`. Los valores
secretos aparecen recién al migrar, que es otra operación y otro endpoint.

La forma de la salida y el significado de cada estado son **los mismos** que los
de `bots.comparar` del catálogo de plugins, a propósito: ese tool reemplaza su
cálculo local por una llamada acá, y así no hay dos implementaciones de "qué
está distinto entre estos dos Bots" que se separen con el tiempo. Si cambia algo
de esta forma, cambia allá.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

# De un flujo, lo que significa algo al compararlo. `updated_at` queda afuera:
# difiere siempre —son dos bases distintas— y no dice nada del contenido.
CAMPOS_FLUJO = ("content", "folder", "state", "description")
# De un item de colección, lo que es del núcleo y no del plugin.
CAMPOS_DEL_NUCLEO = ("_updated_at", "_error")

ESTADOS = ("igual", "distinto", "solo_origen", "solo_destino", "indeterminado")
QUE = ("flujos", "registros", "env")

TIMEOUT = 20


class MigracionError(Exception):
    """Lo que el operador tiene que poder leer: nunca un traceback."""


# ── Hablar con el otro Bot ──────────────────────────────────────────────


def _pedir(url: str, camino: str) -> dict | list:
    """
    Un GET a la API del otro Bot.

    Los errores se traducen acá y no en el handler porque el que los va a leer
    está mirando una pantalla que dice "comparar con Impresión 2": "no se pudo
    conectar" sirve, `URLError(ConnectionRefusedError(...))` no.
    """
    destino = url.rstrip("/") + camino
    try:
        with urllib.request.urlopen(destino, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MigracionError(f"{url} contestó 404 en {camino}: ¿es un Bot?") from None
        raise MigracionError(f"{url} contestó {exc.code} en {camino}") from None
    except urllib.error.URLError as exc:
        raise MigracionError(f"No se pudo conectar con {url}: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise MigracionError(f"No se pudo conectar con {url}: {exc}") from None
    except json.JSONDecodeError:
        raise MigracionError(f"{url} contestó algo que no es JSON: ¿es un Bot?") from None


# ── De cada lado, el mapa {clave: {campo: valor}} ───────────────────────


def flujos_locales(instancia) -> dict[str, dict]:
    return {
        wf.name: {campo: wf.to_dict()[campo] for campo in CAMPOS_FLUJO}
        for wf in instancia.workflows.list()
    }


def flujos_remotos(url: str) -> dict[str, dict]:
    """
    Un pedido por flujo, no uno solo: `GET /workflows` no trae el `content`
    (`to_dict(with_content=False)`), y sin el contenido comparar dos flujos es
    comparar sus carpetas.
    """
    listado = _pedir(url, "/api/core/workflows")
    if not isinstance(listado, list):
        raise MigracionError(f"{url} contestó algo raro en /workflows")
    salida = {}
    for entrada in listado:
        nombre = entrada.get("name")
        if not nombre:
            continue
        completo = _pedir(url, f"/api/core/workflows/{urllib.parse.quote(str(nombre))}")
        salida[nombre] = {campo: completo.get(campo) for campo in CAMPOS_FLUJO}
    return salida


def _mapa_de_items(datos: dict) -> tuple[dict[str, dict], list[str], str]:
    """De lo que devuelve `GET /resources/...`: los items, los secretos y la clave."""
    definicion = datos.get("resource") or {}
    campos = definicion.get("fields") or []
    secretos = sorted(c["name"] for c in campos if c.get("secret"))
    clave = definicion.get("key_field") or "name"
    mapa = {}
    for item in datos.get("items") or []:
        nombre = item.get(clave)
        if nombre is None:
            continue
        mapa[str(nombre)] = {
            k: v for k, v in item.items() if k not in CAMPOS_DEL_NUCLEO and k != clave
        }
    return mapa, secretos, clave


def items_locales(instancia, plugin: str, coleccion: str) -> tuple[dict, list[str], str]:
    """
    Lo mismo que devolvería `GET /resources/{plugin}/{coleccion}`, leído de esta
    base — **con los secretos tapados igual**. El diff no los necesita y así no
    hay una segunda puerta por la que salgan.
    """
    definicion = instancia.resource_definition(plugin, coleccion)
    if definicion is None:
        raise MigracionError(f"Acá no hay una colección '{coleccion}' del plugin '{plugin}'")
    return _mapa_de_items({
        "resource": definicion.to_dict(),
        "items": instancia.resource_items_masked(plugin, coleccion),
    })


def items_remotos(url: str, plugin: str, coleccion: str) -> tuple[dict, list[str], str]:
    datos = _pedir(url, f"/api/core/resources/{plugin}/{coleccion}")
    if not isinstance(datos, dict) or "items" not in datos:
        raise MigracionError(f"{url} no tiene la colección '{plugin}/{coleccion}'")
    return _mapa_de_items(datos)


def _mapa_de_env(variables) -> dict[str, dict]:
    """
    {nombre: {secret, value?}}.

    El `value` de una secreta no está —ni en `None`— porque `EnvVar.to_dict` no
    lo pone: la clave ausente es la que dice que no se sabe, y que existiera en
    `None` haría parecer que está vacía.

    Las `undeclared` quedan afuera: son nombres que un flujo referencia y nadie
    cargó. Aparecen en el listado porque son las que van a romper una ejecución,
    pero no son variables — no hay nada que comparar ni que migrar.
    """
    return {
        v["name"]: {k: valor for k, valor in v.items() if k in ("secret", "value")}
        for v in variables
        if not v.get("undeclared")
    }


def env_locales(instancia) -> dict[str, dict]:
    return _mapa_de_env(instancia.env_listing())


def env_remotas(url: str) -> dict[str, dict]:
    datos = _pedir(url, "/api/core/env")
    variables = datos.get("items") if isinstance(datos, dict) else datos
    if not isinstance(variables, list):
        raise MigracionError(f"{url} contestó algo raro en /env: ¿es un Bot?")
    return _mapa_de_env(variables)


# ── El diff ─────────────────────────────────────────────────────────────


def diferencias(origen: dict, destino: dict, ocultos: dict, detalle: bool) -> tuple[list, dict]:
    """
    El diff entre dos mapas {clave: {campo: valor}}: (items, resumen).

    La única función que decide qué significa "distinto". `indeterminado` es el
    item cuyos campos visibles coinciden pero que tiene alguno que no se puede
    ver: no sale por la API de ninguno de los dos lados, así que podría diferir
    justo ahí, y decir "igual" sería afirmar algo que nadie puede ver.

    `ocultos` va **por clave** y no por colección porque en `env` la secrecía es
    de cada variable, no de la tabla: ahí conviven una `TIMEOUT` que se compara
    entera con una `API_KEY` de la que no se sabe nada. En una colección, en
    cambio, todas las claves llevan el mismo conjunto.
    """
    items = []
    for clave in sorted(set(origen) | set(destino)):
        aca, alla = origen.get(clave), destino.get(clave)
        if alla is None:
            items.append({"clave": clave, "estado": "solo_origen", "campos": []})
            continue
        if aca is None:
            items.append({"clave": clave, "estado": "solo_destino", "campos": []})
            continue

        tapados = ocultos.get(clave) or set()
        distintos = sorted(
            campo for campo in set(aca) | set(alla)
            if campo not in tapados and aca.get(campo) != alla.get(campo)
        )
        if distintos:
            entrada = {"clave": clave, "estado": "distinto", "campos": distintos}
            if detalle:
                entrada["origen"] = {c: aca.get(c) for c in distintos}
                entrada["destino"] = {c: alla.get(c) for c in distintos}
            items.append(entrada)
        else:
            items.append({
                "clave": clave,
                "estado": "indeterminado" if tapados else "igual",
                "campos": [],
            })

    resumen = dict.fromkeys(ESTADOS, 0)
    for item in items:
        resumen[item["estado"]] += 1
    return items, resumen


def comparar(instancia, *, destino_url: str, destino_nombre: str = "", que: str = "flujos",
             plugin: str = "", coleccion: str = "", detalle: bool = False,
             url_propia: str = "") -> dict:
    """El informe completo, con la forma que también devuelve `bots.comparar`."""
    if que not in QUE:
        raise MigracionError(f"'{que}' no es algo que se pueda comparar: {', '.join(QUE)}")
    if not destino_url:
        raise MigracionError("Falta la dirección del Bot destino")
    if url_propia and destino_url.rstrip("/") == url_propia.rstrip("/"):
        raise MigracionError("El destino es este mismo Bot")

    secretos: list[str] = []
    if que == "flujos":
        aca = flujos_locales(instancia)
        alla = flujos_remotos(destino_url)
        comparados = list(CAMPOS_FLUJO)
        ocultos: dict[str, set] = {}
    elif que == "env":
        aca = env_locales(instancia)
        alla = env_remotas(destino_url)
        # Por variable: una `TIMEOUT` se compara entera, de una `API_KEY` no se
        # sabe nada. Alcanza con que **un** lado la tenga marcada secreta.
        secretos = ["value"]
        ocultos = {
            nombre: {"value"}
            for nombre in set(aca) | set(alla)
            if (aca.get(nombre) or {}).get("secret") or (alla.get(nombre) or {}).get("secret")
        }
        comparados = ["secret", "value"]
    else:
        if not plugin or not coleccion:
            raise MigracionError("Con 'registros' hacen falta el plugin y la colección")
        aca, secretos_aca, _ = items_locales(instancia, plugin, coleccion)
        alla, secretos_alla, _ = items_remotos(destino_url, plugin, coleccion)
        # La unión: si un lado declara un campo secreto que el otro no, el item
        # tampoco se puede comparar. Pasa con dos versiones del mismo plugin.
        secretos = sorted(set(secretos_aca) | set(secretos_alla))
        comparados = sorted(
            {c for item in (*aca.values(), *alla.values()) for c in item} - set(secretos)
        )
        ocultos = {clave: set(secretos) for clave in set(aca) | set(alla)} if secretos else {}

    items, resumen = diferencias(aca, alla, ocultos, detalle)
    return {
        "origen": {"bot": "este Bot", "url": url_propia},
        "destino": {"bot": destino_nombre or destino_url, "url": destino_url},
        "que": que,
        "coleccion": f"{plugin}/{coleccion}" if que == "registros" else "",
        "campos_comparados": comparados,
        "campos_secretos": secretos,
        "items": items,
        "resumen": resumen,
    }


# ── Empujar ─────────────────────────────────────────────────────────────


def _escribir(url: str, camino: str, cuerpo: dict) -> None:
    """Un PUT a la API del otro Bot."""
    destino = url.rstrip("/") + camino
    pedido = urllib.request.Request(
        destino, data=json.dumps(cuerpo).encode("utf-8"), method="PUT",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except Exception:  # noqa: BLE001 — el cuerpo del error es best effort
            pass
        raise MigracionError(detalle or f"el destino contestó {exc.code}") from None
    except urllib.error.URLError as exc:
        raise MigracionError(f"no se pudo conectar: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise MigracionError(f"no se pudo conectar: {exc}") from None


def migrar(instancia, *, destino_url: str, que: str, claves: list[str],
           plugin: str = "", coleccion: str = "", url_propia: str = "") -> dict:
    """
    Escribe en el otro Bot lo que se eligió de acá. Clave por clave.

    **Es el único lugar donde un secreto se lee en claro**, y sólo el de esta
    instalación: `resource_store.read` descifra los de una colección y
    `env.resolve()` los de `env` —write-only es sobre la API, no sobre el
    núcleo—. De ahí salen a un PUT del destino, que los vuelve a cifrar con su
    propia llave. Por eso no hay que copiar ningún archivo de llave, y un
    secreto robado en una instalación no vale en la otra.

    Lo que hay que saber antes de usarlo: **el secreto viaja en claro por la
    red.** La API es HTTP sin TLS y sin autenticación —decisión tomada, ver
    `docs/arquitectura.md`—, así que cualquiera que escuche la LAN mientras esto
    corre lo ve. No es peor que cualquier otro PUT de la API, pero es la primera
    vez que un secreto sale de una instalación, y quien lo dispara tiene que
    saberlo: la pantalla lo dice antes de empujar.

    Clave por clave y no todo o nada: si el destino rechaza uno —un flujo que no
    parsea contra su versión del núcleo, un plugin que allá no está— los demás
    tienen que entrar igual, y el informe dice cuál falló y por qué. Deshacer a
    medias sería peor: no hay transacción del otro lado.
    """
    if que not in QUE:
        raise MigracionError(f"'{que}' no es algo que se pueda migrar: {', '.join(QUE)}")
    if not destino_url:
        raise MigracionError("Falta la dirección del Bot destino")
    if url_propia and destino_url.rstrip("/") == url_propia.rstrip("/"):
        raise MigracionError("El destino es este mismo Bot")
    if not claves:
        raise MigracionError("No se eligió nada para migrar")

    if que == "registros" and (not plugin or not coleccion):
        raise MigracionError("Con 'registros' hacen falta el plugin y la colección")

    resultados = []
    for clave in claves:
        try:
            _empujar_uno(instancia, destino_url, que, clave, plugin, coleccion)
        except MigracionError as exc:
            resultados.append({"clave": clave, "ok": False, "error": str(exc)})
        else:
            resultados.append({"clave": clave, "ok": True, "error": ""})

    return {
        "destino": destino_url,
        "que": que,
        "coleccion": f"{plugin}/{coleccion}" if que == "registros" else "",
        "resultados": resultados,
        "migrados": sum(1 for r in resultados if r["ok"]),
        "fallados": sum(1 for r in resultados if not r["ok"]),
    }


def _empujar_uno(instancia, url: str, que: str, clave: str, plugin: str, coleccion: str) -> None:
    if que == "flujos":
        wf = instancia.workflows.get(clave)
        if wf is None:
            raise MigracionError(f'acá ya no está el flujo "{clave}"')
        datos = wf.to_dict()
        _escribir(url, f"/api/core/workflows/{urllib.parse.quote(clave)}", {
            "content": datos["content"], "folder": datos["folder"],
            "state": datos["state"], "description": datos["description"],
        })
        return

    if que == "env":
        variable = instancia.env.get(clave)
        if variable is None:
            raise MigracionError(f'acá ya no está la variable "{clave}"')
        if variable.unreadable:
            raise MigracionError(
                f'"{clave}" está cifrada con otra llave y acá tampoco se puede leer')
        # `resolve()` es lo que ve un flujo en `{env.CLAVE}`: el valor en claro,
        # secreta o no. Es la lectura local que la API no ofrece.
        valor = instancia.env.resolve().get(clave)
        if valor is None:
            raise MigracionError(f'"{clave}" no tiene valor cargado')
        _escribir(url, f"/api/core/env/{urllib.parse.quote(clave)}",
                  {"value": valor, "secret": variable.secret})
        return

    definicion = instancia.resource_definition(plugin, coleccion)
    if definicion is None:
        raise MigracionError(f"acá no hay una colección '{coleccion}' del plugin '{plugin}'")
    store = instancia.resource_store(plugin, definicion)
    try:
        item = store.read(clave)
    except Exception:  # noqa: BLE001 — ResourceError vive en el núcleo
        raise MigracionError(f'acá ya no está "{clave}"') from None
    item = {k: v for k, v in item.items() if k not in CAMPOS_DEL_NUCLEO}
    item.setdefault(definicion.key_field, clave)
    _escribir(url, f"/api/core/resources/{plugin}/{coleccion}/{urllib.parse.quote(clave)}",
              {"item": item})

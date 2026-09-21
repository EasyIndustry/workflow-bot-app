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


def _pedir(url: str, camino: str, faltante_ok: bool = False) -> dict | list | None:
    """
    Un GET a la API del otro Bot. Con `faltante_ok`, un 404 devuelve `None`.

    Los errores se traducen acá y no en el handler porque el que los va a leer
    está mirando una pantalla que dice "comparar con Impresión 2": "no se pudo
    conectar" sirve, `URLError(ConnectionRefusedError(...))` no.
    """
    destino = url.rstrip("/") + camino
    try:
        with urllib.request.urlopen(destino, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and faltante_ok:
            return None
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


def items_remotos(url: str, plugin: str, coleccion: str) -> tuple[dict, list[str], bool]:
    """
    Los items del otro Bot, y si **tiene** la colección.

    Que al destino le falte el plugin no es un error: es el caso de un Bot nuevo
    de la flota, al que justamente se le va a copiar todo. Devuelve el mapa
    vacío y lo dice, para que quien decide qué copiar distinga "la tiene y está
    vacía" de "ni siquiera la tiene".

    Del lado del **origen** sí es un error, y la asimetría es a propósito: pedir
    una colección que este Bot no tiene es casi siempre un nombre mal escrito, y
    no hay nada que comparar *desde* — un informe vacío ahí parecería una
    respuesta.
    """
    datos = _pedir(url, f"/api/core/resources/{plugin}/{coleccion}", faltante_ok=True)
    if datos is None:
        return {}, [], False
    if not isinstance(datos, dict) or "items" not in datos:
        raise MigracionError(f"{url} contestó algo raro para '{plugin}/{coleccion}'")
    mapa, secretos, _ = _mapa_de_items(datos)
    return mapa, secretos, True


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
    # Siempre presente, como `campos_secretos`: quien dibuja no tiene que
    # distinguir "no pasa" de "no me lo dijeron".
    destino_sin_coleccion = False
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
        alla, secretos_alla, tiene = items_remotos(destino_url, plugin, coleccion)
        destino_sin_coleccion = not tiene
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
        "destino_sin_coleccion": destino_sin_coleccion,
        "items": items,
        "resumen": resumen,
    }


# ── Empujar ─────────────────────────────────────────────────────────────


def _entregar(url: str, sobre: dict) -> dict:
    """
    El sobre sellado al endpoint que lo recibe.

    Un 404 acá significa que el destino tiene una versión de app sin este
    endpoint, y se dice así: un 404 crudo no le dice nada a quien opera. **No
    hay caída a texto plano.** Un fallback con aviso dejaría que sea quien
    ataca el que elige el camino sin cifrar —se presenta como un destino viejo
    y fuerza el downgrade—, y el aviso lo lee alguien que lo pasa de largo.
    """
    destino = url.rstrip("/") + "/api/core/migrar/recibir"
    pedido = urllib.request.Request(
        destino, data=json.dumps(sobre).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MigracionError(
                f"{url} tiene una versión de la app que no sabe recibir una migración. "
                "Hay que actualizarlo desde Config → Actualizaciones.") from None
        detalle = ""
        try:
            detalle = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except Exception:  # noqa: BLE001 — el cuerpo del error es best effort
            pass
        raise MigracionError(detalle or f"el destino contestó {exc.code}") from None
    except urllib.error.URLError as exc:
        raise MigracionError(f"no se pudo conectar con {url}: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise MigracionError(f"no se pudo conectar con {url}: {exc}") from None
    except json.JSONDecodeError:
        raise MigracionError(f"{url} contestó algo que no es JSON") from None


def migrar(instancia, *, emparejado: dict, destino_url: str, que: str, claves: list[str],
           plugin: str = "", coleccion: str = "", url_propia: str = "") -> dict:
    """
    Manda al otro Bot, en un sobre cifrado, lo que se eligió de acá.

    **Es el único lugar donde un secreto se lee en claro**, y sólo el de esta
    instalación: `resource_store.read` descifra los de una colección y
    `env.resolve()` los de `env` —write-only es sobre la API, no sobre el
    núcleo—. Por eso la migración corre en el origen: nadie más los puede leer.

    De ahí no salen en claro a la red: van adentro de un sobre sellado con la
    clave de este emparejamiento (`webapp/emparejamiento.py`), que el destino
    abre y vuelve a cifrar con su propia llave al guardar. Sin emparejamiento no
    se migra — no hay camino en claro, a propósito.
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

    contenido = {"que": que, "plugin": plugin, "coleccion": coleccion, "items": []}
    fallados = []
    for clave in claves:
        try:
            contenido["items"].append(_reunir_uno(instancia, que, clave, plugin, coleccion))
        except MigracionError as exc:
            # Lo que no se pudo leer de este lado ni sale: se informa igual que
            # lo que el destino rechace, en la misma lista.
            fallados.append({"clave": clave, "ok": False, "error": str(exc)})

    resultados = []
    if contenido["items"]:
        from webapp import emparejamiento as emp

        # El sobre se arma **acá**, en el momento de mandarlo, porque su `ttl`
        # empieza a correr al sellarlo.
        respuesta = _entregar(destino_url, emp.sellar(emparejado, contenido))
        resultados = respuesta.get("resultados") or []

    resultados = resultados + fallados
    return {
        "destino": destino_url,
        "emparejamiento": emparejado["id"],
        "que": que,
        "coleccion": f"{plugin}/{coleccion}" if que == "registros" else "",
        "resultados": resultados,
        "migrados": sum(1 for r in resultados if r["ok"]),
        "fallados": sum(1 for r in resultados if not r["ok"]),
    }


def _reunir_uno(instancia, que: str, clave: str, plugin: str, coleccion: str) -> dict:
    """Lo que hay que mandar de una clave, leído de esta base. Con su secreto."""
    if que == "flujos":
        wf = instancia.workflows.get(clave)
        if wf is None:
            raise MigracionError(f'acá ya no está el flujo "{clave}"')
        datos = wf.to_dict()
        return {"clave": clave, "datos": {
            "content": datos["content"], "folder": datos["folder"],
            "state": datos["state"], "description": datos["description"],
        }}

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
        return {"clave": clave, "datos": {"value": valor, "secret": variable.secret}}

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
    return {"clave": clave, "datos": {"item": item}}


def aplicar(instancia, contenido: dict) -> list[dict]:
    """
    El lado que **recibe**: escribe en esta base lo que venía en el sobre.

    Clave por clave y no todo o nada: si uno no entra —un flujo que no parsea
    contra esta versión del núcleo, una colección de un plugin que acá no está—
    los demás entran igual y el informe dice cuál falló y por qué. Deshacer a
    medias sería peor, y no hay transacción que abarque esto.
    """
    que = contenido.get("que")
    plugin = contenido.get("plugin") or ""
    coleccion = contenido.get("coleccion") or ""
    resultados = []
    for entrada in contenido.get("items") or []:
        clave = entrada.get("clave")
        try:
            _aplicar_uno(instancia, que, clave, entrada.get("datos") or {}, plugin, coleccion)
        except Exception as exc:  # noqa: BLE001 — cualquier error del núcleo es del item
            resultados.append({"clave": clave, "ok": False, "error": str(exc)})
        else:
            resultados.append({"clave": clave, "ok": True, "error": ""})
    return resultados


def _aplicar_uno(instancia, que: str, clave: str, datos: dict, plugin: str, coleccion: str) -> None:
    if que == "flujos":
        instancia.workflows.save(
            clave, content=datos.get("content", ""), folder=datos.get("folder", ""),
            state=datos.get("state", "enabled"), description=datos.get("description", ""))
        return
    if que == "env":
        instancia.env.save(clave, datos.get("value", ""), secret=bool(datos.get("secret")))
        return

    definicion = instancia.resource_definition(plugin, coleccion)
    if definicion is None:
        # El caso de un Bot que no tiene ese plugin: se dice qué falta, en vez
        # de un error del almacén que no nombra al plugin.
        raise MigracionError(
            f"este Bot no tiene la colección '{coleccion}' del plugin '{plugin}': "
            "hay que instalarlo antes de migrarle esto")
    instancia.resource_store(plugin, definicion).write(clave, datos.get("item") or {})

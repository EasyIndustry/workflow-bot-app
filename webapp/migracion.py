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


# ── El diff ─────────────────────────────────────────────────────────────


def diferencias(origen: dict, destino: dict, secretos: list, detalle: bool) -> tuple[list, dict]:
    """
    El diff entre dos mapas {clave: {campo: valor}}: (items, resumen).

    La única función que decide qué significa "distinto". `indeterminado` es el
    item cuyos campos visibles coinciden pero cuya colección declara campos
    `secret`: no salen por la API de ninguno de los dos lados, así que podría
    diferir justo ahí y decir "igual" sería afirmar algo que nadie puede ver.
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

        distintos = sorted(
            campo for campo in set(aca) | set(alla)
            if campo not in secretos and aca.get(campo) != alla.get(campo)
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
                "estado": "indeterminado" if secretos else "igual",
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
    if que not in ("flujos", "registros"):
        raise MigracionError(f"'{que}' no es algo que se pueda comparar: flujos o registros")
    if not destino_url:
        raise MigracionError("Falta la dirección del Bot destino")
    if url_propia and destino_url.rstrip("/") == url_propia.rstrip("/"):
        raise MigracionError("El destino es este mismo Bot")

    secretos: list[str] = []
    if que == "flujos":
        aca = flujos_locales(instancia)
        alla = flujos_remotos(destino_url)
        comparados = list(CAMPOS_FLUJO)
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

    items, resumen = diferencias(aca, alla, secretos, detalle)
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

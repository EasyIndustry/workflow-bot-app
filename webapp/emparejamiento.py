"""
La clave compartida entre dos Bots, y el sobre con el que se hablan.

Migrar pone un secreto en la red, y la API es HTTP sin TLS. TLS acá no es
práctico: la instalación es local, muchas veces sin internet, y no hay ninguna
autoridad que firme nada. Así que lo que viaja va adentro de un **sobre**
cifrado con una clave **por conexión**, distinta de la llave local de cada Bot.

Por qué por conexión y no la llave local: la local cifra en reposo y no puede
salir de la máquina nunca. Usarla para transporte obligaría a compartirla, y con
eso un secreto robado en una instalación valdría en la otra. Con una clave por
par, comprometer el par no compromete lo guardado en ninguno de los dos.

**La clave la genera el destino y se copia una vez al origen, a mano.** No se
negocia sola al conectarse, y eso no es una simplificación: si se intercambiara
sola en el primer contacto no habría autenticación ninguna — cualquier máquina
de la red se emparejaría sola, y un intermediario también. El copiado a mano es
lo que ata la clave a una persona que puede ver las dos máquinas, y es la
primera cosa autenticada que tiene esta API.

**Para que eso sea cierto, emparejar se hace sentado en la máquina.** Generar,
importar, listar y olvidar sólo responden a un pedido que sale del propio Bot
(`127.0.0.1`); el resto de la API escucha en toda la red (`--red`) y no tiene
autenticación (#4), así que si estos endpoints estuvieran abiertos cualquiera
pediría un código y se emparejaría solo — y ahí el "copiado a mano" no ataría
nada. Recibir un sobre sí queda abierto, porque ahí la credencial es la clave.
La contra es real: no se puede emparejar desde otra PC aunque el Bot se opere
así. Es lo que corresponde hasta que #4 traiga una autenticación de verdad, y
además es coherente con el diseño — emparejar es justamente lo que hace alguien
que puede ver las dos máquinas.

Fernet, que es lo que el núcleo ya usa para `env`. Criptografía propia no: es la
peor clase de código propio, y lo dice el adapter del núcleo mejor que esto.

## Lo que este sobre **no** resuelve

- **Replay, del todo.** `Fernet.decrypt` no mira el timestamp si no se le pasa
  `ttl`, así que va con uno corto. Pero el `ttl` **achica la ventana, no cierra
  el replay**: adentro de esos segundos el mismo sobre sigue siendo válido. El
  ataque que importa acá no es que lean un secreto sino que reenvíen una
  migración vieja y **reviertan** un secreto rotado al valor anterior, que es el
  que quien lo capturó ya conoce. Cerrarlo pide que el receptor recuerde los
  sobres ya vistos, o que dé un nonce de un solo uso. **Está pendiente.** Si
  alguien lee esto más adelante: no está resuelto, sólo acotado.
- **El resto de la API.** Las rutas que escriben y ejecutan siguen sin
  autenticación (#4). Esto protege una migración, no el Bot.

## Dónde vive

En `data/`, al lado de `secret.key` y por el mismo motivo que la llave está
fuera de la base: un backup del `.db` no tiene que llevarse con qué descifrar.
`data/` además queda fuera de `fs_root`, así que un flujo con el port `fs` no lo
alcanza.

No depende de ningún plugin. Un emparejamiento se identifica con su propio id,
no con la colección "Bots conocidos" del plugin `bots`: si ese plugin no está
instalado, esto funciona igual.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

# Leer-modificar-escribir el archivo entero, sin candado, pierde una fila cuando
# se cruzan dos escrituras — y `anotar_uso` corre en **cada** sobre recibido, así
# que dos migraciones a la vez alcanzan. El `replace` protege de un archivo a
# medias, no de una actualización perdida, y lo que se pierde es un
# emparejamiento que hay que rehacer a mano en dos máquinas. Todo el acceso pasa
# por este proceso: cada instalación tiene su `data/`.
_CANDADO = threading.Lock()

ARCHIVO = "emparejamientos.json"
VERSION_ARCHIVO = 1

# La versión del sobre va **afuera** del texto cifrado: el que recibe tiene que
# saber cómo parsearlo antes de poder descifrarlo.
VERSION_SOBRE = 1

# Un sobre se arma en el momento del empuje, así que su vida útil es la de un
# request. Corto a propósito — ver "Lo que este sobre no resuelve".
TTL_SOBRE = 120


class EmparejamientoError(Exception):
    """Un problema que la pantalla puede mostrar tal cual."""


def _ruta(data_dir: Path) -> Path:
    return Path(data_dir) / ARCHIVO


def _leer(data_dir: Path) -> list[dict]:
    ruta = _ruta(data_dir)
    if not ruta.is_file():
        return []
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmparejamientoError(f"No se pudo leer {ruta.name}: {exc}") from None
    return datos.get("emparejamientos") or []


def _escribir(data_dir: Path, filas: list[dict]) -> None:
    ruta = _ruta(data_dir)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Archivo temporal y `replace`: si se corta la luz a mitad de escritura, el
    # anterior sigue entero. Perder el archivo es perder todos los
    # emparejamientos y tener que rehacerlos de a uno en las dos máquinas.
    temporal = ruta.with_suffix(".json.nuevo")
    temporal.write_text(
        json.dumps({"version": VERSION_ARCHIVO, "emparejamientos": filas},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    temporal.replace(ruta)


def _sin_clave(fila: dict) -> dict:
    """Lo que puede salir por la API. La clave no sale nunca, ni para mostrarla."""
    return {k: v for k, v in fila.items() if k != "clave"}


def listar(data_dir: Path) -> list[dict]:
    return [_sin_clave(f) for f in _leer(data_dir)]


def _nueva_clave() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def generar(data_dir: Path, nombre: str) -> dict:
    """
    El lado que **recibe**: crea el emparejamiento y devuelve el código a copiar.

    El código se muestra una sola vez y no se puede volver a pedir: está formado
    por la clave, y una clave que se puede releer por la API es una clave que
    sale por la API. Si se pierde, se genera otro y se olvida éste.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise EmparejamientoError("El emparejamiento necesita un nombre para reconocerlo después")

    try:
        clave = _nueva_clave()
    except BaseException:  # noqa: BLE001 — igual que el adapter del núcleo
        raise EmparejamientoError(
            "No se puede cifrar en esta máquina: falta `cryptography` o está rota. "
            "Config → Diagnóstico lo dice con más detalle.") from None

    fila = {
        # Estable y propio, no la URL: son PCs con DHCP, y un emparejamiento
        # identificado por IP apunta en silencio a otra máquina cuando cambia.
        "id": secrets.token_hex(8),
        "nombre": nombre,
        "clave": clave,
        # Del lado que genera no se sabe quién va a escribir: se completa sola
        # la primera vez que llega un sobre de ese emparejamiento.
        "url": "",
        "creado_en": time.time(),
        "ultimo_uso": 0.0,
    }
    with _CANDADO:
        _escribir(data_dir, _leer(data_dir) + [fila])
    return {**_sin_clave(fila), "codigo": f"{fila['id']}.{clave}"}


def importar(data_dir: Path, codigo: str, url: str, nombre: str) -> dict:
    """El lado que **empuja**: guarda el código que le pasaron, con a quién apunta."""
    codigo = (codigo or "").strip()
    url = (url or "").strip().rstrip("/")
    if not url:
        raise EmparejamientoError("Falta la dirección del Bot con el que se empareja")
    if codigo.count(".") != 1:
        raise EmparejamientoError("Ese código no tiene la forma de un código de emparejamiento")

    ident, clave = codigo.split(".")
    if not ident or not clave:
        raise EmparejamientoError("Ese código no tiene la forma de un código de emparejamiento")
    try:
        from cryptography.fernet import Fernet

        Fernet(clave.encode("ascii"))
    except BaseException:  # noqa: BLE001 — clave mal copiada, o cryptography rota
        raise EmparejamientoError(
            "Ese código no es válido. Suele ser que se copió cortado: "
            "va entero, incluido lo que viene después del punto.") from None

    with _CANDADO:
        previas = _leer(data_dir)
        # Pisar uno que ya estaba es legítimo —es cómo se cambia la IP del otro
        # Bot— pero no puede pasar en silencio: un código preparado con el id de
        # un emparejamiento que ya tenés lo reemplazaría sin que nadie se entere,
        # y el que se pierde hay que rehacerlo a mano en las dos máquinas.
        anterior = next((f for f in previas if f["id"] == ident), None)
        fila = {
            "id": ident,
            "nombre": (nombre or "").strip() or url,
            "clave": clave,
            "url": url,
            "creado_en": time.time(),
            "ultimo_uso": 0.0,
        }
        _escribir(data_dir, [f for f in previas if f["id"] != ident] + [fila])

    return {
        **_sin_clave(fila),
        "reemplazo": _sin_clave(anterior) if anterior else None,
    }


def olvidar(data_dir: Path, ident: str) -> None:
    with _CANDADO:
        filas = _leer(data_dir)
        quedan = [f for f in filas if f["id"] != ident]
        if len(quedan) == len(filas):
            raise EmparejamientoError("Ese emparejamiento ya no está")
        _escribir(data_dir, quedan)


def para_url(data_dir: Path, url: str) -> dict | None:
    """El emparejamiento que apunta a esa dirección, si hay."""
    url = (url or "").strip().rstrip("/")
    return next((f for f in _leer(data_dir) if f.get("url", "").rstrip("/") == url), None)


def sellar(fila: dict, contenido: dict) -> dict:
    """El sobre: la versión y el id afuera, todo lo demás adentro."""
    from cryptography.fernet import Fernet

    token = Fernet(fila["clave"].encode("ascii")).encrypt(
        json.dumps(contenido, ensure_ascii=False).encode("utf-8"))
    return {"v": VERSION_SOBRE, "emparejamiento": fila["id"], "sobre": token.decode("ascii")}


def abrir(data_dir: Path, sobre: dict) -> tuple[dict, dict]:
    """
    Abre un sobre recibido: devuelve (emparejamiento, contenido).

    Que no se pueda abrir es la autenticación: quien no tiene la clave no
    produce un sobre válido. El mensaje de error es **el mismo** para un id que
    no existe y para una clave que no corresponde — decir cuál de las dos cosas
    falló le confirmaría a quien prueba si acertó el id.
    """
    from cryptography.fernet import Fernet, InvalidToken

    if not isinstance(sobre, dict) or sobre.get("v") != VERSION_SOBRE:
        raise EmparejamientoError(
            f"Este Bot no entiende esa versión de sobre (entiende la {VERSION_SOBRE}). "
            "Las dos instalaciones tienen que estar en la misma versión de la app.")

    # **Un solo mensaje para los tres casos**: id que no existe, clave que no
    # corresponde y sobre vencido. Lo que protege no es el id —los ids se
    # listan, aunque sólo desde la propia máquina— sino la **clave**: que no se
    # pueda distinguir "esa clave no es" de "ese sobre venció" es lo que impide
    # ir probando claves y saber cuándo se acertó. El dato del vencimiento se
    # dice igual porque un reloj corrido entre las dos máquinas se ve así, y
    # manda a mirar la hora en vez de a rehacer el emparejamiento.
    generico = (
        "No se pudo abrir el sobre: no hay un emparejamiento que lo explique, o llegó "
        f"vencido (vale {TTL_SOBRE}s). Si las dos máquinas tienen la hora distinta, es eso.")

    fila = next((f for f in _leer(data_dir) if f["id"] == sobre.get("emparejamiento")), None)
    # Sin fila igual se descifra, contra una clave descartable. Volver antes
    # haría que el camino "ese id no existe" fuera medible por lo que tarda:
    # unificar el mensaje y después contestar más rápido es dejar el mismo
    # oráculo por otra puerta.
    clave = fila["clave"] if fila is not None else _nueva_clave()
    try:
        crudo = Fernet(clave.encode("ascii")).decrypt(
            str(sobre.get("sobre", "")).encode("ascii"), ttl=TTL_SOBRE)
    except Exception:  # noqa: BLE001 — token inválido, vencido o mal formado
        raise EmparejamientoError(generico) from None
    if fila is None:
        raise EmparejamientoError(generico)

    return fila, json.loads(crudo.decode("utf-8"))


def anotar_uso(data_dir: Path, ident: str, url: str = "") -> None:
    """Deja constancia de cuándo se usó, y de quién resultó ser del otro lado."""
    with _CANDADO:
        filas = _leer(data_dir)
        for fila in filas:
            if fila["id"] == ident:
                fila["ultimo_uso"] = time.time()
                if url and not fila.get("url"):
                    fila["url"] = url.rstrip("/")
                break
        _escribir(data_dir, filas)

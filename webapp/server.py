"""
Servidor web.

Es una capa delgada sobre `core.Instance`: sirve los estáticos y monta la API
del núcleo. Toda la lógica vive en `core/`, que se testea sin levantar nada.

Arranque:
    python -m webapp [--root /ruta/Bot] [--port 8000] [--no-abrir]

O apuntándole uvicorn (raíz y puerto por entorno: BOT_ROOT, BOT_PORT):
    uvicorn webapp.server:app --port 8000
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# La carpeta del programa (el repo, o %LOCALAPPDATA%\Programs\Bot). La de la
# instalación —boot.env, data/, workspace/— puede ser otra: la resuelve
# `routes.core_api` con `webapp/ubicacion.py`, a partir de BOT_ROOT.
ROOT = Path(__file__).parent.parent
WEBAPP_DIR = Path(__file__).parent

load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(WEBAPP_DIR))

# El puerto lo fija quien arranca (`python -m webapp --port`), y la lista de
# orígenes del CORS tiene que decir el mismo: con 8000 fijo, la app servida en
# 8010 se veía pero ninguna llamada a la API pasaba.
PUERTO = int(os.environ.get("BOT_PORT") or 8000)

from routes.core_api import router as core_router  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# Los docs quedan prendidos: es una herramienta local, y /docs es la forma mas
# rapida de que alguien —una persona o un agente— descubra la API sin leer el
# codigo. /openapi.json es el esquema completo, y sale de los mismos modelos que
# validan las requests, asi que no puede desincronizarse.
app = FastAPI(
    title="Bot",
    description=(
        "API del nucleo. La UI, el MCP y un agente consumen estos mismos "
        "endpoints: no hay una segunda implementacion."
    ),
    docs_url="/docs",
    redoc_url=None,
)

# Sólo el propio origen. Estaba en "*" para recibir tokens de una extensión de
# navegador que ya no existe; con la API del núcleo montada acá, un "*" deja que
# cualquier página abierta en el navegador ejecute flujos en esta máquina.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Una sola superficie. /api/fs y /api/workflows eran rutas propias del front
# viejo; su lógica ya vive en plugins/windows y en el WorkflowStore, detrás del
# núcleo, donde la usan igual la UI, el MCP y un agente.
app.include_router(core_router, prefix="/api/core")


@app.middleware("http")
async def sin_cache_en_la_api(request, call_next):
    """
    Ninguna respuesta de la API se cachea.

    Sin `Cache-Control`, una respuesta sin fecha de vencimiento habilita el
    **cacheo heurístico**: el navegador se inventa cuánto vale, y el resultado es
    que una fuente recién creada no aparece en la lista mientras `curl` sí la ve.
    Encontrado así, en vivo, contra `GET /sources`.

    Va como middleware y no endpoint por endpoint a propósito: son más de
    treinta rutas y cualquiera nueva nace con la regla puesta. Es la misma razón
    por la que la regla de los secretos vive en el núcleo y no en cada handler.

    `no-store` y no `no-cache`: acá no hay ETag ni `Last-Modified`, así que
    revalidar sería pedir todo de nuevo igual. Y estas respuestas llevan la
    configuración de la instalación, que no tiene por qué quedar escrita en el
    disco del navegador. Los estáticos son el caso contrario —inmutables entre
    releases— y por eso siguen con `no-cache`, que sí reusa con un 304.
    """
    respuesta = await call_next(request)
    if request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


class RevalidatingStatic(StaticFiles):
    """
    Estáticos que el navegador siempre revalida.

    Los módulos ES se cachean fuerte. Si una release cambia el grafo de imports,
    un navegador con la versión anterior en caché pide un archivo que ya no
    existe: el módulo falla al cargar y la página queda en blanco, sin un error
    visible. Con no-cache el navegador sigue reusando el archivo cuando no
    cambió (304), pero nunca sirve una versión vieja sin preguntar.
    """

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


# El front se escribe de cero. Mientras no exista webapp/static/, el servidor
# levanta igual y sirve sólo la API: se puede desarrollar el backend y probarlo
# con curl sin que falte nada.
STATIC_DIR = WEBAPP_DIR / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", RevalidatingStatic(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    """La app, o las instrucciones para levantarla si todavía no hay front."""
    indice = STATIC_DIR / "index.html"
    if indice.is_file():
        # Igual que los estáticos: este archivo es el que nombra el grafo de
        # módulos, así que servir una versión vieja rompe la app entera.
        return FileResponse(str(indice), headers={"Cache-Control": "no-cache"})
    return {
        "estado": "API levantada, sin front todavía",
        "api": "/api/core",
        "empezar_por": ["/api/core/doctor", "/api/core/tools", "/api/core/source-kinds"],
    }


if __name__ == "__main__":
    # `python webapp/server.py` sigue andando, pero el arranque con opciones
    # (--root, --port) vive en webapp/__main__.py: `python -m webapp`.
    from webapp.__main__ import main

    sys.exit(main())

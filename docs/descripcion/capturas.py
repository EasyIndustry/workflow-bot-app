"""Saca capturas de la app por CDP (Chrome headless).

    python capturas.py <salida> <url-base> <nombre>=<hash>[|<js>] ...

Cada captura navega al hash, espera, corre el JS opcional (clics para abrir un
modal) y guarda <salida>/<nombre>.png. También importa cada vista para atajar
una que no parsee.
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

PUERTO = 9333


async def main(salida: Path, base: str, pedidos: list[str]) -> None:
    perfil = tempfile.mkdtemp()
    chrome = subprocess.Popen(
        ["google-chrome", "--headless=new", f"--remote-debugging-port={PUERTO}",
         f"--user-data-dir={perfil}", "--window-size=1440,900", "--hide-scrollbars",
         "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                pestanas = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/json").read())
                break
            except OSError:
                time.sleep(0.2)
        ws_url = next(p for p in pestanas if p["type"] == "page")["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            n = 0

            async def cdp(metodo, **params):
                nonlocal n
                n += 1
                yo = n
                await ws.send(json.dumps({"id": yo, "method": metodo, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == yo:
                        if "error" in m:
                            raise RuntimeError(f"{metodo}: {m['error']}")
                        return m.get("result", {})

            async def js(codigo):
                r = await cdp("Runtime.evaluate", expression=codigo, awaitPromise=True, returnByValue=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"])
                return r.get("result", {}).get("value")

            await cdp("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            await cdp("Page.navigate", url=base + "/")
            await asyncio.sleep(2)
            vistas = await js("""(async () => { const r = [];
              for (const v of ['agente','config','inicio','log-modal','plugins','sources','workflows',
                               'workflows-cards','workflows-graph','workflows-mermaid','workflows-node-panel',
                               'workflows-programar']) {
                try { await import('/static/js/views/' + v + '.js'); } catch (e) { r.push(v + ': ' + e); } }
              return r; })()""")
            print("vistas que no importan:", vistas or "ninguna")
            for pedido in pedidos:
                nombre, resto = pedido.split("=", 1)
                ruta, _, codigo = resto.partition("|")
                await cdp("Page.navigate", url="about:blank")
                await asyncio.sleep(0.3)
                await cdp("Page.navigate", url=f"{base}/#/{ruta}")
                await asyncio.sleep(2.5)
                await js("""window.clic = (sel, txt, i = 0) => {
                  const b = [...document.querySelectorAll(sel)].filter(e => e.textContent.trim().endsWith(txt))[i];
                  if (!b) throw new Error("no hay " + txt); b.click(); };""")
                if codigo:
                    await js(codigo)
                    await asyncio.sleep(2)
                foto = await cdp("Page.captureScreenshot", format="png")
                (salida / f"{nombre}.png").write_bytes(base64.b64decode(foto["data"]))
                print(" ", nombre)
    finally:
        chrome.terminate()


if __name__ == "__main__":
    destino = Path(sys.argv[1])
    destino.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(destino, sys.argv[2], sys.argv[3:]))

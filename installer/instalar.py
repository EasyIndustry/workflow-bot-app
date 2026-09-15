#!/usr/bin/env python3
r"""
Instalar Bot.

    python installer/instalar.py      Linux
    py installer\instalar.py          Windows

Abre el wizard en el navegador. Se puede hacer doble clic en el archivo: no
recibe argumentos ni hace falta estar parado en ninguna carpeta en particular.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Doble clic significa que el cwd puede ser cualquiera. La raíz se deduce de
# dónde está este archivo, no de desde dónde se lo arrancó: dos niveles arriba
# —installer/ -> la raíz— es donde viven `installer` y `backend`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    if sys.version_info < (3, 11):
        actual = ".".join(map(str, sys.version_info[:3]))
        print(f"Hace falta Python 3.11 o mayor. Este es {actual}.")
        raise SystemExit(1)

    from installer.source.server import main

    raise SystemExit(main(abrir="--no-abrir" not in sys.argv))

"""
Todo lo del instalador, en un solo lugar.

    source/      el wizard: la lógica, el servidor y el front
    packaging/   cómo se convierte en un .exe de Windows
    build/       lo construido (no se versiona)

`source/` es un huésped del núcleo, como la CLI y el MCP: usa `backend` y no lo
modifica.
"""

from __future__ import annotations

__all__ = ["source"]

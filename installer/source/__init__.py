"""
Instalador: el primer arranque de una instalación, con interfaz.

Es un huésped del núcleo como la CLI y el MCP, no parte de él. Hace lo mismo que
`python -m backend.core init` más crear la base, pero guiado y explicando qué
queda acotado y qué no.

    python -m installer.source

Corre en el navegador con la stdlib. Ver `server.py` para por qué.
"""

from __future__ import annotations

__all__ = ["pasos", "plugins", "server"]

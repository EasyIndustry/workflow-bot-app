"""
Plugin `conocimiento` — propio de esta webapp, como `connections`.

Una sola colección, `notas`: lo que **no se deduce del código ni de la base**
y un agente necesita saber para entender una orden ambigua. "La fuente QA
casos es la bandeja de intranet", "stage=Impresion quiere decir que el caso
está listo para imprimir", "el flujo de facturación lo corre Contaduría los
lunes". Nadie más que la persona que opera —o el agente, cuando lo aprende—
puede escribir eso.

Por qué una colección y no un archivo en `workspace/`:

- viaja con la base y con su backup, y queda fuera de `fs_root`: un flujo con
  el port `fs` no la puede pisar ni leer;
- se edita desde Plug ins → conocimiento sin que ninguna pantalla sepa que
  existe (se dibuja del manifest, como toda colección), y desde el MCP con
  `write_resource_item`;
- `describe_installation` la incluye entera: es la parte del manual que se
  forma con el uso, al lado de la parte que se genera sola.

No expone tools ni declara ports: no es un nodo de ningún flujo. Es dato.
"""

from __future__ import annotations

from backend.core.contract import Field, ParamType, Plugin, PluginManifest, Resource

NOTAS = Resource(
    name="notas",
    label="Notas para el agente",
    item_label="Nota",
    key_field="tema",
    doc=(
        "Lo que un agente tiene que saber de esta instalación y no está en "
        "ningún otro lado: qué significa cada fuente, cada estado, cada flujo; "
        "quién corre qué y cuándo. Se lee entero con describe_installation."
    ),
    fields=(
        Field(
            "tema", ParamType.STR, label="Tema", required=True,
            doc="Corto y buscable: el nombre de una fuente, un flujo, un estado, un proceso.",
        ),
        Field(
            "texto", ParamType.STR, label="Texto", required=True, multiline=True,
            doc="Lo que hay que saber, en castellano llano. Sin secretos: esto se le muestra al agente.",
        ),
        Field(
            "origen", ParamType.ENUM, label="Quién lo escribió", default="persona",
            choices=("persona", "agente"),
            doc="Una nota del agente vale menos que una de quien opera: se marca para poder revisarla.",
        ),
    ),
)

MANIFEST = PluginManifest(
    name="conocimiento",
    label="Conocimiento",
    version="0.1.0",
    doc=(
        "Notas sobre esta instalación para que un agente entienda una orden "
        "ambigua: qué es cada fuente, cada flujo, cada estado. Plugin propio de "
        "esta webapp."
    ),
    resources=(NOTAS,),
)


def build_plugin() -> Plugin:
    return Plugin(manifest=MANIFEST)


PLUGIN = build_plugin()

__all__ = ["MANIFEST", "NOTAS", "PLUGIN", "build_plugin"]

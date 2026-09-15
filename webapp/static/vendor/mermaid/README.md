# mermaid 11.12.2

Build UMD (`dist/mermaid.min.js`) tal cual lo publica npm, sin modificar.
Licencia MIT (ver `LICENSE`).

Va embarcado en el repo porque la app corre en máquinas de producción sin
internet: cargarlo de un CDN dejaría el render "Mermaid" del diagrama roto
justo donde se usa. Se carga a demanda, sólo cuando alguien elige esa vista
(ver `js/views/workflows-mermaid.js`) — el render propio del flujo no lo
necesita.

Para actualizar:

    curl -L https://cdn.jsdelivr.net/npm/mermaid@<v>/dist/mermaid.min.js -o mermaid.min.js
    curl -L https://cdn.jsdelivr.net/npm/mermaid@<v>/LICENSE -o LICENSE

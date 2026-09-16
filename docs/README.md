# Documentación de workflow-bot-app

Índice para personas y agentes. Cada archivo responde una pregunta; si una
sesión arranca de cero, leer en este orden.

| Archivo | Responde |
|---|---|
| [estado-del-proyecto.md](estado-del-proyecto.md) | ¿Qué hay hecho, qué está verificado, qué falta? Registro de avance por fecha |
| [arquitectura.md](arquitectura.md) | ¿Cómo está armado? Piezas, módulos clave, endpoints, dónde vive cada cosa |
| [operacion.md](operacion.md) | ¿Cómo se instala, actualiza, publica un release y opera desde otra PC? |
| [decisiones.md](decisiones.md) | ¿Por qué está hecho así? Las decisiones que no se deducen del código |
| [pendientes.md](pendientes.md) | ¿Qué queda? Lista corta, con el porqué de cada uno |

Reglas de escritura del repo: [`../CLAUDE.md`](../CLAUDE.md). El núcleo
(`backend/`) tiene la suya en `backend/README.md` y `backend/docs/`.

## Repos relacionados

| Repo | Qué es |
|---|---|
| [EasyIndustry/workflow-bot-app](https://github.com/EasyIndustry/workflow-bot-app) | este: la app, el instalador, el núcleo vendorizado (público) |
| [EasyIndustry/workflow-bot-core](https://github.com/EasyIndustry/workflow-bot-core) | el núcleo; se trae por release, no se edita acá |
| [EasyIndustry/workflow-bot-plugins](https://github.com/EasyIndustry/workflow-bot-plugins) | índice público de plugins, la forma que espera *Plugins en línea* |
| OperacionesMejoras/workflow-bot-plugins (privado) | catálogo con código: `archivos`, `procesos`, `toothform`, `bots` |
| OperacionesMejoras/workflow-bot-design (privado) | los canvases de diseño de la UI |
| OperacionesMejoras/Bot-Produccion (privado, en desuso) | de donde salió este repo; flujos legacy y el QA de la primera implantación |

## Cómo mantener esto

Cada cambio que altere qué existe o cómo se opera toca el archivo que
corresponde y agrega una línea fechada en `estado-del-proyecto.md`. Sin
fechas relativas ("ayer"): siempre la fecha.

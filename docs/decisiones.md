# Decisiones

Lo que no se deduce leyendo el código: qué se vio roto y qué se eligió.
Cada entrada: contexto → decisión → consecuencia.

## El núcleo no se edita acá
`backend/` es un release de workflow-bot-core, verificado por el hook de
pre-commit. Un cambio del núcleo es un issue allá (core#15 `on_step`,
core#16 root/plugins por defecto en el MCP). Consecuencia: la webapp
envuelve lo que le falta al núcleo (`mcp_servidor.py`, `runs_en_vuelo.py`)
en vez de parcharlo.

## Los plugins no viven en el repo de la app
El `.exe` instala sin plugins; se traen de un catálogo en GitHub con la
forma del índice público más `path` (el código en el repo). Motivo: separar
lo genérico y público de lo de cada cliente, y poder instalar "pelado" en
otra PC. Los plugins son genéricos, con nombre de herramienta, nunca de un
cliente ni de un sistema externo; una llamada HTTP guardada es una Action
de `connections`.

## Lo que carga código corre en otro proceso
Instalar un plugin o un núcleo nuevo se valida con `python -m backend.core
… --json` en un subproceso contra una raíz temporal. Un plugin que se cuelga
al importarse se lleva un proceso descartable, no el servidor. La web app
nueva se **compila** pero no se arranca: arrancarla es abrir la base real.

## Repos de actualización editables, no fijos
El default vive en el código; el valor, en la base por instalación
(`resource webapp/actualizaciones`), como el repo del catálogo. Motivo:
cambiar de repo (privado → público) sin release.

## Correr sin esperar devuelve un ticket, no un run_id
El `run_id` del núcleo existe al final; el ticket, antes de pasar el gate.
`RunsEnVuelo` recuerda los últimos 500 resultados. Consecuencia: otro Bot o
un agente remoto disparan y preguntan, sin conexiones largas.

## Bots que se hablan directo, sin intermediario
Cada Bot ya es una API; el plugin `bots` la usa desde un flujo. Lo que sí
necesita un intermediario es el **reclamo atómico** de un caso entre Bots
que miran la misma lista: eso es un campo en la fuente de datos, no un
canal.

## Sondeo, no websocket
La grilla y la lista de flujos sondean (1.5/5 s). Dos requests livianos
cada pocos segundos resolvieron "no veo lo que disparó otro" sin sumar un
canal de eventos que habría que mantener también en el MCP y en los Bots.

## Agentes: winget, y nunca `irm | iex` desde la app
Defender marcó `powershell -ExecutionPolicy Bypass -Command "irm … | iex"`
lanzado por `pythonw` como `Trojan:Win32/Commando.A!ml` (heurística sobre
el patrón; admin no ayuda, lo empeora). winget es el camino común
(`--source winget`, porque la tienda puede fallar por certificado). Sin
winget: Claude Code se baja y verifica desde Python (SHA256 del manifest +
Authenticode de Anthropic), los otros con el script del vendor. Node no
hace falta para ninguno.

## Los binarios recién instalados se buscan también en el PATH del registro
Un instalador toca el PATH del usuario; el servidor ya corre con el PATH
viejo. `agent_providers.ruta_del_binario` mira `which`, el PATH del
registro y las carpetas conocidas.

## La receta MCP lleva `cwd` y `env`
Claude Code ignora `cwd` en `.mcp.json`; `PYTHONPATH` y `BOT_ROOT` en `env`
lo entienden todos. `python.exe`, no `pythonw.exe`: el servidor MCP habla
por stdio.

## Reiniciar con guardia
Una vez el servidor quedó en "Shutting down" esperando conexiones y nunca
se relanzó. Ahora: cierre prolijo y, a los 8 s, `force_exit`. No
`force_exit` directo: saltea el lifespan y deja un traceback en el registro
en cada reinicio normal.

## Relanzar con `Popen`, no `execv`
En Windows `execv` pega los argumentos sin comillas y una raíz con espacios
llegaba partida. Encontrado en el primer QA.

## Sin Node, sin UAC, sin PyInstaller
El `.exe` trae un CPython relocalizable y instala en el perfil del usuario:
los plugins se descubren con entry points en un site-packages real, y el
instalador corre igual con o sin administrador.

## La migración entre Bots empuja, no tira
Desde #3 un secreto no sale por la API de nadie, así que el único que puede
leer los de una instalación es la instalación misma. Por eso la migración
corre en el **origen**: lee lo suyo con `resource_store.read` y
`env.resolve()` —write-only es sobre la API, no sobre el núcleo— y lo
escribe en el destino con un PUT. Consecuencias: cada Bot cifra con su
propia llave al recibir, así que no hay que copiar ningún archivo de llave
y un secreto robado en una instalación no vale en la otra; y un campo
secreto **nunca** se puede comparar, porque los dos lados lo tapan — de ahí
el estado `indeterminado` del diff, que no es un caso raro sino la respuesta
permanente. Decir "igual" ahí sería afirmar algo que nadie puede ver.

## El diff lo calcula la app, y el plugin lo consume
`bots.comparar` y la pantalla de migración necesitan la misma respuesta a
"qué está distinto entre estos dos Bots". La dirección contraria —que la
pantalla llame al tool— rompe que ninguna pantalla conozca un plugin por
nombre, y además ataría la app a que el plugin esté instalado. Así que el
cálculo vive en `webapp/migracion.py` detrás de `POST /diff`, con la misma
forma de salida que el tool ya fijó con tests, y el tool reemplaza su
cálculo local por una llamada. Consecuencia: el tool pasa a depender de una
versión de app que tenga el endpoint, y un 404 ahí tiene que leerse como
"actualizá este Bot", no como un error crudo.

## Los secretos viajan en un sobre, con una clave por conexión
Empujar un secreto lo pone en la red, y la API es HTTP sin TLS. TLS acá no
es práctico: la instalación es local, sin internet y sin autoridad que
firme. La decisión es cifrar el **sobre** con una clave **por conexión**,
distinta de la llave local de cada Bot: la local cifra en reposo y no sale
de la máquina nunca, y comprometer un par de Bots no compromete lo guardado
en ninguno. La clave la **genera el destino** —aleatoria, de máquina, nadie
elige una frase— y se copia una vez al origen. Se descartó el modelo de
claves públicas con huella: comparar una huella en dos pantallas es más
fácil de aprobar sin mirar que copiar una cadena una vez. Fernet, que es lo
que el núcleo ya usa; criptografía propia no.

Tres cosas que no son adorno:

- **No se genera sola al conectarse.** Si se intercambiara sola en el primer
  contacto no habría autenticación ninguna: cualquier máquina de la LAN se
  emparejaría sola. El copiado a mano **es** la autenticación, y de paso es
  lo primero autenticado que tiene el sistema.
- **`Fernet.decrypt` necesita `ttl`.** Sin él no mira el timestamp y un sobre
  capturado sirve para siempre; el ataque realista no es que lean el secreto
  sino que reenvíen la migración de ayer y **reviertan** un secreto rotado al
  valor viejo, que es el que el atacante ya tiene. El `ttl` achica la ventana,
  **no cierra el replay**: adentro de esos minutos el sobre sigue valiendo.
  Cerrarlo pide que el receptor recuerde los sobres vistos o dé un nonce de un
  solo uso. Está pendiente, no resuelto.
- **Un destino que no entiende sobres no recibe.** Caer a texto plano con un
  aviso deja que sea el atacante quien elige el camino sin cifrar: se presenta
  como un destino viejo y fuerza el downgrade, y el aviso lo lee alguien que lo
  pasa de largo.

- **Emparejar se hace sentado en la máquina.** Generar, importar, listar y
  olvidar sólo responden desde `127.0.0.1`. En la primera versión estaban
  abiertos como el resto de la API, y con eso cualquiera en la red pedía un
  código y quedaba emparejado: el sobre seguía protegiendo el secreto de quien
  escucha, pero no autenticaba a nadie — que es lo que se suponía que aportaba.
  La contra es real: no se puede emparejar desde otra PC aunque el Bot se opere
  así. Es lo que corresponde hasta que #4 traiga autenticación, y es coherente
  con la idea: emparejar es lo que hace alguien que ve las dos máquinas.
  Recibir un sobre sí queda abierto, porque ahí la credencial es la clave.

El emparejamiento se identifica con un id estable que genera el destino, no
con la URL: son PCs de planta con DHCP, y un mapa por URL apunta en silencio
a otra máquina cuando cambia la IP. La versión del sobre va **afuera** del
texto cifrado, porque si no hay que descifrar para saber cómo parsear.

Lo que esto **no** arregla: la API sigue sin autenticación para escribir y
ejecutar (#4). El sobre protege una migración, no el Bot.

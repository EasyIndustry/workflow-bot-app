# Estado del proyecto

Qué hay hecho y verificado, por fecha. Lo más nuevo arriba. "Verificado"
quiere decir corrido de verdad en una instalación Windows (la QA de
desarrollo o la PC de un cliente), no sólo con tests.

## 2026-09-23

- **Cómo se llama este Bot, para titular la pestaña (`webapp/identidad.py`,
  `GET`/`PUT /identidad`, Config → General).** Con varios Bots abiertos en
  pestañas del mismo navegador —cada uno por su IP— todas decían "Bot" y no
  se distinguían sin mirar la URL. El nombre se guarda por instalación en
  `resource_store("webapp", ...)`, el mismo mecanismo que ya usa
  `webapp/updates.py` para el repo de cada componente: no depende de ningún
  plugin instalado. `/overview` lo trae junto con el resto, y `main.js` lo
  usa como `document.title` en cuanto arranca, sea la pestaña propia o la
  que otra máquina abrió con la IP de ésta — el Bot titula su propia
  pestaña, así que no hace falta que quien la abre sepa el nombre de
  antemano. Queda preparado para que el plugin `bots` del catálogo (conecta
  varios Bots por IP) lo lea con un `GET` simple, sin instalarse nada de
  este lado — pendiente coordinar con ese plugin qué usa exactamente al
  abrir una pestaña nueva. Verificado por CDP: el título cambia al guardar
  el nombre y las tres vistas tocadas (`config`, `plugins`, `inicio`)
  importan sin error; `webapp/tests/test_identidad.py` verde.

- **Núcleo v0.3.1-beta.12 vendorizado: core#33.** `FsPort.walk(max_depth)`
  para listar los hijos directos de una carpeta sin statear ni recursar todo
  el árbol: bajar a una subcarpeta de un share con 50k entradas costaba 80 s.
  Es un cambio del port, lo aprovechan los plugins (`archivos`); la web app no
  llama a `walk` y no cambia nada. `backend/tests/test_adapters.py` verde en
  Windows (73). Sale en v0.5.0-beta.8.

## 2026-09-22

- **La tarjeta de decisión también ofrece las variables.** El campo Variable
  abre la lista al entrar (sin tipear `{`, porque la variable de una decisión
  se escribe pelada: `decision_value` la lee por nombre) con las columnas de la
  fila y las salidas de los nodos anteriores, y un helper "Variables que puede
  comparar" con las mismas fichas. No entran las variables de Config ni
  `{NODO.salida}`, porque el núcleo no las resuelve ahí (`autocompletar` con
  `sinLlaves`, `opcionesDeDecision` en `views/workflows-cards.js`). Verificado
  por CDP: al enfocar aparecen las seis columnas más `response`, `status` y
  `result` "la deja Llamar A"; `sta` filtra a `state` y `status`; Enter deja el
  nombre sin llaves. Y con una corrida real: `N1` (connections.llamar) →
  `D1{Estado § status}` → rama `|200|` tomada, así que una decisión compara
  también contra la salida interna de un nodo anterior, no sólo contra la
  fila. `D1{Estado § N1.status}` falla con "Sin rama para N1.status = None":
  la forma calificada no vale en una decisión, y el helper lo dice.
- **Cambiar de pestaña vuelve a donde se estaba.** La pestaña iba a la raíz de
  la vista (`#/sources`) y la vista elegía la primera fuente: se perdían los
  filtros de la grilla y el flujo que se estaba editando. Ahora el router
  recuerda la última ruta completa de cada vista (sessionStorage, por pestaña
  del navegador) y la barra vuelve por ahí; la grilla ya redibujaba de memoria
  la misma fuente, así que los filtros quedan. El editor de flujos no relee
  del servidor un flujo con cambios sin guardar, y si no los tiene lo relee
  pero conserva cómo se lo miraba (Nodos/Texto, nodo elegido, dry run
  desplegado). Verificado por CDP: filtro "sin" de la columna Estado y nombre
  visible editado sobreviven a Sources → Workflows → Sources.
- **Núcleo v0.3.1-beta.11 vendorizado: core#31 y core#32, y la app los usa.**
  - *Un flujo declara su fuente* (`%% source:`, `Workflow.source`, columna
    nueva en `workflows`). En la app: selector "Fuente" en Propiedades y en
    Nuevo flujo, chip `fuente: X` en la cabecera (ámbar si esa fuente no existe
    en la instalación: el flujo corre igual, pero sin columnas que ofrecer), y
    el `PUT /workflows/{name}` lleva `source`. Las columnas de la fila salen
    de la fuente declarada y, si no hay, de la última corrida como antes. En la
    grilla de una fuente, el desplegable de flujo agrupa primero los pensados
    para ella y, si es uno solo y la fuente no tiene flujo por defecto, lo
    propone. Verificado en el server de desarrollo: helper "Columnas de
    flujos-propios, la fuente declarada en Propiedades" con las seis columnas,
    grilla con "Para esta fuente: prueba-columnas" preseleccionado.
  - *Opciones del núcleo y dependientes* (`options_from="core:plugins"`,
    `"core:resources:{plugin}"`). `api.opcionesDeParam` resuelve las dos
    contra el catálogo de `GET /tools` (sin los `builtin`), `campo.js` expone
    `recargarOpciones` y `crearFormulario` recarga la lista del campo que
    declara `depende_de` cuando el otro cambia; la tarjeta del flujo hace lo
    mismo escuchando la tarjeta entera. Un namespace que el núcleo no valida
    (`core:pluggins` pasa el chequeo de carga) se ve en el placeholder del
    campo en vez de como un buscador mudo. Verificado con el componente real:
    `plugin=connections` → `sources, actions`; `conocimiento` → `notas`.
  - El helper de salidas repetidas ahora dice `{N3.log_file} (Verificar log)`:
    el id es lo que resuelve el núcleo y casi nunca coincide con el nombre visible.
  - Suite de la webapp: 412 verdes, con `test_workflow_source.py` nuevo.

- **El autocompletado ofrece las columnas de la fila, con un valor de ejemplo.**
  Un flujo no declara su fuente (core#31, abierto hoy), así que la app la
  infiere de la última corrida: `Run.source` dice contra qué fuente corrió y una
  página de esa fuente —la misma vista previa de Connections que usa la grilla—
  da las columnas. Aparecen primero en la lista al tipear `{` ("columna de la
  fila · flujos-propios · ej. PRUEBAS") y como fichas en el helper, con el
  nombre de la fuente; un flujo que nunca corrió se queda con la ficha genérica
  y lo dice. Se guarda un minuto por flujo. Cuando el núcleo traiga `%% source`,
  la declaración manda sobre la inferencia y "Correr" la propone por defecto.
  Verificado por CDP con una fuente apuntada a la propia API del Bot.
- **La página se abre aunque el navegador tenga guardado el Bot viejo.** En la
  PC de producción, Chrome y Edge mostraban `127.0.0.1:8000` en blanco: el
  servidor entregaba la página nueva (`GET / 200`) y el navegador ejecutaba la
  del Bot viejo que tenía guardada para esa dirección, pidiendo `state.js`,
  `bots-red.js` y `/api/ks/...`, que ya no existen. En modo invitado entraba.
  La página sale ahora con `Clear-Site-Data: "cache", "storage"` la primera vez
  que un navegador la pide (cookie de marca `bot_limpio`), que borra la caché
  y los service workers de ese origen; una sola vez porque también borra el
  localStorage propio. Los navegadores la respetan en `127.0.0.1` y
  `localhost`, que es donde pasa. Con tests del criterio; el efecto real se ve
  en esa PC al recargar.
- **Núcleo v0.3.1-beta.10 vendorizado: core#30, #29 y #19.** `{NODO.salida}`
  elige entre dos nodos que dejan la misma salida (`merge_outputs` agrupa
  además bajo el id del nodo; la plana sigue igual y gana si colisiona con un
  id), `check_flow` valida que el nodo exista y corra antes, `Param.placeholder`
  llega en el catálogo, y un port `geometry` con adapter nulo cuando no hay
  numpy. La app hace lo que había quedado esperando: el autocompletado ofrece
  `{LLAMAR_A.response}` y `{LLAMAR_B.response}` además de `{response}` cuando
  la salida la dejan dos nodos ("la response de Llamar A"), el helper dice cómo
  elegir en vez de que no se puede, y la marca en dos tonos pasa de ámbar a
  azul (`NODO_CALIFICADO_SOPORTADO`). Verificado contra el repo: `check_flow`
  acepta `{LLAMAR_A.response}` y rechaza `{AVISAR.response}` con "referencia a
  AVISAR, que no corre antes en el flujo"; la lista muestra las diez opciones.
  Los tests del núcleo que fallan en Windows (`test_boot`, uno de `doctor`,
  uno de `instance`) ya fallaban con beta.9 en `backend.anterior/`.
  Producción (192.168.3.26) ya corre beta.10 actualizado desde la pantalla.
- **Las `{variables}` se ven marcadas dentro del campo mientras se escribe.**
  Un espejo detrás del input (`components/resaltar-variables.js`): el input
  queda arriba con el texto transparente y el cursor visible, y debajo una caja
  con las mismas clases dibuja el mismo texto con cada `{ruta}` marcada. Así
  `C:\salida\{carpeta}\{env.CLIENTE}.pdf` se lee de un vistazo y lo guardado
  sigue siendo texto plano con sus llaves. No es negrita de verdad: la negrita
  ensancha la letra y el espejo dejaría de coincidir con el input; el peso se
  hace con `text-shadow`. Una variable calificada por nodo, `{LLAMAR_A.response}`,
  muestra la relación entera —nodo en azul oscuro, salida en negro— cuando el
  primer tramo es un nodo del flujo; como el núcleo todavía no resuelve esa
  forma (core#30), va en ámbar con el aviso, y pasa a azul cambiando
  `NODO_CALIFICADO_SOPORTADO` en `views/workflows-cards.js` cuando llegue.
  Sólo en los campos de una línea; el JSON del payload queda para después.
  Verificado por CDP: espejo e input miden lo mismo, misma fuente y padding,
  y escribir una variable nueva la marca al instante.
- **Un param con `placeholder` en el manifest se dibuja con su ejemplo adentro
  del campo** (core#29, todavía sin implementar en el núcleo: el vendorizado
  v0.3.1-beta.9 no lo tiene). La app lo lee de la entrada del catálogo en
  `components/campo.js` y en la tarjeta del nodo; si no viene, el campo queda
  como hoy. Los dos placeholders fijos que ya existían —el buscador de una
  colección y el secreto configurado— siguen mandando sobre él.
- **Las variables de una tarjeta se eligen de una lista al tipear `{`.** Había
  que acordarse de memoria el nombre exacto de cada salida: el helper las
  listaba, pero abajo de todo y sin decir cuál vale cuando dos nodos anteriores
  dejan la misma. Ahora cualquier campo de parámetro (los declarados, los
  descubiertos de una conexión, los no declarados, el JSON de un payload) abre
  al tipear `{` un desplegable con las salidas de los nodos de arriba y los
  nombres de Config, y cada opción dice de dónde sale: "la deja Mover PDF", o
  "la dejan Llamar B y Llamar A · vale la del último que corra". Flechas, Enter
  o Tab para insertar `{nombre}` entero, Esc para cerrar; se filtra mientras se
  escribe. Es un componente propio (`components/autocompletar.js`), no un
  `<datalist>`, porque ése completa el valor entero del campo y acá hay que
  completar en el medio de `C:\salida\{intentos}.pdf`. Lo guardado sigue
  siendo texto plano con sus llaves. El helper marca en ámbar las salidas
  repetidas. Lo que no se puede todavía es elegir de qué nodo (`{NODO.ruta}`):
  el núcleo mezcla las salidas por nombre y la del último que corre gana; es
  core#30, y la lista ya está preparada para ofrecerlo cuando llegue. Tampoco
  se ofrecen las columnas de la fila: un flujo corre contra cualquier fuente.
  Verificado por CDP con un flujo de dos `connections.llamar` seguidos.
- **El formulario de Acciones ofrece el buscador que el param declara.** Un
  `Param` con `options_from` nombra una colección del mismo plugin cuyos items
  son sus valores típicos, y el editor de flujos ya lo dibujaba como texto con
  buscador desde core#27 — pero en Plug ins no, así que la misma Action que en
  un nodo ofrecía la lista, disparada a mano, era un texto pelado y había que
  acordarse del nombre exacto. `campo.js` ya sabía hacerlo; lo que faltaba era
  que quien arma el formulario le dijera cómo traer los valores, igual que en
  `workflows-cards.js`. Sigue siendo texto y no un `<select>`: el valor puede
  ser una `{variable}` que recién se resuelve al correr, y por eso el núcleo lo
  declara informativo. Sólo `Param` lo tiene —ni `Setting` ni `Field`—, así que
  los formularios de settings y de un item no cambian: la pantalla no promete
  lo que el contrato no da. Verificado por CDP contra una instalación con un
  plugin de prueba que lo declara: el campo queda input + datalist con las
  claves de la colección, el param sin `options_from` sigue pelado, y una
  `{variable}` se puede escribir igual. Pedido por la sesión del plugin `bots`:
  es lo que le va a dar el desplegable de direcciones a `bots.migrar`, cuyo
  param `destino` ya declara `options_from`.
- **Emparejar dos Bots se puede hacer desde la app.** Los cuatro endpoints
  estaban desde el 20/09 y ningún JS los llamaba: la única forma de emparejar
  era un `Invoke-RestMethod` a mano en las dos máquinas, y quien intentaba
  migrar chocaba con "No hay emparejamiento con…" sin nada a mano para
  resolverlo. Config → Emparejamientos lista con quién habla este Bot, genera
  el código (el lado que recibe), pega uno (el que empuja) y olvida. El código
  se muestra una sola vez, con el aviso de que va entero: cortarlo en el punto
  es el error más común y del otro lado se lee como "ese código no es válido".
  Pegar avisa que la dirección se compara **tal cual** contra el destino que
  pida la migración, que es lo que hace fallar casi todos los intentos; y si el
  código pisa un emparejamiento que ya estaba, la pantalla lo dice en ámbar y
  nombra al que se perdió, porque rehacerlo cuesta dos máquinas. Los cuatro
  pedidos son loopback-only, así que operando el Bot desde otra PC la pantalla
  explica el 403 en vez de mostrarlo — incluido el caso que más desconcierta:
  abrirlo por la IP de su propia máquina tampoco alcanza. Verificado por CDP
  contra la app: el recorrido entero, el código cortado, el reemplazo, y el 403
  real entrando por `192.168.9.78`. Pedido por la sesión del plugin `bots`.
  De paso, el error de `POST /migrar` ahora **nombra la pantalla**: decía qué
  hacer pero no dónde, porque cuando se escribió no existía dónde. Quien lo lee
  está en la pantalla de un plugin y el arreglo vive en otra pestaña, bajo un
  nombre que no dice "migrar"; y ese texto es además el único camino por el que
  el plugin puede nombrar una pantalla de la app sin conocerla.
- **El puerto del que empuja viaja adentro del sobre.** Al recibir una
  migración, el destino anotaba al otro Bot como `http://<su ip>:8000`, con el
  puerto escrito a mano: si ese Bot escuchaba en otro, quedaba anotada una
  dirección que no existe, y recién se veía cuando la migración iba al revés
  —`para_url` no encontraba nada y el error decía "no hay emparejamiento", que
  manda a rehacer el emparejamiento en vez de a mirar el puerto—. Ahora la IP
  sale de la conexión y el puerto del sobre (`origen_puerto`), así que llega
  autenticado por la clave; si del otro lado hay una app vieja que no lo manda,
  la dirección queda vacía en vez de inventada, porque vacía se ve. Con tests.
  Encontrado por la sesión del plugin `bots`. Y el puerto se **valida** antes de
  armar la dirección: que el sobre abra dice que del otro lado hay alguien con
  la clave, no que lo de adentro sea sano —lo escribió otra máquina, con su
  versión de la app—, así que un string o un número absurdo se interpolaba tal
  cual y quedaba guardado como la dirección de un par, que es lo que después se
  muestra y se compara. De paso, un IPv6 va entre corchetes: `::1` suelto arma
  `http://::1:8010`, que no es una URL y termina igual que el puerto adivinado.
  Encontrado en revisión, en paralelo, por esta sesión y por la del release.
- **La bandeja encuentra la dirección de red en una PC sin internet, y dice si
  copió.** `direccion_red` preguntaba a la tabla de rutas por dónde saldría un
  paquete hacia `10.x`; en una red `192.168.x` sin puerta de enlace no hay por
  dónde, y el menú decía "Sin red" en una máquina que estaba en la red: la
  única dirección a la vista quedaba el `127.0.0.1` de "Abrir Bot", y era la
  que se copiaba. Ahora prueba un destino por rango privado y, si ninguno
  tiene ruta, cae a las IPs de los adaptadores prefiriendo las de oficina.
  Copiar va por la API de Windows (sin la ventana negra de `clip.exe` ni
  depender del PATH; `clip` queda de rescate con las salidas redirigidas) y
  siempre avisa con un globo qué copió, o que no pudo y cuál es la dirección:
  antes un fallo era silencioso y el portapapeles quedaba con lo anterior.
  Reportado desde una PC nueva con Windows 11 al copiar para otras máquinas.
- **`core_api.py` ya no imprime un `SyntaxWarning` al arrancar.** Un `\s` en
  un docstring (`\server-nuevo`) que Python 3.12 marca en cada inicio; era
  la primera línea del registro y parecía un error.
- **Con el 8000 ocupado, Bot arranca en el siguiente puerto libre.** Antes,
  otro programa en el 8000 daba un cartel pidiendo cerrarlo o elegir puerto a
  mano; y **otro Bot** ahí —otra instalación de la misma PC, el repo de
  desarrollo— abría la pantalla de ese otro como si fuera el propio, con sus
  datos, y después no se sabía cuál cerrar. Ahora el lanzador compara la raíz
  del que contesta con la propia: sólo el Bot de esta misma carpeta cuenta
  como "ya abierto"; otro Bot es otro programa y se busca puerto (hasta 50
  arriba, `_decidir_puerto` en `webapp/__main__.py`). Con `--port` explícito
  se respeta y ocupado sigue siendo error: el wizard ya eligió uno libre y el
  reinicio tiene que volver adonde está el navegador. Verificado en esta
  máquina con la QA en el 8000: el Bot del repo avisó "ocupado por otro Bot
  (D:\User\Bot)" y levantó en el 8001 con su propia raíz. Una revisión
  adversarial antes del release encontró dos cosas y se corrigieron: lo que
  ocupa el puerto y no dice quién es (HTTP que tarda o contesta 5xx, que puede
  ser este mismo Bot levantando) ya no se toma por "otro programa" —se insiste
  ocho segundos y, si sigue así, se avisa y no se arranca un segundo Bot sobre
  el mismo `data/`—; y la espera de ocho segundos a que el puerto se libere
  quedó sólo con `--port`, que es el reinicio: el doble clic decide al instante.
- **La botonera de una colección ya no sale recortada.** En Plug ins → Bots
  conocidos, "Probar", "Comparar contenido", "Editar" y el tacho no entraban
  en la columna de acciones, que tenía 210px fijos y ocultaba el resto. Cuántos
  botones hay y qué dicen lo decide el plugin con sus Actions sobre la
  colección, así que ningún número fijo sirve: la tabla (`components/tabla.js`)
  acepta `ancho: "contenido"` y la columna mide lo que dibuja; la cabecera
  lleva adentro, sin alto y sin verse, una copia de la primera fila para medir
  igual y que las columnas de al lado alineen. De paso, la clave de la
  colección salía dos veces ("Nombre | Nombre") porque también está entre los
  campos; se la saca de los tres que se muestran. Verificado por CDP contra una
  copia de los datos de la QA: cabecera y filas miden lo mismo y ningún botón
  queda afuera de su celda. El tope de 900px de `.columna` sigue: no era la
  causa.

## 2026-09-21

- **Núcleo v0.3.1-beta.9** (core#28): el catálogo declara `flow.ejecutar` y
  `flow.retry_gate`. Los resuelve el executor y no son tools invocables —eso no
  cambió—, pero ahora tienen manifest y salen por `registry.catalog()` marcados
  `native`. La app no cambió una línea: el selector del editor nunca filtró,
  armaba la lista con lo que viniera en `GET /tools`, así que aparecen solos con
  su categoría y sus params. Lo que además arregla, y no estaba en el pedido: un
  flujo que ya usaba `flow.retry_gate` se dibujaba con el cartel rojo de "no
  instalado" —la tarjeta marca así a un nodo cuyo `fn` no está en el catálogo—,
  y era falso. Verificado contra una instalación: los dos en el picker, la
  tarjeta limpia y el flujo "sin problemas".
- **Una Action declarada sobre una colección ahora tiene su botón en la fila.**
  El contrato del núcleo dice desde siempre que el botón de una `Action` con
  `resource` va en la fila del ABM, y la fila sólo tenía Editar y Eliminar: una
  Action así existía en el manifest y no se podía disparar desde ningún lado.
  Corre sobre el item **guardado** —el núcleo lo recibe por su clave—, que es
  lo que la distingue del "Probar" del formulario, y su resultado abre un modal
  que dibuja la vista declarada. Si esa vista ofrece una acción de seguimiento,
  reemplaza el contenido del mismo modal en vez de abrir otro encima.
  Encontrado probando el conjunto contra el plugin `bots` real en dos Bots: su
  `comparar` cuelga de la colección y no tenía botón en ninguna parte.
- **Una Action de plugin puede traer su propia pantalla de resultado**
  (`outputs.vista`). Hasta acá un plugin podía declarar settings y colecciones y
  la pantalla se dibujaba sola, pero cuando hacía falta algo más —comparar
  contra otro Bot y elegir qué mandar— sólo quedaba escribirle una pantalla a
  medida en la app. Ahora el resultado de una Action puede declarar una tabla
  con columnas, filas, casillas de selección y una acción de seguimiento que
  recibe lo tildado más el contexto que haga falta fijar (`seleccion.params`).
  Va en el **resultado** y no en el manifest porque las columnas de una
  comparación dependen de lo que se comparó: no se pueden declarar antes de
  correrla. No hizo falta tocar el núcleo — `ToolResult.outputs` ya es libre—,
  así que cualquier plugin lo usa sin esperar un release del núcleo. Ninguna
  pantalla conoce un plugin por nombre: el plugin declara y la app dibuja, y
  todo sale como texto porque `h()` no usa `innerHTML`.
  De paso, **una Action suelta ahora tiene dónde vivir**: hasta ahora sólo
  aparecía como el botón "Probar" adentro del formulario de una colección, así
  que una que no fuera "probar esto antes de guardar" existía en el manifest y
  en ninguna pantalla. Y `dangerous`, que estaba declarado y no hacía nada,
  ahora pide confirmación — por los dos caminos, el botón propio y el de una
  selección.
- **Emparejar sólo se puede desde la propia máquina.** Los endpoints de
  emparejamiento salieron abiertos como el resto de la API, y devolvían el
  código en la respuesta: cualquiera en la red pedía uno y quedaba emparejado.
  El sobre seguía cifrando, pero no autenticaba a nadie — que era justamente lo
  que aportaba, y lo que su propio docstring afirmaba. Ahora generar, importar,
  listar y olvidar sólo contestan a `127.0.0.1`; recibir un sobre queda abierto,
  porque ahí la credencial es la clave. Listar también es local: publicaba los
  ids y la topología de la flota. Encontrado en revisión, verificado contra un
  Bot con `--red` pidiéndole por su IP de LAN. De paso: `importar` avisa cuando
  pisa un emparejamiento que ya estaba, las escrituras del archivo van bajo
  candado —`anotar_uso` corre en cada sobre y dos migraciones a la vez perdían
  una fila— y abrir un sobre hace el mismo trabajo exista o no el id, para no
  dejar por tiempo el oráculo que se había cerrado por mensaje.
- **Migrar contenido a otro Bot, en un sobre cifrado.** `POST /diff` dice qué
  difiere contra otro Bot —flujos, items de una colección, o `env`— y
  `POST /migrar` le empuja lo elegido. Empuja y no tira porque desde #3 un
  secreto no sale por la API de nadie: el único que puede leer los de una
  instalación es la instalación misma. Un campo secreto por eso **nunca** puede
  dar "igual" en el diff: da `indeterminado`, que no es un caso raro sino la
  respuesta permanente. Lo que viaja va adentro de un sobre cifrado con una
  clave **por conexión**, distinta de la llave local de cada Bot —que cifra en
  reposo y no sale de la máquina—; la genera el destino y se copia una vez al
  origen. **Sin emparejamiento no se migra**, y no hay caída a texto plano: un
  fallback con aviso dejaría que sea quien ataca el que elige el camino sin
  cifrar, presentándose como un destino viejo. Que el sobre abra es la
  autenticación del endpoint que recibe, y es lo único autenticado de esta API
  (ver #4 para lo que no lo está). El `ttl` de Fernet acota el replay pero **no
  lo cierra**: está anotado como pendiente en `docs/decisiones.md`, no como
  resuelto. Si al destino le falta el plugin de una colección, el diff lo dice
  (`destino_sin_coleccion`) en vez de romperse — es el Bot nuevo de la flota, al
  que justamente se le va a copiar todo. Verificado entre dos instalaciones
  levantadas de verdad: migrar sin emparejar se niega, el secreto no aparece en
  el sobre ni en la respuesta ni en el `GET /env` del destino, y el 403 del
  sobre que no abre dice **lo mismo** para una clave equivocada que para un id
  inexistente — salió distinto en la primera versión y se vio recién ahí.
- **Los campos `secret` de una colección ya no salen por la API** (#3).
  `GET /resources/{plugin}/{resource}` y `.../{key}` los devolvían descifrados:
  eran el único de los cuatro caminos de lectura que no los tapaba, contra lo
  que dicen el docstring de `resource_items_masked` ("lo que puede salir por el
  servidor MCP o cualquier otra API") y la regla del repo. La asimetría más
  fuerte era contra `db_view.py`, que tapa las filas de `plugin_items` — la
  misma tabla que esta ruta servía en claro. Sin autenticación y con el acceso
  directo arrancando en `--red`, era legible desde cualquier máquina de la LAN.
  Estaba **latente**: ningún plugin declara un campo `secret` todavía, ni los
  del catálogo ni el `connections` de la app, así que no se filtró nada; lo
  abría el primero que guardara un token en una colección en vez de en `env`.
  Listar usa ahora `resource_items_masked` del núcleo y leer uno tapa con el
  mismo criterio. El PUT conserva un secreto que llega en `None` —si no, la
  pantalla, que ahora lee `None`, lo borraría al guardar— y `""` sigue
  vaciándolo a propósito; su respuesta también va tapada, porque puede traer
  uno que quien llamó no mandó. Los tests fallan contra el código anterior, que
  es lo que los hace valer. Encontrado desde el repo de plugins evaluando una
  migración entre Bots.

## 2026-09-20

- **Config: dos o tres vistas adentro de cada panel** (`components/subvistas.js`).
  Varias secciones eran dos pantallas apiladas y había que barrer con el scroll
  para llegar a la mitad de abajo. La vista elegida va en la URL
  (`#/config/limites/programas`), así un enlace lleva a donde uno quiere y
  recargar no devuelve a la primera. Quedaron: **Alcance** (Archivos |
  Programas), **Configurar entorno** (Secretos | Variables de entorno) y
  **Actualizaciones** (Repos | Núcleo | Web app).
- **Los programas que un flujo puede correr se configuran desde la pantalla.**
  `process_allowlist` sólo se podía tocar editando `boot.env` en cada máquina,
  y el error que ve quien opera es un `PortError` adentro de un run, que parece
  del flujo. Va con los tres estados explícitos —ningún programa / sólo éstos /
  cualquiera— porque en el archivo los dos primeros se escriben casi igual (la
  clave presente y vacía, o ausente) y significan lo contrario; una instalación
  nace en "ninguno". Inicio → "Hasta dónde llega" suma la fila. Se agregó
  `PUT /limites/programas` y `GET /limites` ahora distingue lo vigente de lo
  escrito: entre guardar y reiniciar son distintos, y sin decirlo la pantalla se
  redibujaba con el valor viejo y guardar parecía no haber hecho nada.
- **Los releases se piden de a cinco, con paginador**, en vez de treinta por
  componente al abrir la pantalla: cada entrada trae sus notas y casi siempre se
  instala la primera (`GET /updates/releases?pagina=&por_pagina=`). Sin total de
  páginas a propósito: GitHub pagina por cantidad de releases y acá se filtran
  borradores y prereleases, así que un total sería inventado.
- **Config → General**: se fue. Estaba dibujada sin backend desde el traspaso.
- **"Volver a chequear" de Diagnóstico redibujaba Alcance**: buscaba la sección
  por índice (`SECCIONES[2]`) y el botón parecía no hacer nada. Ahora por id.
- **Abrir una tarjeta ya no mueve la pila** (#2). El click en la cabecera
  terminaba en `dibujar()`, que rehace la vista entera — y con ella el div que
  scrollea, que nace en el tope. Con la pila scrolleada, abrir una tarjeta de
  abajo la mandaba fuera de la vista: medido en una instalación con un flujo de
  21 nodos, la tarjeta pasaba de estar a 526px a estar a 1158px, 429px por
  debajo del borde del panel. Ahora abrir y cerrar cuelga o saca el cuerpo
  sobre la tarjeta que ya está en pantalla, sin redibujar nada —el mismo camino
  que ya se había elegido para el filtro de la pila—, y `a.abierta` se sigue
  anotando para que un redibujo de verdad la vuelva a abrir. Aparte, el panel
  de tarjetas recuerda su `scrollTop` y lo vuelve a poner después de dibujar,
  que es lo que hacía falta para lo que sí redibuja: elegir un tool, agregar un
  nodo, quitar uno. Verificado en el navegador por CDP: abrir, cerrar, abrir
  otra, cambiar de tool con la pila en el fondo, el filtro, y el panel flotante
  del diagrama con su "Abrir en Tarjetas".
- **Núcleo v0.3.1-beta.8** (core#27): un `Param` puede declarar de qué
  colección salen sus valores (`options_from`) y un tool puede describir sus
  params extra según lo que el nodo ya eligió (`Tool.describe_extra_params`,
  optativo). `options_from` es informativo a propósito: si validara como
  `choices`, `connection={variable}` dejaría de ser un valor válido y se
  rompería interpolar el nombre desde el contexto del run. El lector de items
  que el núcleo le da al describer no ve los campos `secret`.
- **Elegir la conexión de una lista, sin salir del flujo.** El param
  `connection` declara su colección y la tarjeta lo dibuja como texto con
  buscador (`<datalist>`), no como un `<select>`: la lista es una ayuda para
  no acordarse del nombre exacto, y el campo sigue aceptando una `{variable}`.
  Antes había que volver a Plug ins a ver cómo se llamaba la Action.
- **La tarjeta de un nodo ofrece los params extra de lo que tiene elegido.** Un
  tool con `extra_params` dice que acepta más params que los declarados, pero
  no cuáles: los de `connections.llamar` son las `{variables}` que la Action
  elegida tenga en la URL, los headers y el payload. Había que abrir
  Connections, anotar los nombres y escribirlos a mano en el `.mmd`. Ahora la
  tarjeta pregunta `GET /tools/<tool>/params-extra` con lo que el nodo ya
  tiene y los dibuja con el mismo campo que los declarados; un tool que no
  sepa describirlos contesta vacío. La tarjeta sigue sin conocer un tool por
  nombre: quién lee la Action es el plugin (`webapp/connections/plugin.py`),
  y desde el núcleo v0.3.1-beta.8 lo puede hacer cualquier plugin
  instalado, no sólo el de la app.
  Un campo con un literal —`"texto": ""`— no aparece, porque un param del nodo
  no lo pisaría: sólo se sustituye lo que tiene `{llaves}`. Verificado en el
  navegador contra una instalación, con la Action y el flujo creados por API.
- **Plugins en línea no listaba nada** (v0.4.2-beta.11): se usaba un elemento
  que nunca se creaba y el error cortaba el dibujo de todas las filas.

## 2026-09-17

- **Núcleo v0.3.1-beta.7** (core#26): el port `fs` niega la carpeta de la
  instalación —`data/`, `plugins/` y `boot.env`— venga de donde venga la raíz,
  y la lista la arma el núcleo solo. Con eso una raíz puede contener la
  instalación sin entregarla, así que la app dejó de rechazarlas: usar una
  unidad entera ya no obliga a enumerar carpeta por carpeta. Inicio muestra
  las negadas junto a las raíces. Verificado contra la instalación real con
  `D:\` como raíz: `D:\Proyectos` y el workspace se alcanzan, y la base, la
  llave, `boot.env` y los plugins dan `PortError`. El solapamiento
  `plugins_dir`/`fs_root` dejó de ser fatal, que era lo que dejaba una
  instalación sin arrancar.
- **La raíz por defecto sale de lo que la instalación tiene configurado**, no
  de la regla `<root>/workspace`: asumirla dejó la pantalla sin poder guardar
  nada en una instalación cuya raíz resolvió a la carpeta del programa — la
  única fila que no se podía editar era también la que impedía guardar. Sin
  ninguna raíz declarada no hay fija, y la primera que se agregue pasa a
  serlo. Aparte, `pasos.instalar(registrar=False)`: crear una instalación de
  prueba ya no pisa cuál abre "Abrir Bot", que fue cómo se llegó a ese estado.
  (Se hizo, se perdió y se rehízo: una actualización aplicada sobre el repo a
  las 20:18 pisó lo que no estaba commiteado, así que la v0.4.2-beta.8 salió
  sin este arreglo pese a anunciarlo en sus notas.)
- **La raíz por defecto no se edita.** La pantalla la muestra fija —de sólo
  lectura, sin tacho— y lo que se agrega va debajo, con su alias. El servidor
  la impone aunque le manden otra cosa. Poder pisarla era la mitad de cómo una
  instalación quedó sin arrancar: es la que resuelve toda ruta relativa de todo
  flujo, así que cambiarla rompe en silencio todo lo escrito hasta ahí.
- **Alcance de archivos: sólo rutas completas.** Una instalación nueva en
  `D:\User\Bot` quedó sin arrancar con `fs_roots=principal=D:,…,C=C:`.
  `D:` sin la barra es "la carpeta actual de esa unidad": pasó la validación
  resolviendo a una carpeta inocua y, al reiniciar desde otro lado, resolvió a
  la raíz de la instalación —con `plugins/` adentro— y el núcleo se negó
  (core#22, como corresponde). La pantalla rechaza ahora cualquier ruta no
  absoluta, cada caso con su motivo: unidad sin barra, relativa, UNC sin
  share. Se restauró el `boot.env` de esa instalación (respaldo
  `boot.env.roto-2026-09-17`).
- **Detener un run desde la grilla, y una fila no corre dos veces.** Se vio a
  distancia: una fila ejecutada desde otra PC se veía arrancar en la original
  y nada impedía volver a ejecutarla. Ahora `POST /run` devuelve 409 si esa
  fila ya está en vuelo —es el servidor el que dice no, porque la grilla de
  la otra PC puede no haber sondeado todavía— y la celda Ejecutar es
  **Detener** mientras corre (`POST /runs/en-vuelo/{ticket}/stop`). Detener
  usa el `is_cancelled` que el núcleo ya tenía: mira la marca antes de cada
  nodo, así que el nodo en curso termina y el siguiente no arranca; lo que se
  escribió, quedó escrito. Ojo: el núcleo deja el run detenido con
  `status: ok` y "Detenido por el usuario" sólo en el registro, así que el
  badge de Estado lo muestra como ok.
- **Núcleo v0.3.1-beta.5** vendorizado: core#24, el dry run ya no rechaza un
  param JSON cuyo valor es todavía un placeholder (`rutas={rutas}` de un nodo
  anterior). Verificado en los dos sentidos: el mismo flujo pasa de `err` a
  `ok` en seco con "variables sin resolver" como aviso, y un literal JSON mal
  escrito sigue muriendo en el dry run.
- **Librerías desde el runtime equivocado, dicho antes.** Plug ins →
  Librerías avisa de entrada cuando no hay `runtime-release.json` (el
  intérprete del repo o un programa anterior): el catálogo cura contra el
  runtime del `.exe`, así que instalar desde ahí falla por versión de Python
  y parecía un plugin roto. El error de pip nombra ahora la versión exacta y
  apunta al programa instalado.
- **Los Bots fantasma.** En la QA aparecieron dos servidores vivos en el mismo
  puerto, de un día para el otro, y el acceso directo dejó de abrir sin decir
  nada (cinco intentos, todos anotados en un `webapp.log` que nadie mira).
  Tres causas, las tres arregladas en `webapp/__main__.py`:
  - `_puerto_libre` preguntaba con un `bind` y `SO_REUSEADDR`, y en Windows
    eso no significa "reusar lo que quedó en TIME_WAIT" sino "quedarse con la
    dirección aunque esté en uso": decía "libre" con un servidor escuchando.
    De ahí salían dos Bots en un puerto. Ahora pregunta con un `connect`, que
    además resuelve el falso positivo que el `SO_REUSEADDR` venía a tapar.
  - Con el puerto ocupado por **otro Bot**, ahora abre la pantalla de ése y
    sale bien: es lo que quería quien hizo doble clic. Si lo ocupa otro
    programa, lo dice con un cartel del sistema, porque sin consola el mensaje
    no llegaba a ningún lado.
  - El hilo del ícono de la bandeja (`pystray.run_detached`) **no es daemon**,
    y el `stop()` estaba envuelto en un `except` que se tragaba cualquier
    error: si fallaba, quedaba un proceso sin servidor, imposible de cerrar
    desde la bandeja —el menú que lo cerraría es el de ese mismo ícono— y que
    sólo se iba con el administrador de tareas. Un guardia daemon baja el
    proceso si a los 6 s sigue vivo.
- **Bot figura como Bot en el administrador de tareas.** Corría con el
  intérprete del runtime, así que aparecía como un `python.exe` más entre
  todos los de la máquina: justo cuando hay que cerrar uno a mano no había con
  qué encontrarlo. El build deja `Bot.exe` y `BotConsola.exe` (copias de
  `pythonw.exe` y `python.exe`), los accesos directos lanzan el primero, y la
  app las crea al vuelo si faltan —una instalación que ya existe actualiza
  `webapp/` y no el runtime, así que si dependiera del instalador las máquinas
  de hoy no lo tendrían nunca—. El ícono propio necesita editar los recursos
  del `.exe`; queda pendiente.
- `python -m webapp --help` moría con `UnicodeEncodeError` en una consola de
  Windows por un `↔` en el texto de ayuda — justo el comando que alguien corre
  cuando la app no abre.
- **Config → Alcance de archivos**: las carpetas que un flujo puede tocar se
  editan desde la app, con alias, sin abrir `boot.env` a mano
  (`webapp/limites.py`, `GET /limites`, `PUT /limites/raices`). Hacía falta
  porque el único camino era editar el archivo en la máquina —fuera del
  alcance de quien opera el Bot, que es el que sabe dónde están los archivos
  de hoy— y porque desde core#22 una raíz que no existe **impide arrancar**,
  así que editarlo a mano pasó a poder dejar la instalación sin levantar. El
  backend valida contra el disco antes de escribir y rechaza lo que no
  arrancaría: una carpeta inexistente, un UNC sin el nombre del recurso
  compartido y un alias repetido. (El rechazo de una raíz que contuviera
  `data/` o `plugins/` salió con core#26: eso lo niega el núcleo.) Deja `boot.env.anterior`
  al lado y ofrece reiniciar. Con varias raíces, la primera se guarda con
  nombre aunque no se lo hayan puesto: el alias vacío se escribe
  `fs_roots==ruta` y un núcleo anterior a v0.3.1-beta.4 descarta ese par al
  releer, y app y núcleo se actualizan por separado.
- **Los límites de la instalación se ven en Inicio.** `fs_root` era el único
  límite que decidía si un flujo llega a un archivo y el único que no se
  mostraba en ninguna pantalla: en producción se descubrió con un run
  fallando por "ruta fuera del árbol permitido" contra un `fs_root` mal
  escrito. `GET /overview` lo publica e Inicio lo muestra junto a la raíz y a
  `plugins_dir` ("Hasta dónde llega"), con "todo el disco" cuando no está
  declarado.
- **El diagnóstico de la web corría a medias.** `GET /doctor` llamaba a
  `run_checks` sin `boot`, sin `workflows` y sin `crypto`, así que salteaba
  los chequeos que dependen de cada uno: "Flujos" avisaba "no hay ninguno
  guardado" en una instalación con once (falso positivo), y `check_boot`
  —el que dice `fs_root: X no existe`— no corría nunca desde la app (falso
  negativo). Ahora corre completo, e Inicio levanta un aviso con los
  chequeos que no están en ok, con link al detalle.
- **Núcleo v0.3.1-beta.3** vendorizado, con core#22 y core#23, los dos
  abiertos hoy a partir de una instalación de producción cuyo `fs_root`
  apuntaba a un share de red. Verificado acá: una instalación con
  `fs_root=\server-nuevo` ya **no construye la `Instance`** —levanta
  `BootError` diciendo que un UNC necesita el share y no sólo el host— y
  `fs_roots=casa=…, origen=…` en `boot.env` llega hasta el port `fs` con las
  dos raíces: una ruta relativa resuelve contra la primera, `origen:pieza.stl`
  alcanza el share, y lo que cae fuera de las dos sigue dando `PortError`,
  ahora listando las raíces permitidas. Inicio muestra una fila por raíz con
  su alias. Quedan dos cosas menores comentadas en core#23: `render()` escribe
  la raíz sin alias como `fs_roots==ruta` y `load()` la descarta —el viaje de
  ida y vuelta pierde una raíz sin que `validar()` lo note—, y un alias con un
  typo se lee como ruta relativa de la raíz por defecto en vez de fallar.
- **Núcleo v0.3.1-beta.4**: los dos pendientes del punto anterior, arreglados.
  El `boot.env` con `fs_roots` sobrevive al viaje de ida y vuelta sin perder
  la raíz por defecto, y un alias con typo es `PortError` listando los alias
  declarados — con una letra de unidad (`C:\…`) siguiendo tratada como ruta
  y no como alias, que era lo que ese arreglo podía romper.
- **Los avisos de Sources dejaron de empujar la tabla.** Un run que fallaba
  metía un banner entre la cabecera y la grilla: la tabla bajaba sola justo
  cuando estabas por clickear una fila, y el aviso se borraba en el redibujo
  siguiente. Ahora se acumulan por fuente y se despliegan desde el botón
  "Avisos" de la cabecera, en un panel flotante que no mueve nada (contador
  de no leídos, "Limpiar", cierra al clickear afuera). De paso cada aviso
  lleva su tono: un flujo que falla ya no se anuncia con el tilde verde.
- **Arista con condición editable de verdad.** En el formulario de un nodo
  (modo tarjetas y panel del diagrama), el campo "si" de A dónde sigue
  redibujaba la tarjeta en cada tecla y el input perdía el foco al primer
  caracter. Escribe sin redibujar; el rótulo del diagrama se actualiza al
  salir del campo.
- **Núcleo v0.3.1-beta.2** vendorizado: core#18 (`run_action` por item con
  el campo clave; `describe_installation` con actions), core#20
  (`PluginManifest.requires` visible en el catálogo) y core#21 (un param
  JSON recibe la lista/dict del contexto). Verificado en la QA: el plugin
  `convertidor` del catálogo (`draft`) instaló numpy/scipy/rtree/trimesh en
  el runtime 3.12 desde su `requirements.txt` con hash; renombró 50 STL con
  `reescribir_archivos` alimentado por `archivos.buscar` en un solo run
  (antes de #21 hacía falta un run por archivo); `parsear_pts` e
  `inspeccionar_malla` andan con las librerías reales. Primer plugin con
  dependencias de punta a punta.

## 2026-09-16

- **Librerías Python para plugins** (decidido con core#20 y
  workflow-bot-plugins#1). Un plugin trae `requirements.txt` con versión y
  hash fijos; `plugin_install.instalar()` lo instala con pip en el runtime
  del programa —sólo wheels, `--require-hashes`— antes de validar, y si falla
  no copia nada (`webapp/librerias.py`). Sin internet: `wheels/` del plugin
  o de la instalación y la opción "sin internet" al instalar. Plug ins →
  Librerías: runtime, qué pide cada plugin, qué falta, instalar. El build del
  `.exe` deja `runtime-release.json` (Python exacto + librerías base) y el
  workflow lo sube como asset del release; el catálogo pasa
  `compatible_runtime`. `describe_installation` suma `librerias` y el
  resumen dice el runtime y qué falta.
- **Terminal del agente flotante.** La terminal de instalar/loguear un CLI
  salió de la vista Agente a `webapp/static/js/agent_terminal.js`, un
  singleton montado sobre `body` con un indicador fijo en la barra lateral:
  sobrevive al cambio de pestaña mientras un login OAuth tarda. Con un solo
  proveedor instalado, Agente lo abre directo con su acordeón desplegado.
- **Grilla de Sources sin filtrarse por detrás.** El grupo fijo de las
  columnas del bot medía lo que medía su contenido, no la fila: en la fila
  de filtros eran 8px opacos y los selects de los datos asomaban por arriba
  y por abajo (se veía a 1181–1400px de ancho). `align-self: stretch` en
  `.tabla__grupo-fijo`; verificado por CDP a 1360/1280/1100.
- **Filtros en las columnas del bot** (Estado, Últ. ejec., Flujo, marca):
  filtran las filas de la página ya cargada, sin releer la fuente, porque
  ese estado no está en la API sino en el bot; la nota de la barra lo dice
  cuando hay uno activo. La marca de selección pasó al final de la fila.
- **Núcleo v0.3.1-beta.1** vendorizado (desde v0.3.0-beta.4): trae core#15
  (`on_step`: la barra de la columna Log pasa a ser por nodo; `run_with_gate`
  ya lo pasaba), core#16 (`default_root`/`default_plugins` en el MCP) y
  core#17 (`describe_installation`, `list_flows`/`get_flow`,
  `list_runs`/`get_run`/`get_case_log`, `write_resource_item`/
  `delete_resource_item`, instrucciones que arrancan por la orientación,
  `extra_tools`/`extra_handlers`/`instructions_extra`).
- **Manual agéntico.** La app deja `AGENTS.md` (+ `CLAUDE.md` → `@AGENTS.md`)
  en la carpeta de la instalación y lo regenera al arrancar y al cambiar
  flujos, plugins o colecciones (`webapp/contexto_agente.py`); contra el
  repo no se genera. `webapp/mcp_servidor.py` quedó en pasar al núcleo
  `default_root`, `default_plugins` y lo propio de la app:
  `describe_installation` enriquecido con `fuentes` y `notas`,
  `preview_source`, y `write/delete_resource_item` envueltos para
  regenerar el manual. Plugin local `conocimiento` con la colección `notas`
  (Plug ins → Conocimiento), que el agente también escribe.
- **Panel lateral plegable**: « junto a FLOW-BOT lo deja en una franja de
  38px con la marca sola, que lo vuelve a abrir; se recuerda en
  `localStorage` del navegador (`lateral-plegado`).
- **Bots que se hablan.** `POST /runs` corre un flujo sin esperar y
  devuelve un ticket; `GET /runs/ticket/<t>` dice en cola / en vuelo (con
  paso) / terminado (con el run). Plugin `bots` en el catálogo (`estado`,
  `elegir_libre`, `correr`, `esperar`, colección *Bots conocidos* con
  *Probar*). Verificado: un flujo padre eligió un Bot, derivó un caso con
  ticket y esperó el resultado; el hijo corrió con source `bot:<caso>`.
- **Sondeo permanente.** Sources mira `runs/en-vuelo` siempre (1.5 s con
  algo corriendo, 5 s sin nada); Workflows relee la lista cada 5 s. Un run
  o un flujo que dispara otro Bot, un agente remoto u otra pestaña se ve
  sin recargar.
- **Agentes sin Node, sin `irm | iex`.** Windows Defender marcaba el
  instalador oficial de Claude Code lanzado desde la app como
  `Trojan:Win32/Commando.A!ml` (heurística sobre "PowerShell baja y
  ejecuta"). Los tres CLIs se instalan con **winget** (`--source winget`,
  porque la tienda fallaba con certificado en la PC del cliente); sin
  winget, Claude Code se baja y verifica (SHA256 + Authenticode) desde
  `webapp/instalar_agente.py`; "Manual / otro" instala cualquier id de
  winget. Verificado: `OpenAI.Codex` 0.152.0 instalado desde la fila Manual.
- **Ícono propio** (`installer/packaging/bot.ico`) en instalador, accesos
  directos y buscador de Windows; casilla "ícono en el escritorio" al
  terminar de instalar.
- **Instalador como asset del release**: `.github/workflows/release.yml`
  construye `BotSetup-<versión>.exe` al publicar un release. Verificado con
  `v0.4.1-beta.2`, `beta.3` y `beta.4`.
- Repo abierto nacido de Bot-Produccion (15/09 tarde): sin plugins, sin
  referencias a la empresa. Primer release `v0.4.1-beta.1`.

## 2026-09-15

- **Actualizaciones de la web app** además del núcleo, con los repos
  editables por instalación (Config → Actualizaciones). Verificado dos veces
  seguidas por la ruta sin internet y una desde GitHub con token.
- **MCP desde una instalación**: `webapp/mcp_servidor.py` envuelve
  `backend.mcp` con `root` = la instalación y `connections` cargado; la
  receta lleva `cwd` y `env.PYTHONPATH`/`BOT_ROOT` (Claude Code ignora
  `cwd`). Verificado con `claude -p` desde el `.mcp.json` que deja el login
  en la terminal embebida. Core#16 pide absorberlo.
- Workflows: filtro de la pila junto a "Nodos", "Buscar nodo…" junto a
  "Diagrama", "Ubicar" por tarjeta; abrir una tarjeta ya no abre el panel
  flotante.
- Guardia al reiniciar: si a los 8 s el servidor no salió, `force_exit`.

## 2026-09-14 (todavía en Bot-Produccion)

- Plugins en línea desde un catálogo en GitHub (rama por instalación,
  `.procedencia.json`); el `.exe` instala sin plugins.
- Ícono de bandeja (`webapp/bandeja.py`) y `--red` para operar desde otra
  PC; verificado LAN.
- Barra de progreso en la columna Log (`GET /runs/en-vuelo`); indeterminada
  hasta core#15 (`on_step`).
- ToothFORM por línea de comandos (plugin `toothform`, flujo V3), en el
  catálogo privado.

## Antes

Núcleo v0.3.0-beta.4 vendorizado; wizard de instalación; Sources con
grilla, filtros y ejecución por fila o lote; Workflows en tarjetas/texto con
diagrama y dry run; Config con secretos, límites, base de datos, actores y
actualizaciones del núcleo; pestaña Agente con terminal embebida.

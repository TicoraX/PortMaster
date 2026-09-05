# Changelog

Formato de [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado semántico: la superficie pública son los comandos del CLI, el
esquema de `stack.yaml` y las rutas de la API local.

## [1.4.3] - 2026-09-05

### Agregado

- **Apertura directa en el Explorador de Archivos del sistema (`open-folder`).**
  Botón "Abrir en Explorador" en el modal de selección de carpetas y botón "Carpeta" en las acciones de cada proyecto para abrir Windows Explorer, Finder o gestor Linux de forma nativa (`os.startfile`).
- **Apertura de proyectos en editor de código (`open-editor`).**
  Botón "Editor" en cada ficha de proyecto con auto-detección de VS Code (`code`), Cursor (`cursor`) o variable `$PORTMASTER_EDITOR` / `$EDITOR`.
- **Copiado rápido de ruta con feedback visual.**
  Botón discreto "Copiar ruta" en la ficha del proyecto que copia la ruta exacta al portapapeles y transiciona temporalmente su texto a "Copiado".
- **Carpetas y raíces frecuentes en selector de proyectos.**
  Detección automática de las carpetas padre más comunes de los proyectos registrados (`/api/browse/frecuentes`) presentadas como chips de acceso inmediato en el picker.
- **Soporte de arrastrar y soltar (Drag & Drop) en la zona de registro.**
  Permite arrastrar una carpeta desde el explorador del sistema a la interfaz web para auto-asignar la ruta comparándola con las raíces conocidas.

## [1.4.2] - 2026-09-04

### Corregido

- **Concurrencia y locking seguro en `_Sink` (`server.py`).**
  Protección de mutaciones de buffers de logs (`_partial`, `seq`, `lines`) bajo lock atómico para evitar carreras de hilos y pérdida de orden de líneas.
- **Optimización de memoria y rendimiento O(1) en Action Budget (`mcp.py`).**
  Uso de `collections.deque` con `popleft()` en lugar de filtrado $O(N)$ de listas para el límite de llamadas/minuto.
- **Consistencia atómica en telemetría MCP (`mcp.py`).**
  Adquisición concurrente y atómica de `_action_lock` y `_telemetry_lock` en `get_telemetry()`.
- **Lectura eficiente y robusta de historial (`history.py`).**
  Reemplazo de algoritmo manual de búsqueda de bytes por lectura en streaming con `collections.deque(maxlen=limit)`, eliminando problemas de fragmentación en líneas extensas.
- **Tolerancia a particiones inaccesibles en explorador de archivos (`browse.py`).**
  Manejo defensivo de excepciones `OSError` al enumerar unidades de disco con `psutil.disk_partitions`.
- **Detección precisa de Deno con comentarios y uv en `pyproject.toml` (`detect.py`).**
  Soporte para comentarios en archivos `deno.json` / `deno.jsonc` y corrección de expresión regular para `[tool.uv]` evitando colisiones con `[tool.uvicorn]`.
- **Terminación eficiente de procesos (`runner.py`).**
  Reducción del timeout de espera en reintento tras SIGKILL en `_terminate_tree`.
- **Reintentos automáticos en CLI de logs (`cli.py`).**
  Mecanismo de reconexión y tolerancia a fallos transitorios en `portmaster logs --follow`.
- **Accesibilidad web WCAG (`web/app.js`).**
  Asignación de atributos `aria-controls` e identificadores correspondientes en los botones colapsables del dashboard.
- **Ampliación de matriz de CI (`.github/workflows/ci.yml`).**
  Incorporación de Python 3.11 y 3.12 en la suite de pruebas automatizadas de Ubuntu.

## [1.4.1] - 2026-09-04

### Corregido

- **Control de streaming SSE de logs en proyectos detenidos.**
  Verificación de estado activo antes de abrir `EventSource` para evitar errores 404 innecesarios en la consola del navegador.
- **Directivas explícitas de seguridad CSP.**
  Incorporación de `script-src 'self'` y `style-src 'self'` en la cabecera `Content-Security-Policy`.
- **Prevención de carreras en el sondeo web.**
  Uso de `AbortController` en `refresh()` para cancelar peticiones en vuelo al navegar entre páginas o cambiar filtros.

## [1.4.0] - 2026-09-04

### Agregado

- **Streaming de logs en vivo por SSE (`/api/projects/{pid}/logs/stream`).**
  Permite monitorear la salida en tiempo real con indicador "En vivo", reconexión automática y emisión periódica de keepalive.
- **Grafo interactivo de dependencias DAG (SVG).**
  Visualización topológica de los servicios y dependencias con estados en tiempo real directamente en la ficha del proyecto.
- **Selector reactivo de perfiles con conmutación en vivo.**
  Permite alternar entre perfiles (`all`, `backend`, `frontend`, etc.) desde la UI web con recarga transparente y preservación de estado.

## [1.3.0] - 2026-08-29

### Agregado

- **Comandos `test-stack`, `history`, `logs` y `stats`.** `test-stack` valida el
  `stack.yaml` sin arrancar nada. `history` lista los últimos arranques con su
  duración y su resultado, que registra la interfaz web en
  `~/.portmaster/history/`. `logs` y `stats` (alias `top`) le consultan al
  `portmaster serve` abierto.
- **`restart` y `max_retries` en `stack.yaml`.** `restart` vale `no` (el
  default), `on-failure` o `always`, y `max_retries` es el tope de reintentos,
  por default 3. El vigilante vive en el seguimiento de logs, así que actúa
  mientras `up` corre o mientras la interfaz tiene la sesión viva.
- **`portmaster up --env-file`.** Carga un `.env` en el entorno antes de
  resolver el stack, para la corrida puntual contra otro entorno. El `env:` de
  cada servicio le sigue ganando.
- **Rutas `/api/projects/{pid}/history` y `/api/projects/{pid}/metrics`.** Las
  métricas también viajan en `/api/state`, así que la interfaz no pide de más.
- **Herramientas MCP `portmaster_history` y `portmaster_init`.** Y un tope de 30
  llamadas por minuto, contra el bucle de un agente trabado.
- **Detección de proyectos Deno**, por `deno.json` y sus tareas `dev`, `start` o
  `serve`.
- **`doctor` avisa de placeholders en el `.env`**, del tipo `changeme` o
  `your_api_key`.

### Arreglado

- **La CPU de `stats` y de la interfaz medía 0.0 siempre.** `cpu_percent` de
  psutil calcula el delta contra la lectura anterior del *mismo* objeto
  `Process`, y el código creaba uno nuevo en cada llamada, así que nunca había
  lectura anterior. Afectaba a `portmaster stats`, a
  `/api/projects/{pid}/metrics` y al badge de la tarjeta por igual. El test que
  debía cubrirlo preguntaba si la clave `cpu_percent` existía, o sea la forma, y
  estaba en verde con la métrica muerta.
- **`portmaster test-stack` terminaba en traceback después de validar bien.**
  Imprimía un `✓`, que no existe en cp1252, la página de códigos con la que sale
  la consola de Windows. `UnicodeEncodeError` sobre un comando que ya había
  hecho su trabajo.
- **Apagar mientras un reinicio automático corría su `pre_start` se colgaba.**
  `restart` mantenía tomado el lock de la lista de procesos mientras ejecutaba
  el hook, y `down` necesita ese mismo lock. El presupuesto de un `pre_start`
  son 900 segundos, así que el apagado podía quedarse esperando ese tiempo.
- **El servidor MCP llamaba a `doctor.check()`, que no existe**, y leía
  `r.kind`, cuando el campo se llama `level`. La herramienta `portmaster_doctor`
  no podía funcionar.
- **`portmaster_free_port` no validaba el rango del puerto** antes de escanear.
- **Un `pre_start` o un `post_start` en curso sobrevivía al apagado.** Corrían
  con `subprocess.run`, que no deja handle, así que `down` no tenía a quién
  matar: volvía en el acto y el hook seguía hasta su presupuesto de 900s. Ahora
  quedan registrados y el apagado los baja con `_terminate_tree`, como el
  `CLAUDE.md` pide para todo lo que se lance con `shell=True`.
- **El `stop:` de un servicio podía correr dos veces a la vez.** `restart` baja
  el proceso viejo con el lock suelto, y en esa ventana `down` copiaba la lista
  y lo encontraba todavía ahí. Ahora hay un solo responsable por proceso.

### Cambiado

- **`portmaster_share` solo publica puertos que el proyecto declara**, y nunca
  el de la propia interfaz. Del otro lado hay un agente y no una persona
  mirando la pantalla. El CLI no cambia: ahí el puerto lo escribís vos.
- **Los comandos de `stack.yaml` no se filtran por contenido.** Una lista de
  patrones destructivos llegó a revisar cada `command`, `pre_start`,
  `post_start`, `stop` y script. Se sacó: bloqueaba limpiezas normales como
  `rm -rf ~/.cache/mi-proyecto` o `drop database test_db`, y dejaba pasar el
  mismo borrado escrito con una variable de por medio. Quien escribe un
  `stack.yaml` ya tiene ejecución arbitraria, así que la lista no defendía de
  nadie y sí le rompía el archivo al dueño del proyecto.

## [1.2.1] - 2026-08-19

### Arreglado

- **Apagar un stack que arrancó otro proceso.** Los contenedores de un
  `docker compose up -d` desde la terminal publican su puerto, así que la
  tarjeta los pinta "listo". Pero sin sesión el proyecto quedaba "detenido",
  `Apagar` en gris y `/down` contestando 404: la interfaz mostraba algo vivo que
  no podía bajar. Ahora `/down` arma la sesión y apaga igual.
- **El apagado sin sesión mataba el proxy de Docker.** Corría `kill` sobre el
  proceso dueño de cada puerto, y para un contenedor ese proceso es el motor:
  lo mataba y dejaba el contenedor corriendo sin publicar. Ahora corre el
  `stop:` del servicio y solo mata por pid lo que no tiene uno. Alcanza también
  al caso de la sesión que sobrevive a un reinicio del servidor.
- **`Reiniciar` sobre un servicio ajeno daba 404.** El botón se dibujaba
  mirando el estado del puerto, que no dice quién arrancó el proceso.
- **La tarjeta y el panel de intrusos se contradecían.** El panel saltea los
  proxies de Docker a propósito; la tarjeta no los distinguía, y ofrecía un
  `Liberar` que iba a matar el backend de Docker Desktop entero. Ahora dice que
  es un contenedor y no ofrece cerrarlo.
- **El selector de perfil decía "todo" y arrancaba el `default:`.** Ahora
  nombra los servicios que va a levantar.
- **Contraste de las pastillas de estado en modo claro.** El color de cada tono
  está calibrado para pintar el punto sobre el papel, y se reusaba como tinta
  del texto sobre una versión tenue de sí mismo: `listo` daba 3.97:1 y
  `arrancando` 2.83:1, los dos por debajo del 4.5:1 de WCAG AA. En modo oscuro
  ya cumplían y no cambian.

## [1.2.0] - 2026-08-19

### Agregado

- **`url:` por servicio en `stack.yaml`**: adónde lleva el botón `Abrir`, en la
  interfaz y en `portmaster open`. Sin él sigue siendo `http://localhost:<port>`,
  que es correcto para casi todo y no alcanza para lo que no vive en la raíz del
  puerto: una app montada en `/admin`, o una que pide un token en la query.
  Admite `${VAR}` y `${VAR:-default}`, resueltos con **el mismo entorno con el
  que corre el servicio**, así que si la URL necesita un token es el token que
  recibió el proceso. Solo `http://` y `https://`: otro esquema es error al
  cargar el archivo, no por seguridad —un `stack.yaml` ya ejecuta comandos
  arbitrarios— sino para que escribir `127.0.0.1:8765` sin esquema dé un mensaje
  claro en vez de una ruta relativa. Una variable sin valor deja el servicio sin
  URL: abrir una con el `${TOKEN}` literal adentro carga una página que falla por
  dentro y parece que funcionó.

### Arreglado

- **La interfaz se recortaba por debajo de 640px.** Dos filas de acciones eran
  flex sin `flex-wrap`, así que su ancho mínimo era la suma de los botones y no
  podían encoger. Como `html, body` llevan `overflow-x: clip`, ese desborde no
  daba scroll: daba contenido invisible e inalcanzable. A 375px, `Detalles`,
  `Quitar proyecto` y `Limpiar Docker` quedaban fuera de la pantalla.
- **Con la ficha cerrada se tabulaba hasta `Quitar proyecto`.** El acordeón
  cerraba con `opacity: 0`, que no saca nada del orden de tabulación ni del árbol
  de accesibilidad: cuatro Tab desde el propio toggle caían en controles
  invisibles, el último destructivo, mientras `aria-expanded` decía `false`. Un
  lector de pantalla además leía la lista completa de servicios de cada proyecto
  cerrado.
- **El aviso de puerto compartido nombraba la carpeta y no el proyecto.** Con
  `apps/Fitness` declarando `name: fittrack`, el aviso mandaba a buscar un
  proyecto que en la interfaz no existe. `portmaster list` tenía lo mismo en la
  columna NOMBRE.
- **`portmaster open` reventaba con un traceback** cuando un servicio declaraba
  `url:` con una variable sin valor y no tenía `port:`: no hay default al que
  caer y se abría `None`. Además, un candidato sin puerto cortocircuitaba el
  recorrido y tapaba a los servicios que sí contestaban.
- **`share` aceptaba puertos que no existen.** `POST /api/share?port=0`
  contestaba 200, igual que -5, 70000 y 99999, y reservaba la entrada antes de
  validar; `portmaster share 0` levantaba el cliente de túneles contra
  `127.0.0.1:0`.
- **El servidor MCP dejaba los túneles abiertos** al terminar la sesión, con el
  puerto expuesto a internet. Es el mismo cierre que la interfaz ya hacía.
- **El MCP contestaba notificaciones.** JSON-RPC define notificación como
  petición sin `id` y prohíbe responderlas; se reconocía una sola por nombre.
- **Un hook `pre_start` o `post_start` colgado rompía el arranque** con un
  traceback crudo en vez de decir qué servicio y qué hook se quedaron esperando.
- **Un valor de `.env` entrecomillado con un comentario detrás conservaba las
  comillas.** `TOKEN="abc"  # el de prod` entregaba el token con las comillas
  pegadas, que no falla al arrancar: falla en la primera petición autenticada.
- **El botón de limpieza de Docker podía quedar armado** entre aperturas del
  diálogo, salteándose la confirmación de un borrado.
- **El extractor de URL de tailscale aceptaba cualquier `https://` del log**, así
  que un enlace a la documentación o al login se reportaba como la URL del túnel.
- La pestaña del túnel bloqueada por el navegador ahora se avisa; el mapa de
  puertos ya no se corta en "ocupa el puerto de "; el aviso de volúmenes se
  anuncia a un lector de pantalla; y la casilla de intrusos llega a los 24px de
  área sensible que pide WCAG 2.5.8.

## [1.1.1] - 2026-08-16

### Cambiado

- La confirmación de "Reiniciar Docker" nombra los contenedores que se va a
  llevar, en vez de decir "los contenedores". Reiniciar el motor los baja a
  todos, incluidos los de proyectos que no estás mirando, y no se puede hacer a
  medias: nombrarlos antes es lo único que se puede hacer por quien aprieta el
  botón. Si el motor no contesta a tiempo, queda la frase de siempre.

## [1.1.0] - 2026-08-15

### Agregado

- **Runner de Tareas (`portmaster run`)**: Soporte para la sección `scripts:` en `stack.yaml` permitiendo ejecutar tareas individuales o pipelines secuenciales con inyección completa de variables de entorno.
- **Túneles Seguros (`portmaster share`)**: Integración sin configuración adicional con `cloudflared`, `ngrok`, `lt` y `tailscale` para exponer puertos locales a URLs públicas HTTPS efímeras.
- **Higiene del Host (`portmaster clean`)**: limpieza de Docker por categorías,
  con un comando propio para cada una en vez del `system prune` que las tira
  todas juntas. Contenedores parados, imágenes sin tag, redes sin usar y caché
  de build; los volúmenes anónimos van aparte, porque tienen datos adentro y no
  se regeneran. Pregunta antes mostrando `docker system df`, y `--yes` la
  saltea. En el CLI se acota con `--solo cache --solo images`; en la interfaz,
  el botón abre un diálogo con una casilla por categoría.
- **Servidor MCP para Agentes de IA (`portmaster mcp`)**: Servidor Model Context Protocol nativo sobre `stdio` para introspección y control en tiempo real desde Claude Desktop, Cursor, Gemini y Antigravity.
- **Proyectos Compuestos (`includes:`)**: Composición modular de stacks importando servicios de otros repositorios o subdirectorios con aislamiento de `cwd` y prevención de ciclos.
- **Matriz de Colisión de Puertos**: Detección anticipada y alerta visual en `portmaster list` sobre puertos en disputa entre proyectos registrados.
- **Variables de Entorno & Hooks**: Soporte para `env_file`, bóveda global `~/.portmaster/env.global`, y hooks de ciclo de vida `pre_start` y `post_start`.
- **Detección Avanzada**: Soporte para `uv run` en proyectos Python y detección de frameworks web modernos (Hono, Fastify, Astro, Vite, Nitro, etc.).
- **Mejoras Web**: Botones interactivos de "Túnel" y "Limpiar Docker" en la interfaz web local.

### Arreglado

- La fila de estado de Docker desaparecía al pasar de página. Salía de los
  cuatro proyectos de la página y no del registro entero, así que bastaba una
  segunda página sin contenedores para que se fueran el estado y los botones.
- La sección "Procesos intrusos" se veía en rojo, con un punto latiendo, aunque
  estuviera diciendo que no hay ninguno. Ahora el rojo aparece solo cuando hay
  algo que mirar: un rojo encendido todo el tiempo deja de significar rojo.
- La caja de logs quedaba en blanco sin explicar por qué. Solo se registran los
  de un stack arrancado desde la interfaz, y ahora lo dice.

### Cambiado

- Cada fila de "Procesos intrusos" separa lo que antes iba pegado con un punto:
  qué proceso ocupa el puerto, qué proyectos lo reclaman, y su línea de comando.
  `node.exe · Decepticon` se leía como "este proceso es de Decepticon", cuando
  es al revés. Y ahora hay una fila por puerto y no una por proyecto: un puerto
  que dos proyectos declaran salía dos veces con el mismo pid.
- El arreglo del servicio propio listado como intruso salió antes, en 1.0.3.

## [1.0.3] - 2026-08-15

### Arreglado

- Un servicio arrancado desde la interfaz podía aparecer en "Procesos intrusos"
  y ser ofrecido para cerrar. Pasaba con los que no declaran puerto y lo eligen
  al arrancar (`ready: listen`: un Next, un vite): ese puerto no entraba en la
  lista de lo que corre por cuenta nuestra, así que otro proyecto registrado que
  declarara ese mismo número lo veía ocupado por un desconocido. Cerrarlo mataba
  el servicio propio, y "Liberar todos" lo hacía de un click sobre todos.

## [1.0.2] - 2026-08-08

### Arreglado

- El sello de `/api/version`, que el pie de página usa para avisar si el
  navegador está sirviendo una página vieja de su cache, miraba tres archivos
  escritos a mano y se olvidaba `tokens.css`. Ahí viven los colores y los
  espaciados, así que un cambio de solo estilos no movía la fecha y el sello
  afirmaba que la página era más vieja de lo que era. Ahora recorre todo lo que
  sirve el mount.

### Notas

- La versión 1.0.1 llevó un flag nuevo del CLI, `--version`. Por versionado
  semántico le correspondía 1.1.0: una funcionalidad compatible es minor, no
  patch. Queda anotado para que el criterio no se repita mal.

## [1.0.1] - 2026-08-08

### Agregado

- `portmaster --version`, además del subcomando `version` que ya existía. Es lo
  primero que prueba cualquiera que acaba de instalar la herramienta, y hasta
  ahora contestaba "No such option".
- Classifiers completos en el paquete: versiones de Python soportadas, tema y
  estado de desarrollo. Sin ellos, PyPI solo lo encontraba por nombre exacto.

## [1.0.0] - 2026-08-06

Primera versión publicada. Lo que sigue es el alcance completo, no un diff.

### Orquestación

- `portmaster up` arranca los servicios en orden topológico, con los que no
  dependen entre sí en paralelo, healthchecks por puerto, log o comando, y
  apagado del árbol completo de procesos al salir.
- `portmaster down` baja un stack de compose puro, corriendo los `stop:` en
  orden inverso.
- `portmaster switch` baja los proyectos registrados que le pisan los puertos a
  uno y lo levanta, sin tocar los que no compiten.
- `stack.yaml` declara servicios, dependencias, puertos, healthchecks, perfiles
  y variables. Sin archivo, `detect` infiere el stack de compose, Django,
  FastAPI, Node, Go, Rust, Rails, Laravel y ASP.NET Core, en la raíz o en
  subcarpetas.
- `portmaster init` congela lo detectado a un `stack.yaml` editable.

### Puertos

- `portmaster ports` y `portmaster free` escanean, identifican al proceso dueño
  y lo cierran con verificación de `create_time` contra el reciclado de PIDs.
- `portmaster free --all` recorre los puertos de todos los proyectos
  registrados y cierra lo que los ocupe, con una sola confirmación que lista
  antes qué va a cerrar.
- El cierre se niega sobre el proceso propio, sobre los PIDs de sistema, y
  sobre el proxy compartido de Docker o WSL, porque cerrar ese proxy apaga el
  motor entero con todos sus contenedores.
- Cuando un healthcheck se agota, el error dice si el servicio abrió otro
  puerto que el declarado, o quién tenía el declarado.

### Interfaz web

- `portmaster serve` levanta una interfaz local en `127.0.0.1:7666` para
  arrancar, apagar y reiniciar servicios de varios proyectos, con logs
  incrementales, explorador de carpetas, buscador, paginado, filtro por estado
  y sección de procesos intrusos.
- La tarjeta marca al lado del puerto cuando otro proyecto registrado declara
  ese mismo puerto, y cuando el puerto ya estaba ocupado antes de arrancar.
- "Liberar todos" cierra de una todos los procesos intrusos, en dos pasos sobre
  el mismo botón: el segundo nombra puertos y procesos antes de hacerlo.
- Estado de Docker en la fila de herramientas cuando algún proyecto lo usa, con
  un botón que abre el motor si está caído y lo reinicia si está arriba.
  Reiniciar pide confirmación: baja todos los contenedores.
- La sección de procesos intrusos ya no desaparece cuando no hay ninguno: lo
  dice.
- Sin build y sin webfonts: la CSP es `default-src 'self'`.

### Diagnóstico

- `portmaster doctor` junta los chequeos en una salida, cada rojo con la línea
  que lo arregla. Funciona en una carpeta que no es un proyecto conocido.
- Compara las claves de `.env.example` contra el `.env` y avisa las que faltan
  o quedaron vacías. Nombres, nunca valores.

### Seguridad

- Token de 32 bytes en `~/.portmaster/token` con permisos 0600, o
  `PORTMASTER_TOKEN`. El servidor no arranca sin token.
- Validación del header `Host` contra rebinding de DNS, antes de cualquier otra
  cosa.
- CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y
  `Cache-Control: no-store` en toda respuesta. Sin `Strict-Transport-Security`:
  el servidor es http sobre loopback y el header rompería cualquier otro
  proyecto local.
- Rate limiting por ruta: 1800 lecturas, 60 escrituras y 30 cierres de proceso
  por ventana.

### Conocido

- Con `ready: port`, un proceso ajeno que ya tenga el puerto declarado hace que
  el servicio figure listo al instante. El arranque lo avisa, por consola y en
  la tarjeta, y no lo impide: `docker compose up -d` sobre un contenedor que ya
  está arriba es el mismo caso y ahí es correcto. Ver `docs/pendientes.md`.

[1.4.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.4.0
[1.3.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.3.0
[1.2.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.2.0
[1.1.1]: https://github.com/TicoraX/PortMaster/releases/tag/v1.1.1
[1.1.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.1.0
[1.0.3]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.3
[1.0.2]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.2
[1.0.1]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.1
[1.0.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.0

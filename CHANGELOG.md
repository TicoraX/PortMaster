# Changelog

Formato de [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado semántico: la superficie pública son los comandos del CLI, el
esquema de `stack.yaml` y las rutas de la API local.

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

[1.2.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.2.0
[1.1.1]: https://github.com/TicoraX/PortMaster/releases/tag/v1.1.1
[1.1.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.1.0
[1.0.3]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.3
[1.0.2]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.2
[1.0.1]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.1
[1.0.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.0

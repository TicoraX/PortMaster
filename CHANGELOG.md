# Changelog

Formato de [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado semántico: la superficie pública son los comandos del CLI, el
esquema de `stack.yaml` y las rutas de la API local.

## [1.1.0] - 2026-08-15

### Agregado

- **Runner de Tareas (`portmaster run`)**: Soporte para la sección `scripts:` en `stack.yaml` permitiendo ejecutar tareas individuales o pipelines secuenciales con inyección completa de variables de entorno.
- **Túneles Seguros (`portmaster share`)**: Integración sin configuración adicional con `cloudflared`, `ngrok`, `lt` y `tailscale` para exponer puertos locales a URLs públicas HTTPS efímeras.
- **Higiene del Host (`portmaster clean`)**: `docker system prune -f` sobre
  contenedores parados, redes sin usar, imágenes sin tag y el caché de build.
  No pide confirmación. Con `--volumes` se lleva además los volúmenes
  anónimos huérfanos, que sin esa opción no toca.
- **Servidor MCP para Agentes de IA (`portmaster mcp`)**: Servidor Model Context Protocol nativo sobre `stdio` para introspección y control en tiempo real desde Claude Desktop, Cursor, Gemini y Antigravity.
- **Proyectos Compuestos (`includes:`)**: Composición modular de stacks importando servicios de otros repositorios o subdirectorios con aislamiento de `cwd` y prevención de ciclos.
- **Matriz de Colisión de Puertos**: Detección anticipada y alerta visual en `portmaster list` sobre puertos en disputa entre proyectos registrados.
- **Variables de Entorno & Hooks**: Soporte para `env_file`, bóveda global `~/.portmaster/env.global`, y hooks de ciclo de vida `pre_start` y `post_start`.
- **Detección Avanzada**: Soporte para `uv run` en proyectos Python y detección de frameworks web modernos (Hono, Fastify, Astro, Vite, Nitro, etc.).
- **Mejoras Web**: Botones interactivos de "Túnel" y "Limpiar Docker" en la interfaz web local.

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

[1.1.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.1.0
[1.0.2]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.2
[1.0.1]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.1
[1.0.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.0

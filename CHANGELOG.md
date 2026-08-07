# Changelog

Formato de [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado semántico: la superficie pública son los comandos del CLI, el
esquema de `stack.yaml` y las rutas de la API local.

## [1.0.0] - 2026-08-06

Primera versión publicada. Lo que sigue es el alcance completo, no un diff.

### Orquestación

- `portmaster up` arranca los servicios en orden topológico, con los que no
  dependen entre sí en paralelo, healthchecks por puerto, log o comando, y
  apagado del árbol completo de procesos al salir.
- `portmaster down` baja un stack de compose puro, corriendo los `stop:` en
  orden inverso.
- `stack.yaml` declara servicios, dependencias, puertos, healthchecks, perfiles
  y variables. Sin archivo, `detect` infiere el stack de compose, Django,
  FastAPI, Node en la raíz o en subcarpetas, y backends Python en subcarpetas.
- `portmaster init` congela lo detectado a un `stack.yaml` editable.

### Puertos

- `portmaster ports` y `portmaster free` escanean, identifican al proceso dueño
  y lo cierran con verificación de `create_time` contra el reciclado de PIDs.
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
- Sin build y sin webfonts: la CSP es `default-src 'self'`.

### Diagnóstico

- `portmaster doctor` junta los chequeos en una salida, cada rojo con la línea
  que lo arregla. Funciona en una carpeta que no es un proyecto conocido.

### Seguridad

- Token de 32 bytes en `~/.portmaster/token` con permisos 0600, o
  `PORTMASTER_TOKEN`. El servidor no arranca sin token.
- Validación del header `Host` contra rebinding de DNS, antes de cualquier otra
  cosa.
- CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y
  `Cache-Control: no-store` en toda respuesta. Sin `Strict-Transport-Security`:
  el servidor es http sobre loopback y el header rompería cualquier otro
  proyecto local.
- Rate limiting por ruta: 900 lecturas, 60 escrituras y 30 cierres de proceso
  por ventana.

### Conocido

- Con `ready: port`, un proceso ajeno que ya tenga el puerto declarado hace que
  el servicio figure listo al instante. El arranque por consola lo avisa; la
  tarjeta de la interfaz web todavía no. Ver `docs/pendientes.md`.

[1.0.0]: https://github.com/TicoraX/PortMaster/releases/tag/v1.0.0

# PortMaster

Herramienta de consola en Python que orquesta entornos de desarrollo locales:
libera puertos, arranca Docker, backend y frontend en orden, y expone una
interfaz web local para gestionar varios proyectos.

## Estructura

| Modulo | Responsabilidad |
|---|---|
| `ports.py` | Escaneo de puertos, identificacion del proceso dueno, cierre seguro |
| `config.py` | Carga y validacion de `stack.yaml` |
| `detect.py` | Servicios inferidos del proyecto cuando no hay `stack.yaml` |
| `runner.py` | Arranque en orden topologico, healthchecks, apagado del arbol |
| `registry.py` | Proyectos conocidos por la interfaz, y el token de la API |
| `docker.py` | Arranque y reinicio de Docker Desktop. Diagnosticar si esta arriba es de `doctor.py` |
| `server.py` | API local en FastAPI |
| `web/` | Interfaz: HTML, CSS y JS sin build |
| `cli.py` | Comandos Typer |

El core no depende de la terminal. El CLI y el servidor son dos consumidores de
las mismas funciones; cualquier logica nueva va en el modulo correspondiente, no
en `cli.py` ni en `server.py`.

## Desviaciones deliberadas de las reglas globales

Cada una con su motivo. No revertirlas sin leerlo primero.

### El token no vive en un `.env`

La regla pide secretos en `.env` con validacion al arrancar. PortMaster se
instala con `pipx` o `uv tool`: no hay repositorio donde poner un `.env`, y
pedirle al usuario que genere y copie un token a mano garantiza que termine
usando `token=1234`.

En su lugar: `PORTMASTER_TOKEN` tiene prioridad si existe, y si no,
`registry.token()` genera uno de 32 bytes en `~/.portmaster/token` con permisos
0600. Se valida largo minimo de 16 en ambos casos y el servidor no arranca sin
token. El secreto queda fuera del repo, que es lo que la regla protege.

### Las cuotas de rate limit no son las de referencia

La referencia es 100/15min general. La interfaz sondea `/api/state` cada 2.5s,
que da unas 360 peticiones por ventana: con 100 se rompe el uso normal. Las
cuotas quedaron en `QUOTA_READ = 1800`, `QUOTA_WRITE = 60`, `QUOTA_KILL = 30`.
Las rutas que ejecutan comandos o matan procesos son las que van cortas, que es
donde la regla importa.

### Sin `Strict-Transport-Security`

El servidor es http sobre loopback. Ese header le impondria https a todo
`127.0.0.1` en el navegador del usuario y romperia cualquier otro proyecto local
que corra en http. Los otros headers (CSP, nosniff, DENY, no-referrer) si estan.

En su lugar, contra rebinding de DNS: validacion del header `Host` contra
`127.0.0.1` y `localhost`, antes de cualquier otra cosa.

### `shell=True` en los subprocesos

`npm run dev` y `docker compose up -d` no son ejecutables. `stack.yaml` ya es
codigo ejecutable por diseno, igual que `package.json` o un `Makefile`, y el
README lo documenta. Por eso el apagado mata el arbol de procesos completo: con
`shell=True` el hijo directo es el shell y matarlo solo a el deja huerfano al
servidor de verdad.

### La interfaz no usa webfonts

La CSP es `default-src 'self'`. Una herramienta local que le pide fuentes a un
CDN en cada carga filtra actividad y deja de funcionar sin internet. Los tres
roles tipograficos salen de stacks del sistema.

## Tests

`pytest`. Todo con sockets y procesos reales, sin mocks: es la unica forma de
probar un modulo cuyo trabajo es hablar con el sistema operativo. La CI corre en
Linux, macOS y Windows porque los tres divergen justo ahi.

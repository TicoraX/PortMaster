# Autodeteccion de servicios

`stack.yaml` deja de ser obligatorio. `portmaster up` en una carpeta sin
configuracion detecta los servicios del proyecto, los arranca, y ofrece
congelar lo detectado con `portmaster init`.

## Modulo nuevo: `detect.py`

`detect(root) -> Stack | None` construye los mismos `Stack` y `Service`
congelados que produce `config.load`, asi que `runner`, `server` y `cli` no
distinguen el origen. Devuelve `None` si no reconoce nada.

Tres detectores, cada uno `Path -> Service | None`:

| Detector | Dispara con | Servicio |
|---|---|---|
| `_compose` | `compose.yaml`, `compose.yml`, `docker-compose.yml`, `docker-compose.yaml` | `docker`: `docker compose up -d`, `detached=True`, `ready="none"`, puerto del primer `ports:` publicado |
| `_python` | `manage.py`, o `fastapi`/`uvicorn` en `pyproject.toml`/`requirements.txt` con un modulo que defina `app` | `api`: `python manage.py runserver` o `uvicorn <mod>:app --reload`, `ready="listen"` |
| `_node` | `scripts.dev` en `package.json`, si no `scripts.start` | `web`: `npm run dev`, con `pnpm`/`yarn`/`bun` segun el lockfile, `ready="listen"` |

Las dependencias salen de la cadena fija `docker -> api -> web`, sobre el
subconjunto que exista. Sin perfiles: un stack detectado arranca completo.

`stack_for(root) -> Stack` es el punto de entrada unico para los consumidores:
carga el archivo si existe, detecta si no, y tira `ConfigError` si ninguna de
las dos cosa da resultado. `Stack` gana un campo `detected: bool`.

Solo mira la raiz del proyecto. Un monorepo con `frontend/` y `backend/` en
subcarpetas no se detecta, y sigue necesitando `stack.yaml`.

## `ready: "listen"`

Cuarto valor de `READY_KINDS`. El servicio esta listo cuando el arbol de su
proceso tiene un socket en LISTEN. `Proc` gana `port`, el puerto descubierto,
que es lo que se imprime en `listo (5173)` y lo que sale por `/api/state`.

Un servicio con `ready: "listen"` y `port` declarado es un error de
configuracion: si conoces el puerto, el healthcheck es `ready: "port"`.

`ports.listening(pid) -> int | None` recorre el arbol con psutil y devuelve el
primer puerto en LISTEN. Los procesos son hijos nuestros, asi que
`Process.net_connections()` no pide permisos elevados.

## Consecuencia aceptada: sin liberacion previa del puerto

`up` libera los puertos declarados antes de arrancar. Un servicio con
`ready: "listen"` no tiene puerto declarado, asi que no hay nada que liberar:
si Vite encuentra 5173 ocupado se corre a 5174, y PortMaster reporta 5174.
Compose conserva la liberacion, porque declara sus puertos.

Es el costo de descubrir el puerto en vez de adivinarlo parseando
`vite.config.ts`, `next.config.js`, los flags del script y `.env`, cada uno un
lugar donde el puerto puede estar y el parser fallar. Se acepta.

## Integracion

- `cli.up` y `cli.ports` usan `stack_for`. Con stack detectado, `up` imprime la
  tabla de lo detectado y pide confirmacion, salvo `-y`.
- `cli.init` escribe el `stack.yaml` detectado y no sobreescribe uno existente.
  Es comando aparte y no un prompt dentro de `up`, porque `up` corre en
  foreground siguiendo logs y la pregunta quedaria enterrada en la salida.
- `registry.add` acepta una carpeta detectable, no solo una con `stack.yaml`.
- `server._project_view` y `server.up` usan `stack_for`.

## Tests

`test_detect.py`: directorios temporales con `package.json`, un compose y un
`manage.py`, verificando comandos, orden y puerto de compose. Un test de
`ready: "listen"` con un proceso real que abre un socket, que es la unica forma
de probar el descubrimiento.

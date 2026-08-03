# Pendientes

Estado al 30 de julio de 2026. Lo que quedó abierto, ordenado por lo que cuesta
dejarlo así, no por lo que cuesta arreglarlo.

## Sin verificar contra la realidad

Lo primero, porque son cosas que ya están escritas y funcionando en tests, pero
que nadie vio funcionar de verdad.

**Que `Apagar` baje contenedores.** Los servicios detectados de un compose traen
`stop: docker compose stop <nombre>`, y en los logs se ve el comando corriendo,
fallando con el daemon cerrado y siendo reportado sin tumbar el apagado. Falta
correrlo con Docker Desktop abierto: arrancar Fitness, apretar `Apagar`, y que
`docker ps` quede vacío. Hasta que eso pase, el botón está probado contra un
proceso de mentira, no contra un contenedor.

**El botón `Abrir` abriendo pestaña.** El enlace es correcto (`href` al puerto,
`target="_blank"`, `rel="noopener noreferrer"`) y el destino contesta 200, pero
en headless la pestaña nueva no se puede observar. Un click en un Chrome de
verdad lo cierra.

## Techos marcados en el código

Cada uno tiene su comentario `ponytail:` con la salida escrita al lado. Ninguno
es un bug; son decisiones con fecha de vencimiento conocida.

| Dónde | Qué se aguanta | Cuándo tocarlo |
|---|---|---|
| `runner._speaks_http` | Un solo sondeo al quedar listo | Un dev server que compila en la primera petición (Next) se queda sin botón `Abrir`. La salida es re-sondear desde la vista de estado con caché, no reintentar en el arranque |
| `server._markers` | Un `stat` por marcador y por carpeta, hasta ~1800 en un listado grande | Si el explorador se siente lento en una carpeta con cientos de hijos: un solo `scandir` por carpeta e intersecar nombres |
| `server.RateLimit` | Ventana en memoria, un proceso | Si alguna vez hay más de un worker |
| `ports._pid_by_process_scan` | O(procesos), una llamada al SO por proceso | Solo corre en el camino lento. Si pesa, cachear la tabla entre puertos de un mismo escaneo |
| `detect.VARIABLE` | Solo `${VAR}` y `${VAR:-default}` | Un compose que use `$VAR` a secas deja el puerto desconocido. Se resuelve el día que aparezca uno |
| `runner` (módulo) | Logs prefijados, sin dashboard `rich.live` | Cuando haya un caso concreto que lo pida |
| `server.Session.stop` | Un detached en curso no se corta, se lo espera | Si apagar mientras `docker compose up -d` construye una imagen se hace molesto: matar el árbol del comando detached |

## Lo que se puede agregar

Ideas, no compromisos. Cada una con el motivo por el que todavía no está.

**Backend Python en subcarpetas.** La detección de Node baja una vuelta
(`apps/*`, `frontend/`, etc.), la de Python no: sigue mirando solo la raíz. Un
monorepo con `services/api/` y su `pyproject.toml` no se detecta. Es el mismo
patrón ya escrito, aplicado a `_python`.

**Perfiles en stacks detectados.** Hoy un stack detectado tiene `profiles: {}`,
así que arranca entero o nada. Un perfil obvio saldría del propio compose
(`profiles:` ya existe ahí) y otro sería "solo lo que no es contenedor", para
laburar con el front sin levantar la infra.

**Arranque en paralelo.** Los servicios sin dependencias entre sí se esperan
igual, uno detrás del otro. Arrancarlos juntos ahorra la suma de los
healthchecks, y a cambio entrevera los logs de los primeros segundos.
`stack.example.yaml` lo prometía por error y ahora dice lo que el runner hace.

**Reiniciar un servicio suelto.** Hoy es todo o nada. Cuando el frontend se
cuelga, bajar y subir el stack entero levanta también los contenedores que
estaban bien.

**`portmaster open`.** El CLI ya sabe qué puerto contesta HTTP e imprime la URL
al arrancar. Un comando que la abra en el navegador es una línea con
`webbrowser`, y sirve cuando ya tenés el stack corriendo en otra terminal.

**Botón `Abrir` a nivel proyecto.** El de la tarjeta, que lleve al primer
servicio que conteste HTTP, para no buscar cuál de los tres es el frontend. Se
descartó al elegir cómo detectar lo abrible; la data ya está, es solo interfaz.

**Autocompletado en el input de ruta.** El explorador cubre el caso, pero
escribir `A:\Proy` y que sugiera es más rápido cuando ya sabés a dónde vas. El
endpoint `/api/browse` ya devuelve lo necesario.

**Sesiones que sobrevivan al reinicio del servidor.** `sessions` vive en
memoria: si reiniciás `portmaster serve`, pierde de vista lo que había
arrancado, aunque los procesos sigan vivos. Para los contenedores no importa
tanto, porque el estado se recalcula sondeando el puerto; para un `npm run dev`
sí, queda huérfano y sin logs.

## Cómo retomar

```bash
# Docker Desktop primero, si el proyecto tiene compose
portmaster serve

# la prueba que falta
docker ps          # antes y despues de apretar Apagar
```

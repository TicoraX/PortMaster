# Pendientes

Estado al 30 de julio de 2026. Lo que quedó abierto, ordenado por lo que cuesta
dejarlo así, no por lo que cuesta arreglarlo.

## Sin verificar contra la realidad

**El botón `Abrir` abriendo pestaña.** El enlace es correcto (`href` al puerto,
`target="_blank"`, `rel="noopener noreferrer"`) y el destino contesta 200, pero
en headless la pestaña nueva no se puede observar. Un click en un Chrome de
verdad lo cierra.

## Techos marcados en el código

Cada uno tiene su comentario `ponytail:` con la salida escrita al lado. Ninguno
es un bug; son decisiones con fecha de vencimiento conocida.

| Dónde | Qué se aguanta | Cuándo tocarlo |
|---|---|---|
| `server._markers` | Un `stat` por marcador y por carpeta, hasta ~1800 en un listado grande | Si el explorador se siente lento en una carpeta con cientos de hijos: un solo `scandir` por carpeta e intersecar nombres |
| `server.RateLimit` | Ventana en memoria, un proceso | Si alguna vez hay más de un worker |
| `ports._pid_by_process_scan` | O(procesos), una llamada al SO por proceso | Solo corre en el camino lento. Si pesa, cachear la tabla entre puertos de un mismo escaneo |
| `detect.VARIABLE` | Solo `${VAR}` y `${VAR:-default}` | Un compose que use `$VAR` a secas deja el puerto desconocido. Se resuelve el día que aparezca uno |
| `runner` (módulo) | Logs prefijados, sin dashboard `rich.live` | Cuando haya un caso concreto que lo pida |
| `server.Session.stop` | Un detached en curso no se corta, se lo espera | Si apagar mientras `docker compose up -d` construye una imagen se hace molesto: matar el árbol del comando detached |

## Lo que se puede agregar

Ideas, no compromisos. Cada una con el motivo por el que todavía no está.

**Perfiles en stacks detectados.** Hoy un stack detectado tiene `profiles: {}`,
así que arranca entero o nada. Un perfil obvio saldría del propio compose
(`profiles:` ya existe ahí) y otro sería "solo lo que no es contenedor", para
laburar con el front sin levantar la infra.

**Arranque en paralelo.** Los servicios sin dependencias entre sí se esperan
igual, uno detrás del otro. Arrancarlos juntos ahorra la suma de los
healthchecks, y a cambio entrevera los logs de los primeros segundos.
`stack.example.yaml` lo prometía por error y ahora dice lo que el runner hace.

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

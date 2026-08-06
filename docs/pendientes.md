# Pendientes

Estado al 6 de agosto de 2026, 192 tests. Lo que quedó abierto, ordenado por lo
que cuesta dejarlo así, no por lo que cuesta arreglarlo.

El plan del 3 de agosto (`plan-siguiente.md`) se ejecutó entero y quedó cerrado.
Este documento es la brújula del tramo que sigue.

## Bugs conocidos

**Un servicio con `ready: port` figura listo apuntando a un proceso ajeno.**
`runner.py:319`. Si alguien más tiene el puerto declarado cuando arranca el
servicio, `_is_ready` devuelve `True` en el acto y la tarjeta lo muestra en
verde señalando a un intruso. El arreglo obvio, exigir que el dueño del puerto
sea del árbol del proceso, rompe el caso legítimo de `docker compose up -d`
sobre un contenedor que ya está arriba, que es justo lo que hace que arrancar un
stack a medio levantar no cancele. Necesita distinguir esos dos casos antes de
tocarse.

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
| `server.project_payload` | Un puerto que publica el proxy de Docker se asume del proyecto que se está mirando | Si dos proyectos registrados declaran el mismo puerto. Preguntarle a `docker ps` cuesta un subproceso y esto se sondea cada 2.5s |
| `server.Session.stop` | Un detached en curso no se corta, se lo espera | Si apagar mientras `docker compose up -d` construye una imagen se hace molesto: matar el árbol del comando detached |
| `ports._pid_by_process_scan` | O(procesos), una llamada al SO por proceso | Solo corre en el camino lento. Si pesa, cachear la tabla entre puertos de un mismo escaneo |
| `detect.VARIABLE` | Solo `${VAR}` y `${VAR:-default}` | Un compose que use `$VAR` a secas deja el puerto desconocido. Se resuelve el día que aparezca uno |
| `runner` (módulo) | Logs prefijados, sin dashboard `rich.live` | Cuando haya un caso concreto que lo pida |

## Cerrado

**El fallo intermitente de la suite.** Apareció una vez al agregar el arranque
en paralelo y quedó abierto un mes. Se corrió `test_runner.py` veinte veces
seguidas el 6 de agosto sin un solo rojo, sobre 29 corridas previas sin
reproducirlo. Si vuelve, el primer rojo de CI se mira en vez de reintentarlo.

**`PAGE_MIN`, los estilos inline y el `?v=1.5`.** El cache busting a mano no
hacía nada desde que el middleware manda `Cache-Control: no-store` en toda
respuesta, mounts incluidos. Cubierto por `test_los_estaticos_no_se_cachean`.

## Lo que se puede agregar

Ideas, no compromisos. Cada una con el motivo por el que todavía no está.

**Más ecosistemas en `detect`.** Hoy cubre compose, Node, FastAPI y Django. Go,
Rust, .NET, Rails y Laravel quedan afuera, y la promesa del README es que un
comando levanta lo que sea. Cada detector nuevo son ~30 líneas con su test, y
es la parte del producto donde el esfuerzo se convierte más directo en alcance.

**`env_file:` en `stack.yaml`.** Hoy las variables se declaran una por una.

**Historial de arranques.** Un JSONL en `~/.portmaster/` con proyecto, perfil,
duración por servicio y causa del fallo contestaría "por qué falló ayer" y
"esto siempre tarda 40 segundos". Sigue sin nadie preguntando eso. Vuelve a la
mesa si la detección de más ecosistemas trae usuarios que comparan arranques.

**Distribución.** No hay workflow de release ni CHANGELOG, y la versión es
0.1.0. El README recomienda `uv tool install portmaster`: publicar hoy depende
de una mano que nadie más puede repetir.

## Fuera de alcance

Lo mismo que decidió el plan anterior, y por los mismos motivos: métricas de CPU
por servicio (polling caro por un número con el que nadie decide nada), ícono en
la bandeja (una dependencia nativa por sistema operativo para ahorrar un
`portmaster serve`) y cualquier cosa remota o multiusuario (tres desviaciones
documentadas en `CLAUDE.md` dependen del loopback).

## Cómo retomar

```bash
# Docker Desktop primero, si el proyecto tiene compose
portmaster serve

# la prueba que falta
docker ps          # antes y despues de apretar Apagar
```

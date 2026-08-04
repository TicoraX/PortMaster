# Plan: qué sigue en PortMaster

Fecha: 3 de agosto de 2026. Rama `main`, commit `fb2ccf2`, 142 tests en verde.

Este documento propone el próximo tramo de trabajo. La pregunta que contesta es
"¿qué le falta a PortMaster para que un desarrollador la deje abierta todo el
día?", no "¿qué se puede agregar?".

## Decidido

Después de la revisión que está al final del documento:

**La premisa son las dos cosas, rescate primero.** PortMaster es lo que abrís
cuando algo local no arranca, y también la pestaña que queda abierta. El orden
del trabajo sale de la primera; la segunda no se descarta, se pospone.

**Entra todo el plan menos P2.** Las sesiones que sobreviven al reinicio salen:
la premisa que las sostiene es "reinicio `serve` seguido", que es cierto
mientras se desarrolla PortMaster y no necesariamente para quien lo usa.
Vuelven a la mesa si el dolor aparece usándolo.

**Adelante de todo, los dos bugs que la revisión encontró y quedaron
verificados.** No estaban en ninguna versión del plan y son más grandes que la
mitad de las propuestas:

| # | Qué | Por qué primero |
|---|---|---|
| 0a | `fastapi` y `uvicorn` a dependencia base | Hoy la interfaz no se instala por el camino que el README recomienda |
| 0b | `portmaster down` | Un stack de compose puro deja los contenedores arriba sin forma de bajarlos |

Después: P1, P3, P4, P5, P6, P7, en ese orden.

Los diseños de P3, P4, P6 y P7 se corrigen con lo que encontró la revisión. El
alcance y el orden son los de este documento; lo que cambia es la
implementación, en los puntos donde la escrita estaba comprobadamente rota.

## De dónde partimos

Lo que ya hace, para no volver a proponerlo:

- Arranca un stack en orden topológico, con healthchecks y apagado del árbol.
- Detecta el stack sin `stack.yaml`: compose por contenedor, Django, FastAPI,
  Node en la raíz o en subcarpetas, backend Python en subcarpetas.
- Interfaz local: arrancar, apagar, reiniciar un servicio suelto, logs
  incrementales, abrir en el navegador, registrar y quitar proyectos,
  explorador de carpetas, buscador, paginado, filtro por estado, sección de
  procesos intrusos.
- CLI: `ports`, `free`, `up`, `open`, `add`, `list`, `remove`, `init`, `serve`.

## Criterio

Cada propuesta se justifica por el dolor que saca, no por la funcionalidad que
agrega. Las que están abajo del corte no son malas ideas: son ideas sin dolor
detrás todavía.

Orden por valor sobre esfuerzo. El esfuerzo va en dos escalas: equipo humano y
esta sesión con Claude Code.

---

## P1. `portmaster doctor`

**El dolor.** Algo no arranca y lo único que ves es la última línea del error.
"exit code 1" no dice si falta Docker, si el puerto está tomado, si el lockfile
pide pnpm y no lo tenés, o si el módulo ASGI que se detectó no existe.
Diagnosticar eso hoy son cuatro comandos en cuatro lugares.

**La forma mínima.** Un comando que corra los chequeos que ya sabemos hacer y
los imprima juntos:

| Chequeo | Código que ya existe |
|---|---|
| Qué stack se lee o se detecta | `config.load` / `detect.stack` |
| Qué puertos pide y cuáles están tomados, por quién | `ports.scan` |
| Si el daemon de Docker contesta | `runner.clean_error_message` ya sabe reconocer el error |
| Si el gestor de paquetes del lockfile está instalado | `shutil.which` |
| Si el módulo ASGI detectado existe | `detect._asgi_module` |

Sin flags, sin niveles de verbosidad, sin `--fix`. Imprime y sale con 0 o 1.

**Por qué primero.** Es el mejor valor por línea del lote: todo el código está
escrito y repartido, falta el comando que lo junta. Y es lo que convierte a
PortMaster en la primera cosa que abrís cuando algo falla, en vez de la última.

Esfuerzo: humano ~1 día / CC ~30 min. Riesgo: bajo, no toca nada existente.

## P2. Sesiones que sobreviven al reinicio del servidor

**El dolor.** `sessions` vive en memoria. Reiniciás `portmaster serve` y la
interfaz pierde de vista lo que había arrancado. Para los contenedores da
igual, porque el estado se recalcula sondeando el puerto. Para un `npm run dev`
no: queda vivo, sin logs, sin botón de Apagar, y terminás matándolo a mano.
Que es exactamente lo que la herramienta existe para evitar.

**La forma mínima.** Un `~/.portmaster/sessions.json` que se reescriba cuando
cambia la lista de procesos: por proyecto, el pid del shell, el nombre del
servicio, el puerto y el `create_time`. Al arrancar, releer y adoptar solo los
pids que sigan vivos y cuyo `create_time` coincida, que es la misma verificación
anti-reciclado de pid que ya hace `ports.kill`.

**Techo aceptado.** Los logs anteriores al reinicio no vuelven: el buffer es un
`deque` en memoria y persistirlo es otro problema. Un servicio adoptado se
puede apagar y reiniciar; sus logs empiezan en blanco. Va con su comentario
`ponytail:`.

Esfuerzo: humano ~2 días / CC ~1 h. Riesgo: medio. Toca el ciclo de vida de
`Session`, que es donde ya aparecieron dos bugs de concurrencia.

## P3. Perfiles en los stacks detectados

**El dolor.** Un stack detectado tiene `profiles: {}`: arranca entero o nada.
Si querés tocar el front y la infra ya está levantada de ayer, igual te la
vuelve a levantar.

**La forma mínima.** Dos fuentes, ninguna inventada:

- Los `profiles:` que el propio `compose.yaml` ya declara.
- Un perfil `sin-infra` con todos los servicios que no son contenedores.

El selector de perfil ya está en la UI y el server ya lo consume. Esto es
llenar un diccionario que hoy se devuelve vacío.

Esfuerzo: humano ~1 día / CC ~30 min. Riesgo: bajo.

## P4. Re-sondeo de HTTP desde la vista de estado

**El dolor.** Ya marcado como techo en `runner.speaks_http`. El sondeo es único
y ocurre en el momento en que el servicio queda listo. Un dev server de Next
compila recién en la primera petición: contesta tarde, el sondeo da falso
negativo, y ese proyecto se queda sin botón `Abrir` hasta que lo reinicies.

**La forma mínima.** En `_project_view`, si un servicio está `ready`, tiene
puerto y `http is False`, re-sondear con caché por puerto y una ventana de
varios segundos. El sondeo ya existe y ya es barato; lo único nuevo es la caché
para no pegarle en cada `/api/state`, que corre cada 2.5 segundos.

Esfuerzo: humano ~4 h / CC ~20 min. Riesgo: bajo, pero es trabajo en el camino
caliente del polling y hay que medirlo.

## P5. Congelar a `stack.yaml` desde la interfaz

**El dolor.** `portmaster init` existe, pero solo en la terminal. Ves en la
tarjeta que detectó el puerto equivocado, y para corregirlo tenés que salir de
la interfaz, ir a la carpeta y correr un comando.

**La forma mínima.** Un botón en la tarjeta de un proyecto detectado que llame
al `init` que ya existe, y muestre dónde quedó el archivo. Con confirmación:
escribe en el disco del usuario.

Esfuerzo: humano ~4 h / CC ~20 min. Riesgo: bajo. Es un endpoint de escritura
más, con la cuota `QUOTA_WRITE` que ya está.

## P6. Aviso cuando un servicio se cae solo

**El dolor.** Un servicio que muere cambia un punto de color. Si tenés la
pestaña de fondo, que es donde vive esta herramienta, no te enterás hasta que
el navegador te tira un `ERR_CONNECTION_REFUSED` diez minutos después.

**La forma mínima.** El `title` del documento con un contador cuando hay algo
caído, y la Notification API del navegador, pedida solo cuando el usuario
aprieta un botón que lo diga. Sin dependencias, sin service worker.

Esfuerzo: humano ~1 día / CC ~30 min. Riesgo: bajo.

## P7. Arranque en paralelo por niveles

**El dolor.** Los servicios sin dependencias entre sí se esperan igual, uno
detrás del otro. En un stack de cinco servicios eso es la suma de todos los
healthchecks en vez del más lento.

**La forma mínima.** El orden topológico ya está calculado. Agrupar por nivel
y arrancar cada nivel junto.

**Por qué está último de los que entran.** Es el cambio con más superficie:
un fallo en un nivel tiene que cancelar a sus hermanos, `_cancel` empieza a
tener más de un lector, y los logs de los primeros segundos se entreveran. Los
logs ya van prefijados por servicio, así que se sigue leyendo, pero es una
regresión de legibilidad a cambio de segundos.

Esfuerzo: humano ~2 días / CC ~1 h. Riesgo: alto para lo que devuelve.

---

## Abajo del corte

No entran en este tramo. El motivo, no la promesa.

**Historial de arranques.** Un JSONL en `~/.portmaster/` con proyecto, perfil,
duración por servicio y causa del fallo contestaría "por qué falló ayer" y
"esto siempre tarda 40 segundos". Todavía no hay nadie preguntando eso: la
sesión típica dura lo que dura la sesión. Vuelve a la mesa el día que alguien
quiera comparar dos arranques.

**Autocompletado en el input de ruta.** El explorador ya cubre el caso. Es
comodidad sobre una función que ya funciona.

**Ícono en la bandeja del sistema y arranque con la sesión.** Una dependencia
nativa distinta por sistema operativo, para ahorrar un `portmaster serve`.

**Métricas de CPU y memoria por servicio.** `psutil` ya está y sería fácil.
Nadie va a decidir nada con ese número, y el polling cada 2.5 segundos se
vuelve caro.

**Cualquier cosa remota o multiusuario.** El proyecto es loopback por diseño y
tres de las desviaciones documentadas en `CLAUDE.md` dependen de eso.

---

## Lo que ya está en el árbol sin commitear

Trabajo hecho, verde, sin commit al momento de escribir esto:

- `runner.clean_error_message`: traduce el error del daemon de Docker, el
  puerto ocupado y el permiso denegado a una frase que se entiende.
- `/api/state?status=`: filtro por estado, con su test.
- Tests de paginado atados a `server.PAGE_SIZE` en vez de al número 8.

Entra en el primer commit de este tramo.

---

# GSTACK REVIEW REPORT

Corrida de `/autoplan` del 3 de agosto de 2026. `codex` no está instalado en
esta máquina, así que las cuatro fases corrieron en modo `[subagent-only]`: una
voz independiente por fase, sin contexto de las otras.

## Verificado contra el código

Lo que las voces acusaron y quedó comprobado leyendo los archivos:

| Hallazgo | Dónde | Estado |
|---|---|---|
| La interfaz no se instala por el camino que documenta el README | `pyproject.toml:25`, `cli.py:294` | Confirmado |
| Un stack de compose puro deja los contenedores arriba, sin comando para bajarlos | `cli.py:162` | Confirmado |
| `AGENTS.md` es byte a byte idéntico a `CLAUDE.md` | 3290 bytes ambos | Confirmado |
| `up()` espera a `self.procs[-1]`, que con paralelismo es el servicio equivocado | `runner.py:84` | Confirmado |
| `Proc.popen` es obligatorio y lo desreferencian 7 puntos del ciclo de vida | `runner.py:48` | Confirmado |
| `PAGE_MIN` es código muerto: `render` decide con `data.registered` | `app.js:35` vs `:344` | Confirmado |
| Los `profiles:` de compose excluyen; los de PortMaster incluyen | `config.py:63` vs compose | Confirmado |
| `detect` devuelve `profiles={}` | `detect.py:125` | Confirmado |

## Temas que aparecieron en dos o más fases por separado

Señal alta: ninguna voz vio el informe de las otras.

**T1. P2 está mal dimensionado y hay que rediseñarlo.** CEO e Ingeniería
llegaron por caminos distintos a la misma conclusión, y Diseño enumeró seis
estados sin especificar. Un pid adoptado no tiene `Popen`, y `down()` explota
en el primer adoptado dejando huérfanos a los siguientes, que es exactamente el
bug que P2 venía a arreglar. La forma barata que sí existe: extender la sección
de intrusos, que ya detecta y mata con verificación de `create_time`.

**T2. La semántica de perfiles de compose está invertida.** CEO, Ingeniería y
Diseño. Un mapeo directo arranca servicios que compose deja apagados a
propósito. No era llenar un diccionario.

**T3. P4 sube de prioridad y baja de lugar.** Las tres voces técnicas coinciden
en que es el arreglo más barato con el síntoma más visible, y en que el lugar
propuesto está mal: `_project_view` corre por proyecto y por request, en un
threadpool de 40 tokens compartido con `/down` y `/kill`. Saturarlo deja a la
herramienta sin poder apagar procesos justo cuando algo anda mal.

**T4. La Notification API no entra.** CEO, Diseño e Ingeniería. Contador en el
`title` más favicon dinámico es el 80% del valor sin permisos, sin API y sin la
molestia de una notificación de escritorio cada vez que reiniciás un servicio.

**T5. El arranque en paralelo se va abajo del corte.** Las tres voces técnicas.
Ingeniería enumeró cuatro carreras concretas; CEO señaló que el costo real se
paga en la estabilidad de una suite de 142 tests con procesos reales en tres
sistemas operativos, que es el activo que hace creíble el resto.

**T6. `doctor` no puede nacer solo en el CLI ni imprimir pass/fail.** CEO, DX e
Ingeniería. Necesita módulo propio (`CLAUDE.md` prohíbe lógica nueva en `cli.py`
y `server.py`), una línea de arreglo copiable por chequeo en rojo, modo sin
proyecto, y separación entre error y aviso o el exit code deja de significar
algo.

## Lo que ninguna versión del plan tenía

Dos fallas funcionales verificadas, más grandes que la mitad de las propuestas:

1. `fastapi` y `uvicorn` viven en un extra `web`. Bajo `pipx` o `uv tool`, que
   son los dos métodos que el README recomienda, el comando que sugiere el
   error instala en el intérprete equivocado y `portmaster serve` sigue
   fallando. Cinco de las siete propuestas mejoran una pantalla a la que el
   usuario instalado por el camino recomendado no llega.
2. No existe `portmaster down`. En un proyecto de compose puro todos los
   servicios son `detached`, `up` imprime "nada que seguir" y retorna sin bajar
   nada. `runner.down()` y el `stop:` de cada servicio están escritos y no
   tienen comando que los invoque.

## Registro de decisiones automáticas

| # | Fase | Decisión | Clase | Principio | Motivo |
|---|---|---|---|---|---|
| 1 | CEO | Los dos bugs confirmados encabezan el tramo | Mecánica | Completitud | Son fallas verificadas, no funcionalidades |
| 2 | CEO | `AGENTS.md` pasa a ser un puntero de una línea | Mecánica | DRY | Duplicado byte a byte |
| 3 | CEO | El historial JSONL sigue abajo del corte | Gusto | Simplicidad | Contra la voz CEO: medir sin usuarios mide una intuición |
| 4 | Diseño | `/api/state` ordena por estado antes que alfabético | Gusto | Completitud | Con `PAGE_SIZE = 4` el paginador es la navegación principal |
| 5 | Diseño | Conteos globales por endpoint antes de cualquier aviso de caída | Mecánica | Completitud | Alimentarlo de una lista paginada es una mentira silenciosa |
| 6 | Diseño | P6 queda en `title` y favicon; sin Notification API | Gusto | Explícito | Tres voces, y el 80% del valor sin permisos |
| 7 | Ing. | El re-sondeo va a un hilo de la `Session`, no a `_project_view` | Mecánica | Completitud | El diseño original satura el threadpool |
| 8 | Ing. | Refactor previo: `_start` devuelve el `Proc`, color pre-asignado | Mecánica | Explícito | Bug latente verificado, barato y aislado |
| 9 | Ing. | `doctor` nace en `portmaster/doctor.py` | Mecánica | Regla del repo | `CLAUDE.md` prohíbe lógica nueva en `cli.py` |
| 10 | Ing. | P3 entra con la semántica corregida y test por caso | Mecánica | Completitud | El mapeo directo es un bug, no una simplificación |
| 11 | DX | `doctor` con línea de arreglo por chequeo y modo sin proyecto | Mecánica | Completitud | Un pass/fail no ahorra ningún comando |
| 12 | CEO | P7 abajo del corte | Mecánica | Pragmatismo | Tres voces, y arriesga el CI |

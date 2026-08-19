# Otros comandos

`up`, `serve`, `ports` y `free` están en el [README](../README.md#comandos).
Acá están los cuatro que quedan, con qué revisa cada uno y por qué.

## Bajar lo que sobrevive a la terminal

```bash
portmaster down
portmaster down --profile backend
```

`Ctrl-C` sobre un `portmaster up` apaga a sus hijos, pero un
`docker compose up -d` termina enseguida y deja los contenedores corriendo.
`down` ejecuta el `stop` de cada servicio que lo declara, en orden inverso al
de arranque. Si ningún servicio declara `stop`, lo dice y no hace nada: esos
son hijos de la terminal y ya se fueron con `Ctrl-C`.

## Cambiar de proyecto

```bash
portmaster switch fitness
portmaster switch A:\Proyectos\Fitness    # o la ruta, si hay dos con el mismo nombre
```

Baja los proyectos registrados que declaran alguno de los puertos que este
necesita, y después lo levanta. Solo los que chocan: parar una base de datos que
nadie disputa no ayuda a arrancar y es lo que más cuesta volver a levantar.

Baja lo que declara `stop`, o sea contenedores. Un `npm run dev` de otra
terminal no es hijo de nadie que PortMaster controle, así que si sigue ocupando
el puerto lo agarra el paso de liberación de `up`, que pregunta antes de cerrar
nada.

## Diagnóstico

```bash
portmaster doctor
```

Revisa, sin arrancar nada, lo que suele impedir un arranque: qué stack se lee o
se detecta, si cada comando existe en el `PATH`, si el daemon de Docker
contesta, y qué puertos declarados están ocupados y por quién. Cada chequeo en
rojo trae la línea para arreglarlo.

```
ok    token                  C:\Users\vos\.portmaster\token
ok    stack                  detectado (3 servicios)
ok    comando docker         C:\Program Files\Docker\...\docker.EXE
FALLA daemon de docker       no esta en ejecucion
                             -> abri Docker Desktop
aviso puerto 3000            ocupado por node.exe (pid 24180), lo pide web
                             -> portmaster free 3000
```

Si hay un `.env.example`, compara sus claves contra el `.env` y avisa cuáles
faltan o quedaron sin valor. Nombres de claves nada más: los valores no salen
ni por la terminal ni por la API.

Sale con 1 solo si algo impide arrancar. Un puerto ocupado es aviso, porque
`portmaster up` ofrece liberarlo, y una clave que falta también, porque puede
ser opcional o venir del entorno. Fuera de un proyecto revisa nada más el
entorno, que es lo que uno quiere recién instalado.

## Abrir el stack en el navegador

```bash
portmaster open         # el ultimo servicio del stack que conteste HTTP
portmaster open 3000    # o el puerto que le pases
```

Sirve cuando el stack ya está corriendo en otra terminal. Recorre los puertos
en orden inverso al de arranque, porque lo que uno quiere mirar suele ser el
frontend, y abre el primero que contesta. Una base de datos no contesta HTTP,
así que nunca es el elegido.

## Ejecutar scripts y pipelines de tareas

```bash
portmaster run              # lista las tareas declaradas en stack.yaml
portmaster run test         # ejecuta una tarea específica
portmaster run test -k foo  # pasa argumentos adicionales al comando
portmaster run check        # ejecuta un pipeline secuencial de scripts
```

Permite definir scripts del proyecto en `stack.yaml` (ej. tests, linters, migraciones, seeders)
y ejecutarlos con el contexto completo de variables de entorno inyectadas (`.env`, `env.global`, etc.).
Si un paso del pipeline falla, la ejecución se detiene inmediatamente con el código de error correspondiente.

## Compartir servicios vía túneles públicos

```bash
portmaster share               # expone el servicio web principal
portmaster share 3000          # expone un puerto específico
portmaster share api           # expone el servicio por nombre
portmaster share --provider ngrok  # fuerza el proveedor (cloudflared, ngrok, lt, tailscale)
```

Genera un túnel HTTPS seguro y efímero hacia el puerto local, ideal para probar webhooks,
compartir vistas previas con clientes o probar en dispositivos móviles. Presioná `Ctrl-C` para
cerrar el túnel de inmediato.

## Limpieza de recursos Docker (Higiene)

```bash
portmaster clean                        # contenedores parados, imagenes sin tag, redes sin usar y cache de build
portmaster clean --solo cache --solo images   # solo esas dos categorias
portmaster clean --volumes              # ademas, volumenes anonimos/huerfanos
```

Limpia **por categorías**, con un comando propio para cada una, no con un
`docker system prune` que las tira todas juntas. No es lo mismo borrar
contenedores parados que caché de build: la caché se regenera sola y las
imágenes sin tag pueden ser la capa base que vas a volver a bajar. Poder
separarlo es el punto.

Los **volúmenes van aparte en todos lados** y nunca entran por defecto: adentro
hay datos y no se regeneran. Hay que pedirlos con `--volumes`; en la interfaz
son una casilla propia, y el servidor MCP directamente los rechaza.

Antes de borrar nada muestra `docker system df` para que veas qué hay en juego,
y pregunta. `--yes` saltea la pregunta, para scripts. Si una categoría falla, las
demás siguen y el resumen dice cuál falló: quedarse a mitad sin decir dónde es
peor que terminar y contarlo.

## Servidor MCP para Agentes de IA

```bash
portmaster mcp
```

Inicia un servidor estándar Model Context Protocol (MCP) sobre `stdio`. Permite que
asistentes inteligentes (Claude Desktop, Cursor, Gemini, Antigravity) inspeccionen el estado
del stack, ejecuten scripts declarados en `stack.yaml`, consulten puertos y diagnostiquen errores
en tiempo real durante sesiones de desarrollo guiado.





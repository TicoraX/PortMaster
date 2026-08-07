# PortMaster

[![tests](https://github.com/TicoraX/PortMaster/actions/workflows/ci.yml/badge.svg)](https://github.com/TicoraX/PortMaster/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Orquestador de entornos de desarrollo locales. Un archivo en la raíz del
proyecto, un comando, y el stack entero arriba: puertos libres, Docker,
backend y frontend, sin cuatro terminales abiertas.

Estado: en construcción, usable. La versión actual levanta un stack completo
desde `stack.yaml`: libera los puertos, arranca en orden de dependencias
(y en paralelo lo que no depende entre sí), espera a que cada servicio esté
listo y unifica los logs.

## Instalación

```bash
uv tool install portmaster
# o
pipx install portmaster
```

Requiere Python 3.10 o superior. Funciona en Windows, macOS y Linux.

## Uso

Levantar el stack entero:

```bash
portmaster up
portmaster up --profile backend    # solo un subconjunto
portmaster up --no-free            # no tocar los puertos ocupados
```

Antes de arrancar libera los puertos declarados que tenga otro proceso, y
pregunta antes de cerrar cada uno. Los que ya publica Docker los saltea: ahí
no hay nada que liberar, el contenedor ya está arriba.

```
demo  stack.yaml
db  | $ docker compose up -d postgres
db  | listo (5432)
api | $ npm run dev
api | escuchando en 8080
api | listo (8080)
web | $ npm run dev
web | listo (3000)
Todo listo. Ctrl-C para apagar.
api | GET /health 200
web | ready in 412 ms
```

Antes de arrancar nada revisa los puertos declarados. Si alguno está tomado
por un proceso huérfano, muestra cuál es y pregunta si cerrarlo. `Ctrl-C`
apaga los servicios en orden inverso, árbol de procesos incluido.

### Sin archivo de configuración

`stack.yaml` es opcional. Si no hay uno, PortMaster mira la raíz del proyecto:

| Encuentra | Arranca |
|---|---|
| `compose.yaml`, `compose.yml`, `docker-compose.yml`, `docker-compose.yaml` | un servicio por contenedor: `docker compose up -d <nombre>` |
| `manage.py` | `python manage.py runserver` |
| `fastapi` o `uvicorn` declarados, con un módulo que defina `app` | `uvicorn <módulo>:app --reload` |
| `package.json` con un script que sirva (`dev`, `start:dev`, `serve`, `start`) | `npm run dev`, con `pnpm`/`yarn`/`bun` según el lockfile o el campo `packageManager` |

```
mi-app  A:\Proyectos\mi-app
Sin stack.yaml. Detectado:
  docker  docker compose up -d        5433
  web     pnpm run dev                al arrancar
Para congelarlo en un archivo editable: portmaster init
Arrancar? [Y/n]
```

Arranca en ese orden y encadena las dependencias: el frontend espera al
backend, el backend a los contenedores.

Si la raíz no tiene `package.json`, busca una vuelta más abajo: `frontend/`,
`web/`, `client/`, `ui/`, `front/`, `site/`, y los hijos de `apps/`,
`packages/` y `services/`. Cada app encontrada es un servicio con el nombre de
su carpeta. Si la raíz sí tiene `package.json`, gana ese y no se baja: en un
monorepo su script `dev` suele ser el orquestador (turbo, nx) y arrancar además
los hijos duplicaría todo.

El backend sigue la misma regla, en `backend/`, `api/`, `server/` y los hijos de
los mismos grupos. Reconoce Django (`manage.py`), FastAPI (`uvicorn` con un
módulo ASGI), Go (`go.mod` con un paquete `main`), Rust (`Cargo.toml` con
`src/main.rs`), Rails (`config/application.rb`), Laravel (`artisan`) y ASP.NET
Core (un `.csproj` con `Sdk="Microsoft.NET.Sdk.Web"`).

En Rust hace falta un framework declarado en el `Cargo.toml`: axum, actix-web,
rocket y compañía. No hay servidor HTTP en la stdlib, así que sin uno el binario
no sirve nada por un puerto. En Go no alcanza con eso, porque `net/http` es
stdlib y un servidor escrito con ella no deja rastro en `go.mod`: se busca
además la llamada a `ListenAndServe` en el fuente. Un binario que no sirve nada
no se detecta, porque arrancarlo dejaría al stack esperando un puerto que nunca
abre.

Rails y Laravel no tienen ese problema: `config/application.rb` y `artisan` solo
existen en aplicaciones que sirven, y un `Gemfile` o un `composer.json` sueltos
no alcanzan. Rails arranca con `bundle exec rails server` y no con el binstub
`bin/rails`, que es un script con shebang y en Windows no lo ejecuta nadie.

En .NET la señal está en el atributo `Sdk` del `.csproj` y en ningún otro lado:
una librería y una app de consola usan `Microsoft.NET.Sdk` a secas, y ni el
nombre del proyecto ni sus paquetes distinguen una cosa de la otra.

En las subcarpetas hace falta además una dependencia que declare un servidor de
desarrollo (vite, next, nest, astro, nodemon y compañía). Un workspace tiene
tantas librerías como apps, y una librería con `dev: tsc --watch` entraría como
servicio y se quedaría esperando un puerto que nunca abre.

Nada de esto es recursivo: un scan profundo termina dentro de `node_modules`.

Un compose no entra como un bloque único: cada contenedor es un servicio con su
puerto publicado, su estado y su link, y el orden sale del `depends_on` del
propio archivo. `docker compose up -d <nombre>` arranca ese contenedor con sus
dependencias y es idempotente. Los puertos escritos como `${WEB_PORT:-8080}` se
resuelven con el entorno, con el `.env` del proyecto y por último con el default
de la expresión, el mismo orden que usa compose.

El puerto de `npm run dev` y de `uvicorn` no se adivina: se arranca el proceso y
se le pregunta cuál quedó escuchando. Es más confiable que parsear
`vite.config.ts`, los flags del script y `.env`, y acierta cuando Vite encuentra
5173 tomado y se corre a 5174. El costo es que esos puertos no se pueden liberar
antes de arrancar, porque no se saben hasta después. Los de compose sí, que
están declarados en el archivo.

`portmaster init` escribe lo detectado como `stack.yaml` para editarlo a mano.
No sobreescribe uno existente.

### Bajar lo que sobrevive a la terminal

```bash
portmaster down
portmaster down --profile backend
```

`Ctrl-C` sobre un `portmaster up` apaga a sus hijos, pero un
`docker compose up -d` termina enseguida y deja los contenedores corriendo.
`down` ejecuta el `stop` de cada servicio que lo declara, en orden inverso al
de arranque. Si ningún servicio declara `stop`, lo dice y no hace nada: esos
son hijos de la terminal y ya se fueron con `Ctrl-C`.

### Cambiar de proyecto

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

### Diagnóstico

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

Sale con 1 solo si algo impide arrancar. Un puerto ocupado es aviso, porque
`portmaster up` ofrece liberarlo. Fuera de un proyecto revisa nada más el
entorno, que es lo que uno quiere recién instalado.

### Abrir el stack en el navegador

```bash
portmaster open         # el ultimo servicio del stack que conteste HTTP
portmaster open 3000    # o el puerto que le pases
```

Sirve cuando el stack ya está corriendo en otra terminal. Recorre los puertos
en orden inverso al de arranque, porque lo que uno quiere mirar suele ser el
frontend, y abre el primero que contesta. Una base de datos no contesta HTTP,
así que nunca es el elegido.

### Interfaz web

Cuando tenés varios proyectos, el CLI se queda corto: trabaja sobre el
directorio actual. La interfaz los muestra todos a la vez.

```bash
portmaster serve        # abre http://127.0.0.1:7666
```

Viene con la instalación, no hace falta nada más. Registrar proyectos se puede
desde la propia interfaz con `Explorar…`, o desde la terminal:

```bash
portmaster add .        # registrar el proyecto actual
portmaster list         # listar proyectos registrados (alias: portmaster ls)
portmaster remove .     # des-registrar un proyecto (alias: portmaster rm)
```

Estado de cada servicio, arrancar y apagar stacks, liberar puertos tomados por
procesos ajenos, y logs en vivo por proyecto.

Cuando un servicio se muere solo, el título de la pestaña lleva un contador y
el encabezado dice cuántos hay caídos. Con `Avisarme` podés además pedir
notificaciones del navegador, que solo avisan de caídas nuevas y nunca de un
`Apagar` ni de un `Reiniciar`. El permiso se pide con ese click y nunca al
cargar la página.

Un proyecto detectado trae `Congelar a stack.yaml`, que es `portmaster init`
sin salir de la interfaz: útil cuando ves en la tarjeta que detectó un puerto
que no era. Pide confirmación sobre el mismo botón, escribe la ruta del
registro y nunca una que venga del navegador, y no sobreescribe un archivo
existente.

Cada servicio arrancado desde la interfaz trae un `Reiniciar` propio, que baja y
sube ese solo. Cuando el frontend se cuelga, los contenedores que estaban bien
no tienen por qué pagarlo.

Los servicios que se pueden abrir en el navegador traen un botón `Abrir`, y la
tarjeta del proyecto trae el suyo, que lleva al último de la lista que conteste,
para no buscar cuál de los tres es el frontend. Cuál lo lleva no se adivina por
el nombre: cuando el servicio queda listo, PortMaster le hace una petición al
puerto. Si contesta HTTP, es abrible. Un `404` cuenta,
porque la mayoría de las APIs no sirven nada en la raíz; lo que descarta al
servicio es que no conteste, que es el caso de una base de datos.

Para registrar un proyecto no hace falta copiar la ruta: `Explorar…` abre un
navegador de carpetas que empieza en tu home y en las unidades montadas, y marca
las que tienen `stack.yaml`, un compose, un `package.json` o un `manage.py`. El
listado lo arma el servidor, porque una página web no puede conocer rutas
absolutas de tu disco. Devuelve nombres de carpetas y de esos archivos
marcadores, nunca contenido.

El servidor escucha solo en loopback y exige un token que `serve` genera en
`~/.portmaster/token` y pasa en la URL de arranque. Ejecuta los comandos de tus
`stack.yaml`, así que se trata como superficie sensible: rate limit en todas las
rutas, CSP estricta, y validación del header `Host` contra rebinding de DNS.
Podés fijar el token vos mismo con `PORTMASTER_TOKEN`.

### Puertos

Revisar el estado de los puertos sin arrancar nada:

```bash
portmaster ports              # los declarados en stack.yaml
portmaster ports 3000 8080    # o los que le pases
```

```
PUERTO  ESTADO   PID    PROCESO   COMANDO
3000    ocupado  24188  node.exe  node C:\proj\frontend\node_modules\.bin\vite
8080    libre    -      -         -
5432    ocupado  9012   com.docker.backend.exe
```

Liberar un puerto tomado por un proceso zombie:

```bash
portmaster free 3000
```

Muestra qué proceso lo ocupa y pide confirmación antes de cerrarlo. Si decís
que no, sugiere el siguiente puerto disponible.

Opciones: `--yes` salta la confirmación (para scripts), `--force` aplica
`kill()` cuando el proceso ignora la señal de terminación.

## Qué no hace el kill switch

Estas reglas están en el código, no en la documentación:

- Nunca cierra PID 0, PID 4, el propio PortMaster ni un proceso padre suyo.
  Matar tu propia terminal no es una función.
- Revalida la hora de creación del proceso entre el escaneo y el cierre. Los
  PID se reciclan; sin ese chequeo terminás matando algo al azar.
- Manda `terminate()` y espera 5 segundos. `kill()` solo con `--force`
  explícito, porque un `npm run dev` matado a lo bruto deja hijos huérfanos.
- Sin permisos, lo dice y corta. No reintenta escalando privilegios.
- Nunca cierra el proxy de Docker o de WSL. Un puerto publicado por un
  contenedor no lo escucha el contenedor: lo escucha un proceso compartido por
  todos, y cerrarlo apaga el motor entero. En vez de eso te dice qué contenedor
  parar.

## Configuración

`stack.yaml` en la raíz del proyecto. PortMaster lo busca hacia arriba, así
que podés correr los comandos desde cualquier subdirectorio.

```yaml
name: mi-proyecto

services:
  db:
    command: docker compose up -d postgres
    port: 5432
    detached: true       # el comando termina, el servicio sigue vivo

  api:
    command: npm run dev
    cwd: backend
    port: 8080
    needs: [db]
    env:
      DATABASE_URL: postgres://localhost:5432/app

  web:
    command: npm run dev
    cwd: frontend
    port: 3000
    needs: [api]

profiles:
  backend: [api]         # arrastra db, que es su dependencia
```

`command` es el único campo obligatorio. `needs` define el orden de arranque
y los ciclos fallan al cargar el archivo, no a mitad del arranque. Un perfil
arrastra sus dependencias transitivas: pedir `api` sin su base de datos nunca
es lo que alguien quiso decir.

Los servicios que no dependen entre sí arrancan juntos, y cada tanda espera a
estar lista antes de la siguiente. El stack tarda el healthcheck más lento de
cada nivel en lugar de la suma de todos, a cambio de que los logs de los
primeros segundos se entreveren. Van prefijados por servicio y con un color
propio cada uno, así que se siguen leyendo.

`default` es opcional y lista qué arranca cuando no pedís perfil. Sin él,
arranca todo, que es lo que casi siempre querés. Existe para el caso de abajo.

### Perfiles de un compose detectado

Un `compose.yaml` con `profiles:` los trae puestos:

```yaml
services:
  db: { image: postgres }
  seed:
    image: seed
    profiles: [tools]
```

Ahí `seed` queda afuera del arranque por defecto y entra con
`portmaster up --profile tools`, igual que con `docker compose --profile tools`.
Ojo con la semántica, porque está invertida: en compose `profiles:` **excluye**
un servicio hasta que lo pidas, mientras que en `stack.yaml` un perfil es la
lista de lo que se arranca. `detect` traduce de una a la otra, y por eso
`portmaster init` sobre ese proyecto escribe también un `default`: sin él, el
archivo congelado prendería lo que el compose deja apagado a propósito.

`ready` decide cuándo un servicio cuenta como listo, y acepta cinco formas:

| Valor | Espera a que |
|---|---|
| `port` | el puerto acepte conexiones (default si hay `port`) |
| `listen` | el proceso abra un puerto cualquiera, y lo reporta |
| `log:texto` | ese texto aparezca en la salida del servicio |
| `http://...` | esa URL responda con menos de 400 |
| `none` | nada (default si no hay `port`) |

`listen` es para servicios que eligen su propio puerto. Es incompatible con
`port`: si lo conocés, el healthcheck es `port`.

`stop` es un comando de apagado propio, opcional. Sin él, apagar mata el árbol
de procesos del servicio, que es lo correcto para un `npm run dev` y no alcanza
para un contenedor: `docker compose up -d` termina enseguida y lo que queda
vivo no es hijo nuestro. Los servicios detectados de un compose traen
`stop: docker compose stop <nombre>`. Si el comando falla o tarda más de 90s, se
loguea y el apagado sigue con el resto.

El ejemplo completo y comentado está en
[`stack.example.yaml`](stack.example.yaml).

## Modelo de confianza

`stack.yaml` ejecuta comandos arbitrarios, igual que `package.json` o un
`Makefile`. PortMaster no lo sandboxea: sería teatro. Tratá un `stack.yaml`
de un repo ajeno con el mismo cuidado que sus scripts de build.

Sin `stack.yaml`, los comandos salen de la detección, y `scripts.dev` de un
`package.json` ajeno es igual de arbitrario. Por eso `up` muestra qué va a
ejecutar y pregunta antes, y `-y` es tuyo para saltarlo cuando ya lo leíste.

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"    # .venv\Scripts\pip en Windows
pytest
```

Los tests levantan sockets y procesos reales, sin mocks. Es lo único que
prueba de verdad un módulo cuyo trabajo es hablar con el sistema operativo.

## Licencia

MIT

# PortMaster

[![tests](https://github.com/TicoraX/PortMaster/actions/workflows/ci.yml/badge.svg)](https://github.com/TicoraX/PortMaster/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Orquestador de entornos de desarrollo locales. Un archivo en la raíz del
proyecto, un comando, y el stack entero arriba: puertos libres, Docker,
backend y frontend, sin cuatro terminales abiertas.

Estado: en construcción, usable. La versión actual levanta un stack completo
desde `stack.yaml`: libera los puertos, arranca en orden de dependencias,
espera a que cada servicio esté listo y unifica los logs.

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
```

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

`ready` decide cuándo un servicio cuenta como listo, y acepta cuatro formas:

| Valor | Espera a que |
|---|---|
| `port` | el puerto acepte conexiones (default si hay `port`) |
| `log:texto` | ese texto aparezca en la salida del servicio |
| `http://...` | esa URL responda con menos de 400 |
| `none` | nada (default si no hay `port`) |

El ejemplo completo y comentado está en
[`stack.example.yaml`](stack.example.yaml).

## Modelo de confianza

`stack.yaml` ejecuta comandos arbitrarios, igual que `package.json` o un
`Makefile`. PortMaster no lo sandboxea: sería teatro. Tratá un `stack.yaml`
de un repo ajeno con el mismo cuidado que sus scripts de build.

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

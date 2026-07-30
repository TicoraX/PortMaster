# PortMaster

Orquestador de entornos de desarrollo locales. Un archivo en la raíz del
proyecto, un comando, y el stack entero arriba: puertos libres, Docker,
backend y frontend, sin cuatro terminales abiertas.

Estado: en construcción. La versión actual (0.1.0) implementa el motor de
puertos. El orquestador y el dashboard vienen después.

## Instalación

```bash
uv tool install portmaster
# o
pipx install portmaster
```

Requiere Python 3.10 o superior. Funciona en Windows, macOS y Linux.

## Uso

Revisar el estado de los puertos que usa tu proyecto:

```bash
portmaster ports 3000 8080 5432
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

## Configuración (diseñada, todavía no implementada)

`stack.yaml` en la raíz del proyecto declara los servicios, sus puertos y el
orden de arranque. El esquema completo y comentado está en
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

"""Arranque y reinicio de Docker Desktop, a pedido del usuario.

Vive fuera de `doctor` a proposito: ese modulo diagnostica sin arrancar nada, y
lo dice en su primera linea. Aca no hay chequeos; el "esta apagado" sigue
saliendo de `doctor._docker`, que es quien ya lo sabe.
"""

from __future__ import annotations

import subprocess

# El plugin del CLI y no el ejecutable. `docker` ya es una dependencia del
# proyecto y ya tiene que estar en el PATH para que un stack con compose sirva
# de algo; el ejecutable de Docker Desktop no esta en el PATH en ninguna
# plataforma, vive en una ruta distinta por sistema operativo, y en Windows
# lanzarlo con `start` lo hace buscar tambien en el directorio actual, que es
# el del proyecto que estes mirando.
#
# `--detach` porque sin el, el comando espera a que el motor termine: entre 30 y
# 60 segundos con un request colgado en el threadpool que FastAPI comparte con
# apagar y con matar procesos. Ver server._probe_late_http, que existe por haber
# aprendido eso mismo.
#
# Diccionario y no un string armado con lo que llegue: lo unico que puede pedir
# la red es una de estas dos claves, y el comando sale de aca.
ACTIONS = {
    "start": ("docker", "desktop", "start", "--detach"),
    "restart": ("docker", "desktop", "restart", "--detach"),
}
TIMEOUT = 10.0

HECHO = {
    "start": "Docker Desktop esta arrancando",
    "restart": "Docker Desktop se esta reiniciando",
}


def run(action: str) -> tuple[bool, str]:
    """Pide `start` o `restart` de Docker Desktop. Devuelve si se pudo, y que decir.

    Mira el resultado en vez de disparar y olvidarse. Un lanzamiento que nadie
    espera contesta "listo" siempre, tambien cuando Docker no esta instalado, y
    el usuario se queda mirando una interfaz que le mintio.

    Que el comando haya salido bien no es que el motor este arriba: eso tarda y
    lo reporta la vista de estado, que ya sondea `docker info`.
    """
    command = ACTIONS[action]
    try:
        done = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return False, "docker no esta en el PATH"
    except subprocess.TimeoutExpired:
        return False, f"docker no contesto en {TIMEOUT:.0f}s"
    except OSError as exc:
        return False, f"no se pudo ejecutar docker: {exc}"

    if done.returncode != 0:
        return False, _motivo(done, action)
    return True, HECHO[action]


def _motivo(done: subprocess.CompletedProcess, action: str) -> str:
    """La primera linea util de la salida, o el codigo si no dijo nada.

    Docker Desktop para Linux no trae el plugin `desktop`, y ahi el error es
    'docker: desktop is not a docker command'. Decirlo tal cual es mas util que
    un "no se pudo" que obliga a ir a buscar por que.
    """
    for stream in (done.stderr, done.stdout):
        primera = next((line.strip() for line in (stream or "").splitlines() if line.strip()), "")
        if primera:
            return primera[:200]
    return f"docker desktop {action} fallo con codigo {done.returncode}"


def usage() -> str | None:
    """La tabla de `docker system df`, para que la confirmacion diga cuanto hay.

    Sin parsear: Docker ya la formatea, y sacarle el numero a mano seria atarnos
    a su formato de salida a cambio de nada. None si docker no contesta, y ahi
    la confirmacion sigue sin la tabla en vez de cancelarse.
    """
    try:
        done = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def prune(volumes: bool = False) -> tuple[bool, str]:
    """Ejecuta docker system prune para limpiar recursos huerfanos."""
    cmd = ["docker", "system", "prune", "-f"]
    if volumes:
        cmd.append("--volumes")
    try:
        done = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60.0,
        )
    except FileNotFoundError:
        return False, "docker no esta en el PATH"
    except subprocess.TimeoutExpired:
        return False, "docker system prune excedio el tiempo limite"
    except OSError as exc:
        return False, f"error al ejecutar docker: {exc}"

    if done.returncode != 0:
        return False, _motivo(done, "prune")
    output = (done.stdout or "").strip()
    return True, output or "Recursos de Docker limpiados exitosamente."


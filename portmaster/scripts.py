"""Ejecucion de scripts y tareas del proyecto."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

from rich.console import Console

from . import config
from .config import ConfigError, Stack


def build_script_env(stack: Stack) -> dict[str, str]:
    """Entorno de ejecucion para scripts de proyecto."""
    env = dict(os.environ)
    global_env = Path.home() / ".portmaster" / "env.global"
    if global_env.is_file():
        env.update(config.parse_env_file(global_env))
    local_env = stack.root / ".env"
    if local_env.is_file():
        env.update(config.parse_env_file(local_env))
    env["PYTHONUNBUFFERED"] = "1"
    env["FORCE_COLOR"] = "1"
    return env


def resolve(stack: Stack, name: str, _visto: tuple[str, ...] = ()) -> list[str]:
    """Aplana un script a comandos de shell, expandiendo los que nombran a otro.

    Un item que coincide con el nombre de otro script es una referencia; todo lo
    demas es un comando literal. Sin esto, el `check: [lint, test]` que documenta
    `docs/stack-yaml.md` corria `lint` como si fuera un binario y moria con "no
    se reconoce como comando".

    Un nombre que no es script queda como comando tal cual, que es lo que hace
    falta para `test: pytest -v`. No se puede distinguir un binario real de una
    referencia mal escrita sin adivinar, y adivinar en un ejecutor de comandos
    sale mas caro que el error del shell.
    """
    if name in _visto:
        raise ConfigError(f"ciclo entre scripts: {' -> '.join((*_visto, name))}")
    fuera: list[str] = []
    for item in stack.scripts[name]:
        if item in stack.scripts:
            fuera.extend(resolve(stack, item, (*_visto, name)))
        else:
            fuera.append(item)
    return fuera


def run_script(
    stack: Stack,
    name: str,
    extra_args: Sequence[str] | None = None,
    console: Console | None = None,
) -> int:
    """Ejecuta una tarea o pipeline de comandos definido en stack.yaml.

    Retorna el codigo de salida del comando (0 si todos terminan con exito).
    """
    console = console or Console()
    if name not in stack.scripts:
        known = ", ".join(stack.scripts) or "ninguno"
        raise ConfigError(f"script desconocido: {name!r}. Definidos: {known}")

    commands = resolve(stack, name)
    env = build_script_env(stack)
    extra_str = (" " + " ".join(extra_args)) if extra_args else ""

    for idx, cmd in enumerate(commands):
        # Si es el ultimo comando del pipeline, le pasamos los extra_args
        full_cmd = (cmd + extra_str) if (idx == len(commands) - 1 and extra_str) else cmd
        console.print(f"[bold cyan]$[/] [dim]{full_cmd}[/]")
        res = subprocess.run(
            full_cmd,
            shell=True,
            cwd=stack.root,
            env=env,
        )
        if res.returncode != 0:
            console.print(
                f"[bold red]error:[/] el script '{name}' fallo en el paso {idx + 1} "
                f"con codigo {res.returncode}"
            )
            return res.returncode

    return 0

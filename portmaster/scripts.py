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

    commands = stack.scripts[name]
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

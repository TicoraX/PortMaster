"""CLI de PortMaster. Fase 1: solo gestion de puertos."""

from __future__ import annotations

import typer
import psutil
from rich.console import Console
from rich.table import Table

from . import __version__, ports

app = typer.Typer(
    help="Orquestador de entornos de desarrollo locales.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)

PortArg = typer.Argument(..., min=1, max=65535)


def _row(status: ports.PortStatus, cmd_width: int) -> tuple[str, ...]:
    if status.free:
        return (str(status.port), "[green]libre[/]", "-", "-", "-")
    if status.owner_unknown:
        return (str(status.port), "[red]ocupado[/]", "?", "[dim]sin permisos[/]", "-")
    cmd = status.cmdline or "-"
    if len(cmd) > cmd_width:
        cmd = cmd[: cmd_width - 1] + "…"
    return (str(status.port), "[red]ocupado[/]", str(status.pid), status.name or "?", cmd)


@app.command("ports")
def ports_cmd(port: list[int] = PortArg) -> None:
    """Revisa el estado de uno o mas puertos."""
    table = Table(box=None, pad_edge=False)
    for column in ("PUERTO", "ESTADO", "PID", "PROCESO", "COMANDO"):
        table.add_column(column)
    # Presupuesto para el comando: lo que sobra tras las cuatro columnas fijas.
    cmd_width = max(20, console.width - 34)
    for value in port:
        table.add_row(*_row(ports.scan(value), cmd_width))
    console.print(table)


@app.command("free")
def free_cmd(
    port: int = PortArg,
    yes: bool = typer.Option(False, "--yes", "-y", help="No preguntar antes de matar."),
    force: bool = typer.Option(False, "--force", help="kill() si ignora terminate()."),
) -> None:
    """Libera un puerto ocupado, o sugiere el siguiente disponible."""
    status = ports.scan(port)

    if status.free:
        console.print(f"Puerto {port} [green]libre[/].")
        return

    if status.owner_unknown:
        err.print(
            f"Puerto {port} ocupado, pero el proceso no es visible con estos "
            "permisos. Proba desde una terminal con privilegios."
        )
        raise typer.Exit(1)

    console.print(f"Puerto {port} ocupado por PID {status.pid} ([bold]{status.name}[/])")
    if status.cmdline:
        console.print(f"  [dim]{status.cmdline}[/]")

    if not yes and not typer.confirm(f"Cerrar el PID {status.pid}?"):
        console.print(f"Siguiente puerto libre: [bold]{ports.next_free(port)}[/]")
        return

    try:
        ports.kill(status.pid, status.create_time, force=force)
    except ports.KillRefused as exc:
        err.print(f"Rechazado: {exc}")
        raise typer.Exit(1)
    except psutil.NoSuchProcess:
        console.print(f"El PID {status.pid} ya no existe. Puerto {port} libre.")
        return
    except psutil.AccessDenied:
        err.print(
            f"Sin permisos para cerrar el PID {status.pid}. "
            "Proba desde una terminal con privilegios."
        )
        raise typer.Exit(1)

    console.print(f"PID {status.pid} cerrado. Puerto {port} [green]libre[/].")


@app.command("version")
def version_cmd() -> None:
    """Muestra la version instalada."""
    console.print(__version__)

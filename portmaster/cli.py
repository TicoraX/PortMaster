"""CLI de PortMaster."""

from __future__ import annotations

import typer
import psutil
from rich.console import Console
from rich.table import Table

from . import __version__, config, ports, runner

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
def ports_cmd(
    port: list[int] = typer.Argument(None, min=1, max=65535),
) -> None:
    """Revisa puertos. Sin argumentos, usa los declarados en stack.yaml."""
    if not port:
        try:
            stack = config.load()
        except config.ConfigError as exc:
            err.print(f"{exc}\nPasa los puertos como argumento: portmaster ports 3000 8080")
            raise typer.Exit(1)
        port = stack.ports()
        if not port:
            err.print(f"{stack.path} no declara ningun puerto.")
            raise typer.Exit(1)

    table = Table(box=None, pad_edge=False)
    for column in ("PUERTO", "ESTADO", "PID", "PROCESO", "COMANDO"):
        table.add_column(column)
    # Presupuesto para el comando: lo que sobra tras las cuatro columnas fijas.
    cmd_width = max(20, console.width - 34)
    for value in port:
        table.add_row(*_row(ports.scan(value), cmd_width))
    console.print(table)


def _release(port: int, yes: bool, force: bool) -> bool:
    """Deja el puerto libre. Devuelve False si sigue ocupado."""
    status = ports.scan(port)
    if status.free:
        return True

    if status.owner_unknown:
        err.print(
            f"Puerto {port} ocupado, pero el proceso no es visible con estos "
            "permisos. Proba desde una terminal con privilegios."
        )
        return False

    console.print(f"Puerto {port} ocupado por PID {status.pid} ([bold]{status.name}[/])")
    if status.cmdline:
        console.print(f"  [dim]{status.cmdline}[/]")

    if not yes and not typer.confirm(f"Cerrar el PID {status.pid}?"):
        return False

    try:
        ports.kill(status.pid, status.create_time, force=force)
    except ports.KillRefused as exc:
        err.print(f"Rechazado: {exc}")
        return False
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        err.print(
            f"Sin permisos para cerrar el PID {status.pid}. "
            "Proba desde una terminal con privilegios."
        )
        return False

    console.print(f"PID {status.pid} cerrado. Puerto {port} [green]libre[/].")
    return True


@app.command("free")
def free_cmd(
    port: int = PortArg,
    yes: bool = typer.Option(False, "--yes", "-y", help="No preguntar antes de matar."),
    force: bool = typer.Option(False, "--force", help="kill() si ignora terminate()."),
) -> None:
    """Libera un puerto ocupado, o sugiere el siguiente disponible."""
    if ports.is_free(port):
        console.print(f"Puerto {port} [green]libre[/].")
        return
    if not _release(port, yes, force):
        console.print(f"Siguiente puerto libre: [bold]{ports.next_free(port)}[/]")


@app.command("up")
def up_cmd(
    profile: str = typer.Option(None, "--profile", "-p", help="Perfil de stack.yaml."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Liberar puertos sin preguntar."),
    force: bool = typer.Option(False, "--force", help="kill() si ignora terminate()."),
    timeout: float = typer.Option(60.0, help="Segundos de espera por servicio."),
) -> None:
    """Levanta el stack: libera puertos, arranca en orden y sigue los logs."""
    try:
        stack = config.load()
        services = stack.resolve(profile)
    except config.ConfigError as exc:
        err.print(str(exc))
        raise typer.Exit(1)

    console.print(f"[bold]{stack.name}[/] [dim]{stack.path}[/]")

    for service in services:
        if service.port and not _release(service.port, yes, force):
            err.print(f"Puerto {service.port} sigue ocupado ({service.name}). Cancelado.")
            raise typer.Exit(1)

    engine = runner.Runner(stack, console=console, timeout=timeout)
    try:
        engine.up(profile)
    except runner.StartupError as exc:
        err.print(f"Fallo el arranque: {exc}")
        raise typer.Exit(1)

    if all(p.service.detached for p in engine.procs):
        console.print("[green]Todo listo.[/] Servicios detached, nada que seguir.")
        return

    console.print("[green]Todo listo.[/] Ctrl-C para apagar.")
    try:
        engine.follow()
    except KeyboardInterrupt:
        console.print()
    finally:
        engine.down()


@app.command("version")
def version_cmd() -> None:
    """Muestra la version instalada."""
    console.print(__version__)

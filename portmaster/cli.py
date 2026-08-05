"""CLI de PortMaster."""

from __future__ import annotations

from pathlib import Path
import json

import typer
import psutil
from rich.console import Console
from rich.table import Table

from . import __version__, config, detect, doctor, ports, registry, runner

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
    """Revisa puertos. Sin argumentos, usa los del stack (declarados o detectados)."""
    if not port:
        try:
            stack = detect.stack_for(Path.cwd())
        except config.ConfigError as exc:
            err.print(f"{exc}\nPasa los puertos como argumento: portmaster ports 3000 8080")
            raise typer.Exit(1)
        port = stack.ports()
        if not port:
            err.print(
                f"{stack.path} no declara ningun puerto. Los servicios con "
                "'ready: listen' recien lo tienen cuando arrancan."
            )
            raise typer.Exit(1)

    table = Table(box=None, pad_edge=False)
    for column in ("PUERTO", "ESTADO", "PID", "PROCESO", "COMANDO"):
        table.add_column(column)
    # Presupuesto para el comando: lo que sobra tras las cuatro columnas fijas.
    cmd_width = max(20, console.width - 34)
    scanned = ports.scan_many(port)
    for value in port:
        table.add_row(*_row(scanned[value], cmd_width))
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


def _confirm_detected(services: list[config.Service], yes: bool) -> bool:
    """Muestra lo detectado y pide confirmacion: nadie quiere arrancar a ciegas."""
    console.print("[dim]Sin stack.yaml. Detectado:[/]")
    table = Table(box=None, pad_edge=False, show_header=False)
    for service in services:
        port = str(service.port) if service.port else "[dim]al arrancar[/]"
        table.add_row(f"  [bold]{service.name}[/]", service.command, port)
    console.print(table)
    console.print("[dim]Para congelarlo en un archivo editable: portmaster init[/]")
    return yes or typer.confirm("Arrancar?", default=True)


@app.command("up")
def up_cmd(
    profile: str = typer.Option(None, "--profile", "-p", help="Perfil de stack.yaml."),
    yes: bool = typer.Option(False, "--yes", "-y", help="No preguntar nada, arrancar."),
    force: bool = typer.Option(False, "--force", help="kill() si ignora terminate()."),
    timeout: float = typer.Option(60.0, help="Segundos de espera por servicio."),
) -> None:
    """Levanta el stack: libera puertos, arranca en orden y sigue los logs."""
    try:
        stack = detect.stack_for(Path.cwd())
        services = stack.resolve(profile)
    except config.ConfigError as exc:
        err.print(str(exc))
        raise typer.Exit(1)

    console.print(f"[bold]{stack.name}[/] [dim]{stack.path}[/]")

    if stack.detected and not _confirm_detected(services, yes):
        raise typer.Exit(1)

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
        console.print(
            "[green]Todo listo.[/] Servicios detached, nada que seguir. "
            "Para bajarlos: [bold]portmaster down[/]"
        )
        return

    console.print("[green]Todo listo.[/] Ctrl-C para apagar.")
    try:
        engine.follow()
    except KeyboardInterrupt:
        console.print()
    finally:
        engine.down()


MARCA = {"ok": "[green]ok   [/]", "warn": "[yellow]aviso[/]", "fail": "[red]FALLA[/]"}


@app.command("doctor")
def doctor_cmd() -> None:
    """Revisa que puede impedir el arranque, sin arrancar nada."""
    checks = doctor.run(Path.cwd())

    ancho = max(len(c.name) for c in checks)
    for check in checks:
        # Sin `highlight`: rich le pone color a los numeros y a las rutas, y
        # esta salida es para copiar y pegar, no para mirar.
        console.print(
            f"{MARCA[check.level]} {check.name.ljust(ancho)}  {check.detail}", highlight=False
        )
        if check.fix and check.level != "ok":
            console.print(f"{' ' * (ancho + 8)}[dim]-> {check.fix}[/]", highlight=False)

    if doctor.blocking(checks):
        raise typer.Exit(1)


@app.command("down")
def down_cmd(
    profile: str = typer.Option(None, "--profile", "-p", help="Perfil de stack.yaml."),
) -> None:
    """Apaga lo que sobrevive a la terminal: contenedores y demas servicios detached."""
    try:
        stack = detect.stack_for(Path.cwd())
        services = stack.resolve(profile)
    except config.ConfigError as exc:
        err.print(str(exc))
        raise typer.Exit(1)

    console.print(f"[bold]{stack.name}[/] [dim]{stack.path}[/]")

    # En orden inverso al de arranque, igual que `Runner.down`: lo que depende
    # de algo se baja antes que aquello de lo que depende.
    apagables = [s for s in reversed(services) if s.stop]
    if not apagables:
        console.print(
            "Ningun servicio declara [bold]stop[/]. Los que arranca "
            "[bold]portmaster up[/] son hijos de esa terminal y se apagan con Ctrl-C."
        )
        return

    fallaron = 0
    for service in apagables:
        console.print(f"[dim]{service.name} | $ {service.stop}[/]")
        done = runner.run_stop(service)
        if done is None:
            err.print(f"{service.name}: el apagado no termino en {runner.STOP_TIMEOUT}s")
            fallaron += 1
            continue
        for line in (done.stdout or "").splitlines():
            console.print(f"[dim]{service.name} |[/] {line.rstrip()}")
        if done.returncode != 0:
            err.print(f"{service.name}: el apagado fallo con codigo {done.returncode}")
            fallaron += 1

    if fallaron:
        raise typer.Exit(1)
    console.print("[green]Apagado.[/]")


@app.command("open")
def open_cmd(
    port: int = typer.Argument(None, min=1, max=65535, help="Puerto, si ya lo sabes."),
) -> None:
    """Abre en el navegador el primer servicio del stack que conteste HTTP."""
    if port is None:
        try:
            stack = detect.stack_for(Path.cwd())
        except config.ConfigError as exc:
            err.print(f"{exc}\nPasa el puerto como argumento: portmaster open 3000")
            raise typer.Exit(1)
        # En orden de arranque: los contenedores primero, el frontend al final.
        # Se recorre al reves porque lo que uno quiere abrir suele ser lo ultimo.
        candidates = [s.port for s in reversed(stack.resolve()) if s.port]
    else:
        candidates = [port]

    for candidate in candidates:
        if runner.speaks_http(candidate):
            url = f"http://localhost:{candidate}"
            console.print(f"Abriendo [bold]{url}[/]")
            import webbrowser

            webbrowser.open(url)
            return

    err.print(
        "Ningun puerto del stack contesta HTTP. "
        "Arrancalo con 'portmaster up' o pasa el puerto como argumento."
    )
    raise typer.Exit(1)


@app.command("add")
def add_cmd(
    path: str = typer.Argument(".", help="Directorio del proyecto."),
) -> None:
    """Registra un proyecto para que aparezca en la interfaz."""
    try:
        registered = registry.add(path)
    except registry.RegistryError as exc:
        err.print(str(exc))
        raise typer.Exit(1)
    console.print(f"Registrado: [bold]{registered}[/]")


@app.command("list")
@app.command("ls")
def list_cmd() -> None:
    """Lista los proyectos registrados para la interfaz web."""
    items = registry.paths()
    if not items:
        console.print("[dim]No hay proyectos registrados. Registra uno con: portmaster add <ruta>[/]")
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("ID")
    table.add_column("NOMBRE")
    table.add_column("RUTA")
    for path in items:
        pid = registry.project_id(path)
        table.add_row(pid, path.name, str(path))
    console.print(table)


@app.command("remove")
@app.command("rm")
def remove_cmd(
    target: str = typer.Argument(..., help="Ruta o ID del proyecto a des-registrar."),
) -> None:
    """Des-registra un proyecto de la interfaz."""
    pids = {registry.project_id(p): p for p in registry.paths()}
    if target in pids:
        pid = target
        path = pids[pid]
    else:
        resolved = Path(target).expanduser().resolve()
        pid = registry.project_id(resolved)
        path = resolved

    if registry.remove(pid):
        console.print(f"Quitado: [bold]{path}[/]")
    else:
        err.print(f"El proyecto '{target}' no esta registrado.")
        raise typer.Exit(1)


@app.command("init")
def init_cmd(
    path: str = typer.Argument(".", help="Directorio del proyecto."),
) -> None:
    """Escribe un stack.yaml con lo detectado, para editarlo a mano."""
    root = Path(path).expanduser().resolve()
    try:
        target = detect.freeze(root)
    except config.ConfigError as exc:
        err.print(str(exc))
        raise typer.Exit(1)

    console.print(f"Escrito: [bold]{target}[/]")
    console.print("[dim]Revisalo antes de confiar en el.[/]")


@app.command("export")
def export_cmd(
    out: Path | None = typer.Argument(None, help="Archivo JSON de destino (opcional)."),
) -> None:
    """Exporta las rutas de todos los proyectos registrados en formato JSON."""
    data = registry.export_data()
    text = json.dumps(data, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Exportados {len(data)} proyectos en [bold]{out}[/]")
    else:
        console.print(text)


@app.command("import")
def import_cmd(
    src: Path = typer.Argument(..., help="Archivo JSON con rutas de proyectos."),
) -> None:
    """Importa masivamente proyectos registrados desde un archivo JSON."""
    if not src.is_file():
        err.print(f"El archivo '{src}' no existe.")
        raise typer.Exit(1)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        imported = registry.import_data(data)
        console.print(f"Importados [bold]{len(imported)}[/] proyectos desde [bold]{src}[/]")
    except Exception as exc:
        err.print(f"Error al importar desde '{src}': {exc}")
        raise typer.Exit(1)


@app.command("serve")
def serve_cmd(
    port: int = typer.Option(7666, min=1, max=65535, help="Puerto de la interfaz."),
    no_open: bool = typer.Option(False, "--no-open", help="No abrir el navegador."),
) -> None:
    """Levanta la interfaz web local."""
    try:
        import uvicorn

        from . import server
    except ImportError:
        err.print("Falta el extra web. Instalalo con: pip install 'portmaster[web]'")
        raise typer.Exit(1)

    token = registry.token()
    url = f"http://127.0.0.1:{port}/?token={token}"

    console.print(f"PortMaster en [bold]http://127.0.0.1:{port}[/]")
    console.print("[dim]Solo loopback. El token va en la URL de abajo.[/]")
    console.print(url)

    if not no_open:
        import webbrowser

        webbrowser.open(url)

    try:
        uvicorn.run(server.create_app(token), host="127.0.0.1", port=port, log_level="warning")
    except OSError as exc:
        err.print(f"No se pudo iniciar el servidor en 127.0.0.1:{port}: {exc}")
        err.print(f"El puerto {port} esta ocupado. Podes usar 'portmaster free {port}' o '--port <otro>'.")
        raise typer.Exit(1)


@app.command("version")
def version_cmd() -> None:
    """Muestra la version instalada."""
    console.print(__version__)


if __name__ == "__main__":
    app()

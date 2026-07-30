"""Deteccion de puertos ocupados y cierre seguro del proceso que los usa.

Sin dependencias de terminal a proposito: el CLI y la futura API local
consumen las mismas funciones.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import psutil

# System Idle Process y System en Windows (0, 4), e init/systemd/launchd en POSIX (1). Matarlos no es una opcion.
PROTECTED_PIDS = {0, 1, 4}

TERMINATE_TIMEOUT = 5


class KillRefused(Exception):
    """El proceso existe pero PortMaster se niega a matarlo."""


@dataclass(frozen=True)
class PortStatus:
    port: int
    free: bool
    pid: int | None = None
    name: str | None = None
    cmdline: str | None = None
    create_time: float | None = None

    @property
    def owner_unknown(self) -> bool:
        """Ocupado pero sin permiso para saber por quien."""
        return not self.free and self.pid is None


def _check_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError(f"puerto invalido: {port!r}")
    if not 1 <= port <= 65535:
        raise ValueError(f"puerto fuera de rango 1-65535: {port}")
    return port


def _bind_free(port: int) -> bool:
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    hosts = [("0.0.0.0", socket.AF_INET), ("127.0.0.1", socket.AF_INET)]
    if getattr(socket, "has_ipv6", False):
        hosts.append(("::1", socket.AF_INET6))

    for host, family in hosts:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                if exclusive is not None and family == socket.AF_INET:
                    sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                sock.bind((host, port))
        except OSError:
            return False
    return True


def _pid_by_process_scan(port: int) -> int | None:
    """Barrido proceso por proceso. Solo cuando la tabla no dio el dueno.

    ponytail: O(procesos) y con una llamada al SO por proceso. Corre solo en el
    camino lento, con el puerto ya confirmado ocupado. Si alguna vez pesa, la
    salida es cachear la tabla entre puertos de un mismo escaneo.
    """
    for proc in psutil.process_iter():
        try:
            for conn in proc.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == port:
                    if conn.status == psutil.CONN_LISTEN:
                        return proc.pid
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def is_free(port: int) -> bool:
    """Libre solo si nadie escucha en la tabla y ademas el bind funciona."""
    _check_port(port)
    return port not in _listeners({port}) and _bind_free(port)


def _quiet(getter):
    try:
        return getter()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None


def _describe(port: int, pid: int | None) -> PortStatus:
    if pid is None:
        pid = _pid_by_process_scan(port)
    if pid is None:
        return PortStatus(port=port, free=False)

    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = _quiet(proc.name)
            cmdline = _quiet(lambda: " ".join(proc.cmdline()))
            created = _quiet(proc.create_time)
    except psutil.NoSuchProcess:
        return PortStatus(port=port, free=False)

    return PortStatus(port, False, pid, name, cmdline or None, created)


def scan(port: int) -> PortStatus:
    """Estado del puerto, con el dueno si se puede averiguar."""
    return scan_many([port])[port]


def scan_many(wanted: list[int]) -> dict[int, PortStatus]:
    """Igual que scan(), pero con una sola lectura de la tabla del sistema.

    La UI escanea los puertos de todos los proyectos cada pocos segundos; hacer
    una llamada al SO por puerto se nota.
    """
    for port in wanted:
        _check_port(port)

    listeners = _listeners(set(wanted))
    result = {}
    for port in wanted:
        if port not in listeners and _bind_free(port):
            result[port] = PortStatus(port=port, free=True)
        else:
            result[port] = _describe(port, listeners.get(port))
    return result


def _listeners(wanted: set[int]) -> dict[int, int | None]:
    """Puertos de `wanted` con listener, mapeados a su PID si es visible."""
    found: dict[int, int | None] = {}
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if not conn.laddr or conn.status != psutil.CONN_LISTEN:
                continue
            port = conn.laddr.port
            if port in wanted and (conn.pid or port not in found):
                found[port] = conn.pid
    except (psutil.AccessDenied, PermissionError):
        pass  # macOS sin root: queda todo en manos de la sonda de bind
    return found


def listening(pid: int) -> int | None:
    """Primer puerto en LISTEN del proceso pid o de sus descendientes.

    Para servicios cuyo puerto no esta declarado: en vez de adivinarlo parseando
    la config del framework, se arranca el proceso y se le pregunta. El arbol
    entero porque con shell=True el hijo directo es el shell, y quien escucha es
    un nieto.
    """
    try:
        parent = psutil.Process(pid)
        tree = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return None

    found = []
    for process in tree:
        try:
            for conn in process.net_connections(kind="inet"):
                if conn.status == psutil.CONN_LISTEN and conn.laddr:
                    found.append(conn.laddr.port)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return min(found) if found else None


def next_free(start: int, limit: int = 20) -> int:
    """Primer puerto libre desde start (incluido)."""
    _check_port(start)
    candidates = range(start, min(start + limit, 65536))
    taken = _listeners(set(candidates))
    for port in candidates:
        if port not in taken and _bind_free(port):
            return port
    raise RuntimeError(f"sin puerto libre entre {start} y {start + limit - 1}")


def kill(pid: int, create_time: float | None = None, force: bool = False) -> None:
    """Cierra el proceso pid. terminate() primero, kill() solo con force.

    create_time es el valor visto por scan(); si no coincide, el PID fue
    reciclado por otro proceso y se aborta.

    Lanza KillRefused si el proceso esta protegido, psutil.NoSuchProcess si ya
    no existe, y psutil.AccessDenied si faltan permisos.
    """
    if pid in PROTECTED_PIDS:
        raise KillRefused(f"PID {pid} es un proceso del sistema")

    me = psutil.Process()
    if pid == me.pid:
        raise KillRefused("ese PID es PortMaster")
    if pid in {ancestor.pid for ancestor in me.parents()}:
        raise KillRefused(f"PID {pid} es un proceso padre de PortMaster (tu terminal)")

    proc = psutil.Process(pid)
    if create_time is not None and proc.create_time() != create_time:
        raise KillRefused(f"el PID {pid} ya no es el proceso que se escaneo")

    proc.terminate()
    try:
        proc.wait(TERMINATE_TIMEOUT)
        return
    except psutil.TimeoutExpired:
        pass

    if not force:
        raise KillRefused(
            f"PID {pid} ignoro terminate tras {TERMINATE_TIMEOUT}s; usa --force"
        )
    proc.kill()
    proc.wait(TERMINATE_TIMEOUT)

"""Deteccion de puertos ocupados y cierre seguro del proceso que los usa.

Sin dependencias de terminal a proposito: el CLI y la futura API local
consumen las mismas funciones.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import psutil

# System Idle Process y System en Windows. Matarlos no es una opcion.
PROTECTED_PIDS = {0, 4}

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
    """Sonda de bind en las dos direcciones. Red de seguridad, no fuente de verdad.

    Detecta lo que la tabla del sistema no muestra (macOS sin root), pero por si
    sola miente: en Windows, un dev server que abrio su socket con SO_REUSEADDR
    (http.server, Flask, Vite lo hacen) deja que otro proceso bindee encima y el
    puerto se reporta libre estando ocupado. SO_EXCLUSIVEADDRUSE reduce el caso,
    no lo elimina.
    """
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    for host in ("0.0.0.0", "127.0.0.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if exclusive is not None:
                sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            try:
                sock.bind((host, port))
            except OSError:
                return False
    return True


def _table_lookup(port: int) -> tuple[bool, int | None]:
    """(hay listener en la tabla del sistema, su PID si es visible).

    (False, None) tambien es la respuesta cuando no hay permisos para leer la
    tabla, y por eso el resultado se combina siempre con la sonda de bind.
    """
    try:
        listening = False
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port:
                if conn.status == psutil.CONN_LISTEN:
                    if conn.pid:
                        return True, conn.pid
                    listening = True
        return listening, None
    except (psutil.AccessDenied, PermissionError):
        return False, None  # macOS sin root


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
    listening, _ = _table_lookup(port)
    return not listening and _bind_free(port)


def _quiet(getter):
    try:
        return getter()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None


def scan(port: int) -> PortStatus:
    """Estado del puerto, con el dueno si se puede averiguar."""
    _check_port(port)
    listening, pid = _table_lookup(port)
    if not listening and _bind_free(port):
        return PortStatus(port=port, free=True)

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


def next_free(start: int, limit: int = 20) -> int:
    """Primer puerto libre desde start (incluido)."""
    _check_port(start)
    try:
        taken = {
            conn.laddr.port
            for conn in psutil.net_connections(kind="tcp")
            if conn.laddr and conn.status == psutil.CONN_LISTEN
        }
    except (psutil.AccessDenied, PermissionError):
        taken = set()

    for port in range(start, min(start + limit, 65536)):
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

"""Arranque secuenciado de los servicios de un stack.

Cada servicio corre en su propio proceso; un hilo por servicio bombea su salida
hacia una cola que el hilo principal drena e imprime con prefijo de color.

ponytail: no hay dashboard con `rich.live`. Los logs prefijados son el 90% del
valor y no pelean con el scroll de la terminal. Un panel fijo se agrega si
alguien lo pide con un caso concreto.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field

import psutil
from rich.console import Console

from . import ports
from .config import Service, Stack

COLORS = ("cyan", "magenta", "green", "yellow", "blue", "bright_red")
SHUTDOWN_TIMEOUT = 5
POLL = 0.15

# Un comando detached tiene su propio presupuesto, mucho mas largo que el del
# healthcheck: la primera vez que corre, `docker compose up -d` construye la
# imagen y eso tarda minutos sin que nada este mal.
DETACHED_TIMEOUT = 900

# `docker compose stop` le da su gracia a cada contenedor antes de matarlo, y con
# varios no entra en los 5s del apagado del arbol.
STOP_TIMEOUT = 90


class StartupError(Exception):
    """Un servicio no arranco o no llego a estar listo."""


@dataclass
class Proc:
    service: Service
    popen: subprocess.Popen
    color: str
    ready: bool = False
    matched_log: bool = False
    port: int | None = None  # descubierto, para los servicios con ready: listen
    http: bool = False  # el puerto contesta HTTP, o sea que se puede abrir
    # Ultimas lineas de salida, para que el error diga la causa y no solo el
    # codigo: "fallo con codigo 1" sin el motivo obliga a abrir los logs.
    tail: deque[str] = field(default_factory=lambda: deque(maxlen=5))

    @property
    def known_port(self) -> int | None:
        return self.service.port or self.port


@dataclass
class Runner:
    stack: Stack
    console: Console = field(default_factory=Console)
    timeout: float = 60.0
    procs: list[Proc] = field(default_factory=list)
    _logs: queue.Queue = field(default_factory=queue.Queue)
    _width: int = 8
    _cancel: threading.Event = field(default_factory=threading.Event)
    _down: bool = False
    restarting: bool = False

    def up(self, profile: str | None = None) -> None:
        """Arranca el perfil en orden. Si algo falla, apaga lo ya levantado."""
        services = self.stack.resolve(profile)
        self._width = max(len(s.name) for s in services)
        try:
            for service in services:
                self._abort_if_cancelled()
                self._start(service)
                self._wait_ready(self.procs[-1])
        except BaseException:
            self.down()
            raise

    def cancel(self) -> None:
        """Aborta un arranque en curso desde otro hilo.

        Sin esto, apagar mientras arranca no apaga nada: la lista de procesos
        todavia esta vacia y el arranque sigue levantando servicios detras del
        apagado. El propio `up` es el que baja lo que alcanzo a levantar.

        Tambien corta `follow`, para que el hilo termine y se lo pueda esperar
        sin importar en que fase estaba.
        """
        self._cancel.set()

    def _abort_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise StartupError("apagado pedido durante el arranque")

    def follow(self) -> None:
        """Sigue imprimiendo logs hasta Ctrl-C o hasta que no quede nada vivo."""
        while not self._cancel.is_set() and (
            # Durante un reinicio no queda nadie vivo por un instante, y sin esto
            # el stack se daria por terminado justo ahi.
            self.restarting
            or any(p.popen.poll() is None for p in self.procs)
        ):
            if not self._drain():
                time.sleep(POLL)
        self._drain()

    def restart(self, name: str) -> None:
        """Reinicia un servicio sin tocar el resto del stack."""
        index = next((i for i, p in enumerate(self.procs) if p.service.name == name), None)
        if index is None:
            raise StartupError(f"{name} no esta corriendo en este stack")

        old = self.procs[index]
        self.restarting = True
        try:
            self._stop_one(old)
            proc = self._spawn_proc(old.service, old.color)
            self.procs[index] = proc
        finally:
            self.restarting = False
        self._wait_ready(proc)

    def down(self) -> None:
        """Apaga en orden inverso al de arranque. Correrlo dos veces no hace nada."""
        if self._down:
            return
        self._down = True
        for proc in reversed(self.procs):
            self._stop_one(proc)
        self._drain()

    def _stop_one(self, proc: Proc) -> None:
        if proc.service.stop:
            self._stop_command(proc)
        if proc.popen.poll() is None:
            self._say(proc, "apagando")
            _terminate_tree(proc.popen.pid)

    def _stop_command(self, proc: Proc) -> None:
        """Apagado propio del servicio.

        Matar el arbol no alcanza cuando lo que quedo vivo no es hijo nuestro:
        `docker compose up -d` termina enseguida y los contenedores siguen
        corriendo. Sin este comando, "apagar" no apaga nada.
        """
        self._say(proc, f"$ {proc.service.stop}")
        done = run_stop(proc.service)
        if done is None:
            self._say(proc, f"el apagado no termino en {STOP_TIMEOUT}s")
            return
        for line in (done.stdout or "").splitlines():
            self._write(proc, line.rstrip())
        if done.returncode != 0:
            self._say(proc, f"el apagado fallo con codigo {done.returncode}")

    # arranque -------------------------------------------------------------

    def _start(self, service: Service) -> None:
        color = COLORS[len(self.procs) % len(COLORS)]
        self.procs.append(self._spawn_proc(service, color))

    def _spawn_proc(self, service: Service, color: str) -> Proc:
        proc = Proc(service, self._spawn(service), color)
        self._say(proc, f"$ {service.command}")
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        return proc

    def _spawn(self, service: Service) -> subprocess.Popen:
        # shell=True es deliberado: `npm run dev` y `docker compose up -d` no son
        # ejecutables, y stack.yaml ya es codigo ejecutable por diseño. El README
        # documenta el modelo de confianza.
        env = {
            "PYTHONUNBUFFERED": "1",
            "FORCE_COLOR": "1",
            **os.environ,
            **service.env,
        }
        return subprocess.Popen(
            service.command,
            shell=True,
            cwd=service.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
        )

    def _pump(self, proc: Proc) -> None:
        assert proc.popen.stdout is not None
        for line in proc.popen.stdout:
            self._logs.put((proc, line.rstrip()))
        proc.popen.stdout.close()

    # espera ---------------------------------------------------------------

    def _wait_ready(self, proc: Proc) -> None:
        service = proc.service

        if service.detached:
            self._await_exit(proc)

        deadline = time.monotonic() + self.timeout
        while True:
            self._abort_if_cancelled()
            self._drain()
            if self._is_ready(proc):
                proc.ready = True
                port = proc.known_port
                if port:
                    proc.http = speaks_http(port)
                detail = f" ({port})" if port else ""
                if proc.http:
                    detail += f" · http://localhost:{port}"
                self._say(proc, "listo" + detail)
                return
            if not service.detached and proc.popen.poll() is not None:
                raise StartupError(
                    f"{service.name} termino con codigo {proc.popen.returncode} "
                    f"antes de estar listo{_why(proc)}"
                )
            if time.monotonic() > deadline:
                raise StartupError(
                    f"{service.name} no estuvo listo en {self.timeout:.0f}s "
                    f"(ready: {service.ready}){_why(proc)}"
                )
            time.sleep(POLL)

    def _await_exit(self, proc: Proc) -> None:
        """Un servicio detached corre un comando que termina y deja algo vivo."""
        budget = max(self.timeout, DETACHED_TIMEOUT)
        try:
            code = proc.popen.wait(budget)
        except subprocess.TimeoutExpired:
            raise StartupError(
                f"{proc.service.name} es detached pero no termino en {budget:.0f}s"
            ) from None
        self._drain()
        if code != 0:
            raise StartupError(f"{proc.service.name} fallo con codigo {code}{_why(proc)}")

    def _is_ready(self, proc: Proc) -> bool:
        ready = proc.service.ready
        if ready == "none":
            return True
        if ready == "port":
            return not ports.is_free(proc.service.port)
        if ready == "listen":
            proc.port = ports.listening(proc.popen.pid)
            return proc.port is not None
        if ready.startswith("log:"):
            return proc.matched_log
        return _http_ok(ready)

    # salida ---------------------------------------------------------------

    def _drain(self) -> bool:
        """Imprime lo que haya en la cola. Devuelve si imprimio algo."""
        printed = False
        while True:
            try:
                proc, line = self._logs.get_nowait()
            except queue.Empty:
                return printed
            marker = proc.service.ready
            if marker.startswith("log:") and marker[4:] in line:
                proc.matched_log = True
            proc.tail.append(line)
            self._write(proc, line)
            printed = True

    def _say(self, proc: Proc, message: str) -> None:
        self._write(proc, f"[dim]{message}[/]")

    def _write(self, proc: Proc, text: str) -> None:
        name = proc.service.name.ljust(self._width)
        self.console.print(f"[{proc.color}]{name}[/] [dim]|[/] {text}", highlight=False)


def run_stop(service: Service) -> subprocess.CompletedProcess | None:
    """Corre el `stop:` de un servicio. None si no termino a tiempo.

    Vive afuera del `Runner` porque `portmaster down` tiene que poder apagar un
    stack que arranco otro proceso: los contenedores de un `docker compose up -d`
    sobreviven a la terminal que los levanto, y ahi no hay ningun `Proc` vivo del
    que colgarse.
    """
    assert service.stop
    try:
        return subprocess.run(
            service.stop,
            shell=True,
            cwd=service.cwd,
            env={**os.environ, **service.env},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=STOP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None


WHY_MAX = 200


def clean_error_message(text: str) -> str:
    """Simplifica mensajes de error extensos o tecnicos como fallas de Docker daemon."""
    lower = text.lower()
    if any(k in lower for k in ("docker_engine", "docker daemon", "cannot connect to the docker", "is the docker daemon running", "docker.sock")):
        return "Docker no está en ejecución (abrí Docker Desktop)"
    if "address already in use" in lower or "wsaeaddrinuse" in lower:
        return "El puerto ya está ocupado por otro proceso"
    if "permission denied" in lower or "access is denied" in lower:
        return "Permiso denegado al ejecutar el comando"
    return text


def _why(proc: Proc) -> str:
    """Ultima linea con contenido de la salida del servicio.

    Es la diferencia entre "postgres fallo con codigo 1" y saber que el daemon de
    Docker no esta corriendo. Los avisos de compose sobre variables sin definir se
    saltean: son ruido y tapan la linea que importa.
    """
    for line in reversed(proc.tail):
        text = line.strip()
        if text and "level=warning" not in text:
            cleaned = clean_error_message(text)
            if len(cleaned) > WHY_MAX:
                cleaned = cleaned[: WHY_MAX - 1].rstrip() + "…"
            return f": {cleaned}"
    return ""


HTTP_PROBE_TIMEOUT = 1.0


def speaks_http(port: int) -> bool:
    """Si el puerto contesta HTTP, y por lo tanto se puede abrir en el navegador.

    Un postgres listo no es algo que abrir, y saber cual servicio es el frontend
    por el nombre es adivinar. Se le pregunta al puerto, igual que el puerto se le
    pregunta al proceso.

    Un 404 cuenta: la mayoria de las APIs no sirven nada en la raiz y siguen
    siendo HTTP. Lo que descarta al servicio es que no conteste.

    Un solo sondeo, en el momento en que el servicio queda listo: reintentar
    aca cuesta el timeout entero por cada puerto que no habla HTTP, y lo pagaria
    el arranque. Al servidor que contesta tarde porque compila en la primera
    peticion, como el modo dev de Next, lo recupera `Session._probe_late_http`
    desde su propio hilo.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=HTTP_PROBE_TIMEOUT):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _terminate_tree(pid: int, timeout: float = SHUTDOWN_TIMEOUT) -> None:
    """Cierra el proceso y sus descendientes.

    Con shell=True el hijo directo es el shell, y matarlo solo a el deja
    huerfano al servidor de verdad. Por eso se apaga el arbol entero.
    """
    try:
        parent = psutil.Process(pid)
        victims = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for victim in victims:
        try:
            victim.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(victims, timeout=timeout)
    for victim in alive:
        try:
            victim.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(alive, timeout=timeout)

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
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from rich.console import Console

from . import config, detect, ports
from .config import Service, Stack


def build_env(service: Service) -> dict[str, str]:
    """Construye el entorno de ejecucion con precedencia clara:
    1. os.environ
    2. ~/.portmaster/env.global (si existe)
    3. service.env_file (en orden)
    4. service.env (declarado explicito)
    """
    env = dict(os.environ)
    global_env = Path.home() / ".portmaster" / "env.global"
    if global_env.is_file():
        env.update(config.parse_env_file(global_env))
    for env_path in service.env_file:
        if env_path.is_file():
            env.update(config.parse_env_file(env_path))
    env.update(service.env)
    env["PYTHONUNBUFFERED"] = "1"
    env["FORCE_COLOR"] = "1"
    return env


def service_url(service: Service) -> str | None:
    """Adonde lleva "Abrir" para este servicio, o None si no se puede saber.

    Sin `url:` devuelve None y el que llama arma el default de siempre con el
    puerto. Con `url:`, expande `${VAR}` y `${VAR:-default}` desde el entorno
    que `build_env` ya compone, que es el mismo con el que corre el servicio: si
    la URL necesita un token, es el token que el proceso recibio.

    Una variable sin valor tambien devuelve None. Abrir el navegador en una URL
    con un `${TOKEN}` literal adentro es peor que no ofrecer el boton: parece
    que funciono.

    Toca disco (`build_env` lee `env.global` y cada `env_file`), asi que no se
    llama en el sondeo de la interfaz salvo para servicios ya abribles.
    """
    if not service.url:
        return None

    env = build_env(service)
    faltante = False

    def resolve(match: re.Match) -> str:
        nonlocal faltante
        valor = env.get(match.group(1))
        if valor:
            return valor
        if match.group(2) is not None:
            return match.group(2)
        faltante = True
        return match.group(0)

    expandida = detect.VARIABLE.sub(resolve, service.url)
    return None if faltante else expandida


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
    # El puerto ya aceptaba conexiones antes de arrancar. Ver _spawn_proc.
    port_taken: bool = False
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
    # Protege `procs` y `_down` entre los hilos de un mismo nivel y el apagado.
    _procs_lock: threading.Lock = field(default_factory=threading.Lock)

    def up(self, profile: str | None = None) -> None:
        """Arranca por niveles. Si algo falla, apaga lo ya levantado.

        Los servicios que no dependen entre si arrancan juntos: el stack tarda
        el healthcheck mas lento de cada nivel en vez de la suma de todos.
        """
        services = self.stack.resolve(profile)
        self._width = max(len(s.name) for s in services)
        # Color por posicion, antes de arrancar nada. `COLORS[len(self.procs) %
        # ...]` era un read-modify-write: dos servicios del mismo nivel podian
        # salir del mismo color, que es justo lo que hace legibles los logs
        # cuando se entreveran.
        colors = {s.name: COLORS[i % len(COLORS)] for i, s in enumerate(services)}
        try:
            for level in _levels(services):
                self._abort_if_cancelled()
                self._start_level(level, colors)
        except BaseException:
            self.down()
            raise

    def _start_level(self, level: list[Service], colors: dict[str, str]) -> None:
        if len(level) == 1:
            self._launch(level[0], colors[level[0].name])
            return

        fallos: list[BaseException] = []
        threads = [
            threading.Thread(target=self._launch_capturing, args=(s, colors[s.name], fallos))
            for s in level
        ]
        for thread in threads:
            thread.start()
        # Se esperan todos aunque uno falle: cortar antes dejaria a los hermanos
        # arrancando detras del apagado, que es el mismo bug que `cancel` vino a
        # resolver para el arranque entero.
        for thread in threads:
            thread.join()

        if fallos:
            if len(fallos) > 1:
                otros = ", ".join(str(f) for f in fallos[1:])
                raise StartupError(f"{fallos[0]} (y ademas: {otros})") from fallos[0]
            raise fallos[0]

    def _launch_capturing(
        self, service: Service, color: str, fallos: list[BaseException]
    ) -> None:
        try:
            self._launch(service, color)
        except BaseException as exc:  # el hilo no debe morir en silencio
            fallos.append(exc)

    def _launch(self, service: Service, color: str) -> None:
        proc = self._spawn_proc(service, color)
        if not self._register(proc):
            # El apagado ya paso por la lista: este proceso no lo va a ver nadie
            # mas, asi que lo baja quien lo arranco.
            self._stop_one(proc)
            raise StartupError("apagado pedido durante el arranque")
        self._wait_ready(proc)

    def _register(self, proc: Proc) -> bool:
        with self._procs_lock:
            if self._down:
                return False
            self.procs.append(proc)
            return True

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
            # Copia: un nivel todavia arrancando puede appendear mientras iteramos.
            or any(p.popen.poll() is None for p in list(self.procs))
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
        with self._procs_lock:
            if self._down:
                return
            self._down = True
            # Copia bajo el lock: si un hilo del nivel appendea mientras iteramos,
            # ese proc queda fuera de la lista y lo baja `_launch`, que ve el
            # `_down` y no lo registra.
            pendientes = list(reversed(self.procs))
        for proc in pendientes:
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

    def _spawn_proc(self, service: Service, color: str) -> Proc:
        # Una sola muestra, antes de arrancar. Con `ready: port` el servicio se
        # declara listo apenas alguien acepte en el puerto, y si ya habia alguien
        # ahi el verde puede estar señalando a un proceso ajeno. Saber quien es
        # el dueño costaria un recorrido de todos los procesos por sondeo, y en
        # macOS la tabla de conexiones pide root; saber si el puerto ya estaba
        # tomado cuesta un connect y contesta lo mismo para el que mira.
        #
        # No es un error: `docker compose up -d` sobre un contenedor que ya esta
        # arriba cae aca y es el caso legitimo. Por eso avisa y no cancela.
        if service.pre_start:
            self._say_raw(service.name, color, f"$ pre_start: {service.pre_start}")
            try:
                res = subprocess.run(
                    service.pre_start,
                    shell=True,
                    cwd=service.cwd,
                    env=build_env(service),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    timeout=DETACHED_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                # Sin esto el timeout salia crudo. Un `npm run build` colgado
                # rompia el arranque con un traceback en vez de decir que
                # servicio y que hook se quedaron esperando, que es lo unico que
                # hace falta para saber donde mirar.
                raise StartupError(
                    f"{service.name} pre_start no termino en {DETACHED_TIMEOUT:.0f}s"
                ) from None
            for line in (res.stdout or "").splitlines():
                self._write_raw(service.name, color, line)
            if res.returncode != 0:
                raise StartupError(f"{service.name} pre_start fallo con codigo {res.returncode}")

        taken = service.ready == "port" and ports.accepts(service.port)
        proc = Proc(service, self._spawn(service), color, port_taken=taken)
        self._say(proc, f"$ {service.command}")
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        return proc

    def _spawn(self, service: Service) -> subprocess.Popen:
        # shell=True es deliberado: `npm run dev` y `docker compose up -d` no son
        # ejecutables, y stack.yaml ya es codigo ejecutable por diseño. El README
        # documenta el modelo de confianza.
        return subprocess.Popen(
            service.command,
            shell=True,
            cwd=service.cwd,
            env=build_env(service),
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
                if proc.port_taken:
                    detail += " · el puerto ya estaba ocupado antes de arrancar"

                if service.post_start:
                    self._say(proc, f"$ post_start: {service.post_start}")
                    try:
                        res = subprocess.run(
                            service.post_start,
                            shell=True,
                            cwd=service.cwd,
                            env=build_env(service),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            errors="replace",
                            timeout=DETACHED_TIMEOUT,
                        )
                    except subprocess.TimeoutExpired:
                        raise StartupError(
                            f"{service.name} post_start no termino en {DETACHED_TIMEOUT:.0f}s"
                        ) from None
                    for line in (res.stdout or "").splitlines():
                        self._write(proc, line)
                    if res.returncode != 0:
                        raise StartupError(f"{service.name} post_start fallo con codigo {res.returncode}")

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
                    f"(ready: {service.ready}){_port_hint(proc)}{_why(proc)}"
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
            # `accepts` y no `not is_free`: is_free tambien cuenta como ocupado
            # un socket bindeado que todavia no llamo a listen(), y ahi el
            # servicio se declaraba listo antes de aceptar a nadie. El sondeo
            # HTTP que sigue se comia un connection refused y el servicio
            # perdia el boton Abrir. Ver ports.accepts.
            return ports.accepts(proc.service.port)
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
        self._say_raw(proc.service.name, proc.color, message)

    def _write(self, proc: Proc, text: str) -> None:
        self._write_raw(proc.service.name, proc.color, text)

    def _say_raw(self, name: str, color: str, message: str) -> None:
        self._write_raw(name, color, f"[dim]{message}[/]")

    def _write_raw(self, name: str, color: str, text: str) -> None:
        padded = name.ljust(self._width)
        self.console.print(f"[{color}]{padded}[/] [dim]|[/] {text}", highlight=False)


def _levels(services: list[Service]) -> list[list[Service]]:
    """Agrupa el orden de arranque en tandas que pueden arrancar juntas.

    `services` ya viene en orden topologico, asi que cuando se mira un servicio
    todas sus dependencias tienen nivel asignado y alcanza con una pasada.
    """
    nivel_de: dict[str, int] = {}
    levels: list[list[Service]] = []
    for service in services:
        nivel = max((nivel_de[d] + 1 for d in service.needs if d in nivel_de), default=0)
        nivel_de[service.name] = nivel
        while len(levels) <= nivel:
            levels.append([])
        levels[nivel].append(service)
    return levels


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
            env=build_env(service),
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


def _port_hint(proc: Proc) -> str:
    """Que paso con el puerto declarado, cuando el healthcheck ya se agoto.

    Un dev server que encuentra su puerto ocupado se corre al siguiente sin
    fallar: vite salta de 5177 a 5178 y sigue como si nada. El arranque queda
    esperando en el puerto viejo hasta el timeout y el error no dice por que.
    Solo corre en el camino del fallo, asi que los escaneos no los paga nadie
    que este arrancando bien.
    """
    declarado = proc.service.port
    if not declarado:
        return ""

    abiertos = ports.opened_by(proc.popen.pid)
    otros = [p for p in abiertos if p != declarado]
    if otros:
        return (
            f"; declaraste el puerto {declarado} pero abrio {', '.join(map(str, otros))}"
            f" (arrancalo con el puerto fijo, o cambia el port: del stack.yaml)"
        )

    dueno = ports.scan(declarado)
    if not dueno.free and dueno.pid is not None:
        quien = dueno.name or f"pid {dueno.pid}"
        return (
            f"; el puerto {declarado} ya lo tenia {quien} (pid {dueno.pid}):"
            f" liberalo con `portmaster free {declarado}` y reintenta"
        )
    return ""


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


# Solo se agota cuando alguien acepta la conexion y no contesta: un puerto
# cerrado corta en el acto y no cuesta nada. Ese caso es justo el de un servidor
# que acaba de bindear y todavia no entro a su bucle de atencion, y con 1s
# bastaba una maquina cargada para darlo por mudo.
HTTP_PROBE_TIMEOUT = 3.0
HTTP_PROBE_FIRST_TIMEOUT = 1.0
HTTP_PROBE_RETRY_DELAY = 0.1


def speaks_http(port: int) -> bool:
    """Si el puerto contesta HTTP, y por lo tanto se puede abrir en el navegador.

    Un postgres listo no es algo que abrir, y saber cual servicio es el frontend
    por el nombre es adivinar. Se le pregunta al puerto, igual que el puerto se le
    pregunta al proceso.

    Un 404 cuenta: la mayoria de las APIs no sirven nada en la raiz y siguen
    siendo HTTP. Lo que descarta al servicio es que no conteste.

    Dos intentos cortos, no uno solo ni muchos: reintentar sin limite costaria
    el timeout entero por cada puerto que no habla HTTP, y lo pagaria el
    arranque. Un puerto cerrado corta con ECONNREFUSED en el acto, asi que los
    dos intentos ahi no cuestan mas que el sleep del medio.

    El segundo intento es cinturon y tirantes desde que `ready: port` pregunta
    por `ports.accepts`: la carrera que cubria, sondear un socket que bindeo y
    todavia no llamo a listen(), ya no llega hasta aca.

    Al servidor que contesta tarde porque compila en la primera peticion, como
    el modo dev de Next, lo recupera `Session._probe_late_http` desde su propio
    hilo.
    """
    timeouts = (HTTP_PROBE_FIRST_TIMEOUT, HTTP_PROBE_TIMEOUT - HTTP_PROBE_FIRST_TIMEOUT)
    for i, timeout in enumerate(timeouts):
        try:
            # `localhost` y no 127.0.0.1: un dev server de Node escucha solo en
            # ::1, y preguntando por IPv4 se lo daba por mudo y se quedaba sin
            # boton Abrir. Por nombre, urllib prueba las dos, igual que hace el
            # navegador con el enlace que vamos a ofrecer. Ver ports.LOOPBACK.
            with urllib.request.urlopen(f"http://localhost:{port}", timeout=timeout):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, OSError, ValueError):
            if i == len(timeouts) - 1:
                return False
            time.sleep(HTTP_PROBE_RETRY_DELAY)
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

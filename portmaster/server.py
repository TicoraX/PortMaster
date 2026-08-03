"""API local que consume la interfaz web.

Este servidor ejecuta comandos arbitrarios definidos en stack.yaml. Se trata
como superficie sensible aunque solo escuche en loopback:

- bind exclusivo a 127.0.0.1
- token obligatorio en Authorization: Bearer, comparado en tiempo constante
- validacion del header Host contra rebinding de DNS
- rate limit en todas las rutas
- headers de seguridad y CSP estricta
- logging de cierres de procesos, rechazos de auth y excesos de rate limit
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rich.console import Console

from . import config, detect, ports, registry, runner

log = logging.getLogger("portmaster.server")

WEB = Path(__file__).parent / "web"
LOG_LINES = 500

# Cuotas por ventana de 15 minutos. La interfaz sondea el estado cada 2s, que da
# unas 450 peticiones por ventana: un limite global de 100 la romperia en el uso
# normal. Las rutas que ejecutan o matan procesos si van cortas.
WINDOW = 900
QUOTA_READ = 900
QUOTA_WRITE = 60
QUOTA_KILL = 30


class RateLimit:
    """Ventana deslizante en memoria.

    ponytail: un proceso, un usuario, sin persistencia. Si alguna vez hay mas de
    un worker, esto se cambia por un limiter con almacen compartido.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, quota: int, window: int = WINDOW) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= quota:
                return False
            hits.append(now)
            return True


class _Sink:
    """Recibe lo que escribe Rich y lo parte en lineas numeradas."""

    def __init__(self) -> None:
        self.lines: deque[tuple[int, str]] = deque(maxlen=LOG_LINES)
        self.seq = 0
        self._partial = ""

    def write(self, text: str) -> int:
        self._partial += text
        *complete, self._partial = self._partial.split("\n")
        for line in complete:
            self.seq += 1
            self.lines.append((self.seq, line.rstrip()))
        return len(text)

    def flush(self) -> None:
        if self._partial:
            self.seq += 1
            self.lines.append((self.seq, self._partial.rstrip()))
            self._partial = ""


@dataclass
class Session:
    """Un stack corriendo, arrancado desde la interfaz."""

    stack: config.Stack
    profile: str | None
    sink: _Sink = field(default_factory=_Sink)
    state: str = "starting"
    error: str | None = None
    engine: runner.Runner | None = None
    thread: threading.Thread | None = None

    def start(self) -> None:
        # force_terminal=False no es redundante con no_color: Rich mira FORCE_COLOR
        # del entorno y decide que el sink es una terminal, y no_color saca los
        # colores pero deja el dim, que llega al navegador como "[2m|[0m".
        console = Console(
            file=self.sink, force_terminal=False, no_color=True, width=160, soft_wrap=True
        )
        self.engine = runner.Runner(self.stack, console=console)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        assert self.engine is not None
        try:
            self.engine.up(self.profile)
            self.state = "running"
            if all(proc.service.detached for proc in self.engine.procs):
                # Todo detached: los comandos ya terminaron y lo que quedo vivo
                # (contenedores) esta fuera de nuestro arbol. follow() volveria
                # en el acto y el stack diria "detenido" con todo arriba.
                return
            self.engine.follow()
            # Si el apagado ya empezo, el que manda es el: `follow` vuelve en el
            # acto al cancelarse y "detenido" taparia el "apagando" mientras el
            # comando de apagado todavia corre.
            if self.state != "stopping":
                self.state = "stopped"
        except Exception as exc:  # el hilo no debe morir en silencio
            self.error = str(exc)
            self.state = "error"
            log.warning("stack %s fallo: %s", self.stack.name, exc)

    def stop_async(self) -> None:
        """Apaga sin hacer esperar al request.

        `docker compose stop` tarda decenas de segundos con varios contenedores.
        La interfaz sondea el estado igual que en el arranque, asi que lo unico
        que hace falta es un estado que sepa mostrar mientras tanto.
        """
        self.state = "stopping"
        threading.Thread(target=self.stop, daemon=True).start()

    def restart_async(self, name: str) -> None:
        """Reinicia un servicio. Como el apagado, no hace esperar al request."""
        threading.Thread(target=self._restart, args=(name,), daemon=True).start()

    def _restart(self, name: str) -> None:
        assert self.engine is not None
        try:
            self.engine.restart(name)
        except Exception as exc:  # el hilo no debe morir en silencio
            self.error = str(exc)
            self.state = "error"
            log.warning("reinicio de %s fallo: %s", name, exc)

    def stop(self) -> None:
        if self.engine is not None:
            # Apagar mientras arranca: el hilo de arranque es el que sabe que
            # levanto, asi que se le pide que corte y se lo espera. Despues su
            # `down` ya corrio y este no hace nada.
            self.engine.cancel()
            if self.thread is not None:
                # ponytail: un detached en curso (`docker compose up -d`
                # construyendo) no se puede cortar, se espera a que termine. Si
                # alguna vez molesta, matar el arbol del comando detached.
                self.thread.join(runner.STOP_TIMEOUT)
            self.engine.down()
        self.state = "stopped"

    def service_ports(self) -> dict[str, int]:
        """Puertos descubiertos al arrancar, para los servicios que no los declaran."""
        if self.engine is None:
            return {}
        return {p.service.name: p.port for p in self.engine.procs if p.port}

    def service_http(self) -> set[str]:
        """Servicios cuyo puerto contesta HTTP: los unicos que tiene sentido abrir."""
        if self.engine is None:
            return set()
        return {p.service.name for p in self.engine.procs if p.http}

    def service_states(self) -> dict[str, str]:
        if self.engine is None:
            return {}
        if self.state in ("stopped", "error"):
            return {}
        states = {}
        for proc in self.engine.procs:
            if proc.popen.poll() is not None and not proc.service.detached:
                states[proc.service.name] = "stopped"
            else:
                states[proc.service.name] = "ready" if proc.ready else "starting"
        return states


sessions: dict[str, Session] = {}
sessions_lock = threading.Lock()
limiter = RateLimit()


# seguridad ----------------------------------------------------------------


def require_token(request: Request) -> None:
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(supplied, request.app.state.token):
        log.warning("auth rechazada en %s", request.url.path)
        raise HTTPException(401, "token invalido")


def quota(name: str, limit: int):
    def dependency(request: Request) -> None:
        client = request.client.host if request.client else "desconocido"
        if not limiter.allow(f"{name}:{client}", limit):
            log.warning("rate limit excedido en %s desde %s", name, client)
            raise HTTPException(429, "Demasiadas peticiones. Espera un momento.")

    return Depends(dependency)


# modelos ------------------------------------------------------------------


class AddProject(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class UpRequest(BaseModel):
    profile: str | None = Field(default=None, max_length=100)


# app ----------------------------------------------------------------------


def create_app(token: str) -> FastAPI:
    app = FastAPI(title="PortMaster", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.allowed_hosts = {"127.0.0.1", "localhost", "[::1]"}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Rebinding de DNS: un sitio cualquiera puede resolver su dominio a
        # 127.0.0.1 y hablarle a este servidor desde el navegador de la victima.
        # El token ya lo frena, pero rechazar por Host cierra la puerta antes.
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in app.state.allowed_hosts:
            log.warning("host rechazado: %r", host)
            return JSONResponse({"detail": "host no permitido"}, status_code=400)

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        # Sin Strict-Transport-Security: el servidor es http en loopback y el
        # header obligaria a https a todo 127.0.0.1, rompiendo otros proyectos.
        return response

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/api/state", dependencies=[quota("state", QUOTA_READ), Depends(require_token)])
    def state() -> dict:
        return {"projects": [_project_view(path) for path in registry.paths()]}

    @app.get("/api/browse", dependencies=[quota("state", QUOTA_READ), Depends(require_token)])
    def browse(path: str = "") -> dict:
        try:
            return _browse(path)
        except ValueError as exc:
            log.info("browse rechazado: %s", exc)
            raise HTTPException(400, str(exc))

    @app.post("/api/projects", dependencies=[quota("write", QUOTA_WRITE), Depends(require_token)])
    def add_project(body: AddProject) -> dict:
        try:
            path = registry.add(body.path)
        except registry.RegistryError as exc:
            log.info("alta de proyecto rechazada: %s", exc)
            raise HTTPException(400, str(exc))
        return _project_view(path)

    @app.delete(
        "/api/projects/{pid}",
        dependencies=[quota("write", QUOTA_WRITE), Depends(require_token)],
    )
    def drop_project(pid: str) -> dict:
        with sessions_lock:
            session = sessions.pop(pid, None)
        if session is not None:
            session.stop()
        if not registry.remove(pid):
            raise HTTPException(404, "proyecto desconocido")
        return {"ok": True}

    @app.post(
        "/api/projects/{pid}/up",
        dependencies=[quota("write", QUOTA_WRITE), Depends(require_token)],
    )
    def up(pid: str, body: UpRequest) -> dict:
        path = _lookup(pid)
        try:
            stack = detect.stack_for(path)
            stack.resolve(body.profile)
        except config.ConfigError as exc:
            log.info("arranque rechazado para %s: %s", pid, exc)
            raise HTTPException(400, str(exc))

        with sessions_lock:
            live = sessions.get(pid)
            if live is not None and live.state in ("starting", "running"):
                raise HTTPException(409, "el stack ya esta corriendo")
            if live is not None and live.state == "stopping":
                raise HTTPException(409, "el stack se esta apagando")
            session = Session(stack, body.profile)
            sessions[pid] = session
        session.start()
        return {"ok": True}

    @app.post(
        "/api/projects/{pid}/down",
        dependencies=[quota("write", QUOTA_WRITE), Depends(require_token)],
    )
    def down(pid: str) -> dict:
        with sessions_lock:
            session = sessions.get(pid)
        if session is None:
            raise HTTPException(404, "ese stack no fue arrancado desde aca")
        if session.state != "stopping":
            session.stop_async()
        return {"ok": True}

    @app.post(
        "/api/projects/{pid}/services/{name}/restart",
        dependencies=[quota("write", QUOTA_WRITE), Depends(require_token)],
    )
    def restart(pid: str, name: str) -> dict:
        with sessions_lock:
            session = sessions.get(pid)
        if session is None:
            raise HTTPException(404, "ese stack no fue arrancado desde aca")
        if session.state != "running":
            raise HTTPException(409, "el stack no esta corriendo")
        if name not in session.stack.services:
            log.info("reinicio rechazado en %s: servicio %r desconocido", pid, name)
            raise HTTPException(404, "ese servicio no esta en el stack")
        session.restart_async(name)
        return {"ok": True}

    @app.get(
        "/api/projects/{pid}/logs",
        dependencies=[quota("state", QUOTA_READ), Depends(require_token)],
    )
    def logs(pid: str, since: int = 0) -> dict:
        with sessions_lock:
            session = sessions.get(pid)
        if session is None:
            return {"lines": [], "seq": 0}
        pending = [
            {"seq": seq, "text": text}
            for seq, text in list(session.sink.lines)
            if seq > since
        ]
        return {"lines": pending, "seq": session.sink.seq}

    @app.post(
        "/api/ports/{port}/kill",
        dependencies=[quota("kill", QUOTA_KILL), Depends(require_token)],
    )
    def kill_port(port: int) -> dict:
        try:
            status = ports.scan(port)
        except ValueError as exc:
            log.info("puerto rechazado: %s", exc)
            raise HTTPException(400, str(exc))

        if status.free:
            return {"ok": True, "detail": "ya estaba libre"}
        if status.pid is None:
            raise HTTPException(403, "el proceso no es visible con estos permisos")

        try:
            ports.kill(status.pid, status.create_time)
        except ports.KillRefused as exc:
            log.warning("kill rechazado en %d: %s", port, exc)
            raise HTTPException(409, str(exc))
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            log.warning("kill sin permisos en %d (pid %d)", port, status.pid)
            raise HTTPException(403, "sin permisos para cerrar ese proceso")

        log.info("proceso cerrado: puerto=%d pid=%d nombre=%s", port, status.pid, status.name)
        return {"ok": True}

    return app


# vistas -------------------------------------------------------------------


# exploracion de carpetas -------------------------------------------------
#
# El navegador no puede dar rutas absolutas (webkitdirectory las oculta a
# proposito), asi que el listado sale de aca. Solo nombres de carpetas y de los
# archivos marcadores: nunca contenido, nunca archivos sueltos.

MARKERS = ("stack.yaml", "stack.yml", *detect.COMPOSE_NAMES, "package.json", "manage.py")

# Carpetas que nunca son un proyecto y solo hacen ruido al navegar.
BROWSE_SKIP = {"node_modules", "__pycache__", "venv", "env", "dist", "build", "target"}
BROWSE_LIMIT = 300


def _browse(raw: str) -> dict:
    if not raw:
        return _roots()

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"la ruta debe ser absoluta: {raw}")
    try:
        path = path.resolve(strict=True)
    except OSError:
        raise ValueError(f"no existe: {raw}") from None
    if not path.is_dir():
        raise ValueError(f"no es un directorio: {path}")

    names = _subdirs(path)
    return {
        "path": str(path),
        # "" manda a la vista de raices; None es no tener a donde subir.
        "parent": "" if path.parent == path else str(path.parent),
        "markers": _markers(path),
        "truncated": len(names) > BROWSE_LIMIT,
        "entries": [
            {"name": name, "path": str(path / name), "markers": _markers(path / name)}
            for name in names[:BROWSE_LIMIT]
        ],
    }


def _subdirs(path: Path) -> list[str]:
    found = []
    try:
        with os.scandir(path) as items:
            for item in items:
                if item.name.startswith(".") or item.name in BROWSE_SKIP:
                    continue
                try:
                    if item.is_dir():
                        found.append(item.name)
                except OSError:
                    continue  # enlace roto o unidad desconectada
    except OSError:
        return []  # sin permisos se ve vacia, que no es un error del usuario
    return sorted(found, key=str.lower)


def _markers(path: Path) -> list[str]:
    """Archivos que delatan un proyecto.

    ponytail: un stat por marcador y por carpeta, hasta ~1800 en un listado
    grande. Es local y en SSD no se nota. Si alguna vez pesa, la salida es un
    solo scandir por carpeta e intersecar los nombres.
    """
    return [name for name in MARKERS if (path / name).is_file()]


def _roots() -> dict:
    """Punto de partida: la home del usuario y las unidades montadas."""
    seen = {str(Path.home())}
    entries = [{"name": "Inicio", "path": str(Path.home()), "markers": []}]
    for partition in psutil.disk_partitions(all=False):
        mount = partition.mountpoint
        if mount not in seen and os.path.isdir(mount):
            seen.add(mount)
            entries.append({"name": mount, "path": mount, "markers": []})
    return {"path": "", "parent": None, "markers": [], "truncated": False, "entries": entries}


def _lookup(pid: str) -> Path:
    for path in registry.paths():
        if registry.project_id(path) == pid:
            return path
    raise HTTPException(404, "proyecto desconocido")


def _project_view(path: Path) -> dict:
    pid = registry.project_id(path)
    base = {"id": pid, "path": str(path), "name": path.name}

    try:
        stack = detect.stack_for(path)
    except config.ConfigError as exc:
        return {**base, "state": "invalid", "error": str(exc), "services": [], "profiles": []}

    with sessions_lock:
        session = sessions.get(pid)
    running = session.service_states() if session else {}
    discovered = session.service_ports() if session else {}
    openable = session.service_http() if session else set()

    scanned = ports.scan_many([s.port for s in stack.services.values() if s.port])
    services = []
    for service in stack.services.values():
        status = scanned.get(service.port) if service.port else None
        state = running.get(service.name, "stopped")
        # Un detached vive fuera de nuestro arbol: si alguien lo bajo por afuera
        # (docker stop), el puerto libre es la verdad y el proceso no dice nada.
        if state == "ready" and service.detached and status is not None and status.free:
            state = "stopped"
        services.append(
            {
                "name": service.name,
                # Contenedor o proceso local: es lo unico que se sabe de verdad
                # del rol de un servicio. Adivinar "backend" por el nombre no.
                "kind": "container" if service.detached else "local",
                "port": service.port or discovered.get(service.name),
                # Solo lo que contesta HTTP se ofrece para abrir: un postgres
                # listo tiene puerto y no es algo que mandar al navegador.
                "openable": state != "stopped" and service.name in openable,
                "needs": list(service.needs),
                "state": state,
                "occupant": _occupant(status, state != "stopped"),
            }
        )

    return {
        **base,
        "name": stack.name,
        "state": session.state if session else "stopped",
        "error": session.error if session else None,
        "detected": stack.detected,
        "profiles": sorted(stack.profiles),
        "services": services,
    }


def _occupant(status: ports.PortStatus | None, ours: bool) -> dict | None:
    """Quien ocupa el puerto, solo cuando no somos nosotros."""
    if status is None or status.free or ours:
        return None
    return {"pid": status.pid, "name": status.name or "desconocido"}

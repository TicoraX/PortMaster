"""Deteccion de servicios en un proyecto sin stack.yaml.

Mira la raiz del proyecto y arma el mismo `Stack` congelado que produce
`config.load`, para que `runner`, `server` y `cli` no distingan el origen.

Tres detectores, en el orden en que hay que arrancarlos: contenedores, backend,
frontend. Cada uno devuelve los servicios que reconoce, o una lista vacia. El
compose devuelve uno por contenedor, para que cada uno tenga su puerto y su
estado propios.

Ningun detector adivina el puerto de un proceso que no lo declara: compose si lo
declara y se lee del archivo, y los otros dos usan `ready: listen`, que descubre
el puerto real del proceso ya arrancado. Ver el spec en docs/.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path

import yaml

from .config import CONFIG_NAMES, ConfigError, Service, Stack, find, load

COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")

# lockfile -> gestor. npm es el fallback: package-lock.json no es obligatorio.
LOCKFILES = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "bun.lock": "bun",
}

# Donde vive la app ASGI, en orden de preferencia.
ASGI_MODULES = ("main.py", "app.py", "asgi.py", "src/main.py", "api/main.py", "app/main.py")

# Scripts que levantan un servidor, en orden de preferencia. `start:dev` es el
# modo watch de Nest, que no tiene `dev`.
NODE_SCRIPTS = ("dev", "start:dev", "serve", "start")

# Subcarpetas donde vive el frontend de un monorepo, y los grupos cuyos hijos se
# revisan uno por uno.
NODE_DIRS = ("frontend", "web", "client", "ui", "front", "site")
PYTHON_DIRS = ("backend", "api", "server")
WORKSPACE_DIRS = ("apps", "packages", "services")

# Dependencias que delatan un servidor de desarrollo de verdad.
DEV_SERVERS = (
    "vite",
    "next",
    "nuxt",
    "astro",
    "@remix-run",
    "react-scripts",
    "@angular/cli",
    "webpack-dev-server",
    "@nestjs/cli",
    "expo",
    "@sveltejs/kit",
    "parcel",
    "gatsby",
    "nodemon",
    "ts-node-dev",
)


def stack_for(root: Path) -> Stack:
    """Stack del proyecto: el archivo si existe, la deteccion si no.

    El archivo se busca hacia arriba como siempre, para poder correr desde un
    subdirectorio. La deteccion solo mira `root`.
    """
    try:
        path = find(root)
    except ConfigError:
        path = None
    if path is not None:
        # Un archivo invalido es un error, no una excusa para detectar por atras.
        return load(path)

    found = detect(root)
    if found is None:
        raise ConfigError(
            f"{root} no tiene stack.yaml y no se detecto nada conocido "
            "(compose, package.json, manage.py)"
        )
    return found


def detect(root: Path) -> Stack | None:
    """Servicios detectados en root, o None si no se reconoce nada."""
    root = root.resolve()
    services: dict[str, Service] = {}
    previous: tuple[str, ...] = ()

    opcionales = _compose_profiles(root)

    for detector in (_compose, _python, _node):
        group = []
        for service in detector(root):
            if service.name in services:
                continue  # el primero gana: el contenedor le come el nombre al local
            # Los contenedores traen sus propias dependencias del compose. Los
            # demas heredan la cadena: el frontend espera al backend, y el
            # backend a los contenedores.
            wired = replace(service, needs=service.needs or previous)
            services[wired.name] = wired
            # Un contenedor con perfil no entra en la cadena heredada: si el
            # frontend lo necesitara, el orden topologico lo volveria a arrastrar
            # al arranque por defecto y el perfil no serviria de nada.
            if wired.name not in opcionales:
                group.append(wired.name)
        if group:
            previous = tuple(group)

    if not services:
        return None

    stack = Stack(
        name=root.name,
        root=root,
        path=root,
        services={
            name: replace(service, needs=tuple(d for d in service.needs if d in services))
            for name, service in services.items()
        },
        profiles=_profiles_for(services, opcionales),
        detected=True,
        # Solo cuando hay algo que dejar afuera: sin perfiles, `None` sigue
        # queriendo decir "todo", que es lo que era antes de existir este campo.
        default=tuple(n for n in services if n not in opcionales) if opcionales else None,
    )
    stack.resolve()  # los ciclos fallan al detectar, no a mitad del arranque
    return stack


def _profiles_for(
    services: dict[str, Service], opcionales: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    """Un perfil de PortMaster por cada perfil declarado en el compose.

    Pedir un perfil arranca lo de siempre **mas** los contenedores de ese
    perfil, que es lo que hace `docker compose --profile X up`. Un perfil que
    arrancara solo sus propios contenedores dejaria al resto del stack afuera y
    no es lo que nadie quiso decir.
    """
    base = tuple(n for n in services if n not in opcionales)
    nombres = {p for perfiles in opcionales.values() for p in perfiles}
    return {
        nombre: base + tuple(n for n, perfiles in opcionales.items() if nombre in perfiles)
        for nombre in sorted(nombres)
    }


def freeze(root: Path) -> Path:
    """Escribe lo detectado como stack.yaml. Devuelve el archivo escrito.

    Vive aca y no en `cli` porque la interfaz ofrece lo mismo, y `CLAUDE.md`
    pide que el CLI y el servidor sean dos consumidores de la misma funcion.
    """
    target = root / CONFIG_NAMES[0]
    if any((root / name).is_file() for name in CONFIG_NAMES):
        raise ConfigError(f"{root} ya tiene un stack.yaml. No se sobreescribe.")

    stack = detect(root)
    if stack is None:
        raise ConfigError(
            f"No se detecto nada conocido en {root} (compose, package.json, manage.py)"
        )
    target.write_text(to_yaml(stack), encoding="utf-8")
    return target


def to_yaml(stack: Stack) -> str:
    """Serializa un stack detectado al formato de stack.yaml."""
    services = {}
    for service in stack.services.values():
        spec: dict[str, object] = {"command": service.command}
        if service.cwd != stack.root:
            spec["cwd"] = service.cwd.relative_to(stack.root).as_posix()
        if service.port:
            spec["port"] = service.port
        spec["ready"] = service.ready
        if service.needs:
            spec["needs"] = list(service.needs)
        if service.detached:
            spec["detached"] = True
        if service.stop:
            spec["stop"] = service.stop
        services[service.name] = spec

    # Congelar tiene que ser fiel: sin estas dos claves, un compose con
    # `profiles:` volveria a cargarse arrancando lo que deja apagado.
    document: dict[str, object] = {"name": stack.name, "services": services}
    if stack.default is not None:
        document["default"] = list(stack.default)
    if stack.profiles:
        document["profiles"] = {name: list(members) for name, members in stack.profiles.items()}

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


# detectores ---------------------------------------------------------------


def _compose_services(root: Path) -> dict | None:
    """El mapa `services` del compose. None si no hay compose, {} si es ilegible.

    Lo leen dos funciones (los contenedores y sus perfiles) y no queria dos
    copias de la busqueda del archivo: divergen en el primer nombre nuevo.
    """
    path = next((root / name for name in COMPOSE_NAMES if (root / name).is_file()), None)
    if path is None:
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        raw = None
    declared = raw.get("services") if isinstance(raw, dict) else None
    return declared if isinstance(declared, dict) else {}


def _compose(root: Path) -> list[Service]:
    """Un servicio por contenedor, no uno solo llamado "docker".

    `docker compose up -d <nombre>` arranca ese contenedor y sus dependencias, y
    es idempotente. Asi cada contenedor tiene su puerto, su estado y su link en
    la interfaz, en vez de esconderse detras de un unico bloque opaco.
    """
    declared = _compose_services(root)
    if declared is None:
        return []
    if not declared:
        # Compose ilegible o sin servicios: se arranca entero y sin puertos.
        return [
            _container("docker", "docker compose up -d", root, None, (), "docker compose stop")
        ]

    env = _dotenv(root)
    names = {str(name) for name in declared}
    found = []
    for name, spec in declared.items():
        name = str(name)
        spec = spec if isinstance(spec, dict) else {}
        needs = tuple(dep for dep in _depends_on(spec) if dep in names and dep != name)
        found.append(
            _container(
                name,
                f"docker compose up -d {name}",
                root,
                _first_port(spec, env),
                needs,
                f"docker compose stop {name}",
            )
        )
    return found


def _container(
    name: str, command: str, root: Path, port: int | None, needs: tuple[str, ...], stop: str
):
    return Service(
        name=name,
        command=command,
        cwd=root,
        port=port,
        # Con puerto publicado se espera a que acepte conexiones; sin el, `up -d`
        # ya termino y no hay nada mas que mirar desde afuera.
        ready="port" if port else "none",
        needs=needs,
        env={},
        detached=True,
        stop=stop,  # el contenedor no muere con el cliente que lo arranco
    )


def _compose_profiles(root: Path) -> dict[str, tuple[str, ...]]:
    """Perfiles declarados por cada contenedor: nombre -> perfiles a los que pertenece.

    Ojo con la semantica, que esta invertida respecto de la de PortMaster: en
    compose, un servicio con `profiles:` queda **excluido** por defecto y solo
    entra cuando pedis uno de sus perfiles. En PortMaster un perfil es la lista
    de servicios a arrancar. Traducir uno al otro es el trabajo de `detect`,
    aca abajo; mapearlos directo arrancaria lo que compose deja apagado a
    proposito.
    """
    declared = _compose_services(root) or {}
    found = {}
    for name, spec in declared.items():
        value = spec.get("profiles") if isinstance(spec, dict) else None
        # Viene como lista, o como string suelto si hay uno solo.
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            perfiles = tuple(str(p) for p in value if isinstance(p, (str, int)))
            if perfiles:
                found[str(name)] = perfiles
    return found


def _depends_on(spec: dict) -> tuple[str, ...]:
    """`depends_on` en sus dos formas: lista de nombres, o mapa con condiciones."""
    value = spec.get("depends_on")
    if isinstance(value, dict):
        return tuple(str(name) for name in value)
    if isinstance(value, list):
        return tuple(str(name) for name in value if isinstance(name, (str, int)))
    return ()


def _first_port(spec: dict, env: dict[str, str]) -> int | None:
    for entry in spec.get("ports") or ():
        port = _published(entry, env)
        if port is not None:
            return port
    return None


def _published(entry: object, env: dict[str, str]) -> int | None:
    """Puerto del host en una entrada de `ports:`.

    Las formas son "8080:80", "127.0.0.1:8080:80", 8080 y {published: 8080}, con
    o sin `${VAR:-default}` adentro. Se descartan los rangos ("8000-8010:80") y
    las entradas de un solo puerto ("80" publica en un puerto del host al azar):
    en los dos casos no hay un puerto fijo que mirar.
    """
    if isinstance(entry, dict):
        return _valid(_interpolate(entry.get("published"), env))
    if not isinstance(entry, str):
        return None
    pieces = _interpolate(entry, env).split(":")
    if len(pieces) < 2:
        return None
    return _valid(pieces[-2])


# ponytail: solo la forma con llaves. `$VAR` a secas tambien es valido en compose
# y no se resuelve; el puerto queda desconocido, que es mejor que inventarlo.
VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _interpolate(value: object, env: dict[str, str]) -> object:
    if not isinstance(value, str):
        return value

    def resolve(match: re.Match) -> str:
        # Mismo orden que compose: entorno del shell, .env, y por ultimo el
        # default de la propia expresion.
        found = os.environ.get(match.group(1)) or env.get(match.group(1))
        if found:
            return found
        return match.group(2) if match.group(2) is not None else match.group(0)

    return VARIABLE.sub(resolve, value)


def _dotenv(root: Path) -> dict[str, str]:
    """Variables de `.env`, y solo para resolver puertos del compose.

    Compose lo lee, asi que ignorarlo daria puertos equivocados justo en los
    proyectos que parametrizan el puerto del frontend. Los valores no se
    loguean ni se pasan a ningun proceso.
    """
    values = {}
    for line in _read(root / ".env").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _valid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        port = int(value)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def _python(root: Path) -> list[Service]:
    at_root = _python_at(root, "api")
    if at_root is not None:
        # Igual que en Node: si la raiz es el proyecto, no se baja una vuelta.
        return [at_root]

    found = []
    for path in _subprojects(root, PYTHON_DIRS):
        service = _python_at(path, path.name)
        if service is not None:
            found.append(service)
    return found


def _python_at(path: Path, name: str) -> Service | None:
    if (path / "manage.py").is_file():
        return _served(name, "python manage.py runserver", path)

    declared = "\n".join(
        _read(path / archivo)
        for archivo in ("pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock", "uv.lock")
    ).lower()
    if "fastapi" not in declared and "uvicorn" not in declared:
        return None

    module = _asgi_module(path)
    if module is None:
        return None
    return _served(name, f"uvicorn {module}:app --reload", path)


def _asgi_module(root: Path) -> str | None:
    """Modulo con un `app` de nivel superior, en notacion de puntos."""
    for candidate in ASGI_MODULES:
        path = root / candidate
        if not path.is_file():
            continue
        for line in _read(path).splitlines():
            if line.startswith(("app = ", "app=", "app: ")):
                return candidate[: -len(".py")].replace("/", ".")
    return None


def _node(root: Path) -> list[Service]:
    at_root = _package(root, root, "web", strict=False)
    if at_root is not None:
        # El package.json de la raiz manda: en un monorepo su script `dev` suele
        # ser el orquestador (turbo, nx) y arrancar ademas los hijos duplicaria
        # todo. Si no hay ninguno, se busca una vuelta mas abajo.
        return [at_root]

    found = []
    for path in _subprojects(root, NODE_DIRS):
        service = _package(path, root, path.name, strict=True)
        if service is not None:
            found.append(service)
    return found


def _subprojects(root: Path, names: tuple[str, ...]):
    """Subcarpetas candidatas, una sola vuelta.

    Sin recursion a proposito: un scan profundo entra en `node_modules` y en cada
    template de ejemplo que tenga el repo.
    """
    for name in names:
        yield root / name
    for group in WORKSPACE_DIRS:
        parent = root / group
        if not parent.is_dir():
            continue
        try:
            children = sorted(parent.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and not child.name.startswith(".") and child.name != "node_modules":
                yield child


def _package(path: Path, root: Path, name: str, strict: bool) -> Service | None:
    try:
        raw = json.loads(_read(path / "package.json") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None

    scripts = raw.get("scripts")
    if not isinstance(scripts, dict):
        return None
    script = next((s for s in NODE_SCRIPTS if isinstance(scripts.get(s), str)), None)
    if script is None:
        return None
    if strict and not _serves(raw):
        return None

    return _served(name, f"{_manager(raw, path, root)} run {script}", path)


def _serves(raw: dict) -> bool:
    """Si el paquete declara un servidor de desarrollo.

    En un workspace hay tantas librerias como apps, y una libreria con
    `dev: tsc --watch` entraria como servicio y nunca abriria un puerto: el
    arranque se quedaria esperando a que este lista hasta el timeout.
    """
    declared = {
        *(raw.get("dependencies") or {}),
        *(raw.get("devDependencies") or {}),
    }
    return any(
        dep == server or dep.startswith(server) for dep in declared for server in DEV_SERVERS
    )


def _manager(raw: dict, path: Path, root: Path) -> str:
    pinned = raw.get("packageManager")
    if isinstance(pinned, str):
        for tool in ("pnpm", "yarn", "bun", "npm"):
            if pinned.startswith(tool):
                return tool
    # El lockfile del propio paquete, y si no el de la raiz: en un monorepo hay
    # uno solo y esta arriba.
    for base in (path, root):
        for lock, tool in LOCKFILES.items():
            if (base / lock).is_file():
                return tool
    return "npm"


# helpers ------------------------------------------------------------------


def _served(name: str, command: str, root: Path) -> Service:
    """Servicio de larga duracion cuyo puerto se descubre al arrancar."""
    return Service(
        name=name,
        command=command,
        cwd=root,
        port=None,
        ready="listen",
        needs=(),
        env={},
        detached=False,
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

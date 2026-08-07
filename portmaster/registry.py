"""Proyectos que la interfaz conoce.

El CLI trabaja sobre el directorio actual y no necesita registro. La interfaz
si: su razon de existir es ver todos los proyectos a la vez sin importar en que
carpeta estas parado.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from . import config, detect

HOME = Path(os.environ.get("PORTMASTER_HOME") or Path.home() / ".portmaster")
PROJECTS = HOME / "projects.json"


class RegistryError(Exception):
    """La ruta no sirve como proyecto."""


def project_id(path: Path) -> str:
    """Identificador estable y seguro para URLs, derivado de la ruta."""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def paths() -> list[Path]:
    try:
        data = json.loads(PROJECTS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [Path(item) for item in data if isinstance(item, str)]


def add(raw: str | Path) -> Path:
    """Registra un proyecto: con stack.yaml propio, o detectable."""
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise RegistryError(f"no es un directorio: {path}")
    path = path.resolve()

    known = any((path / name).is_file() for name in config.CONFIG_NAMES)
    if not known and detect.detect(path) is None:
        raise RegistryError(
            f"{path} no tiene {config.CONFIG_NAMES[0]} y no se detecto nada conocido"
        )

    current = paths()
    if path not in current:
        _save(current + [path])
    return path


def remove(pid: str) -> bool:
    current = paths()
    kept = [p for p in current if project_id(p) != pid]
    if len(kept) == len(current):
        return False
    _save(kept)
    return True


def export_data() -> list[str]:
    """Exporta las rutas de los proyectos registrados como lista JSON."""
    return [str(p) for p in paths()]


def import_data(data: list[str]) -> list[str]:
    """Importa masivamente rutas de proyectos desde una lista."""
    if not isinstance(data, list):
        raise RegistryError("el formato debe ser una lista de rutas de proyectos")
    imported = []
    for item in data:
        if isinstance(item, str):
            try:
                path = add(item)
                imported.append(str(path))
            except RegistryError:
                pass
    return imported


def declared_ports() -> dict[int, list[Path]]:
    """Puerto declarado -> proyectos registrados que lo piden.

    Es el unico dato que PortMaster tiene y las herramientas de un proyecto solo
    no pueden tener: cada compose se conoce a si mismo y ninguno sabe del de al
    lado. Sin esto, que dos proyectos peleen por el 3000 se descubre cuando el
    segundo no arranca.

    ponytail: resuelve el stack de cada proyecto registrado, o sea una deteccion
    por proyecto. Va bien para un comando que corre una vez; si alguna vez lo
    quiere la vista de estado, que sondea cada 2.5s, hay que cachearlo por mtime
    del stack.yaml.
    """
    found: dict[int, list[Path]] = {}
    for path in paths():
        for port in sorted(_ports_of(path)):
            found.setdefault(port, []).append(path)
    return found


def _ports_of(path: Path) -> set[int]:
    """Puertos declarados por un proyecto. Vacio si no se puede leer.

    Un proyecto roto o borrado no es motivo para que el resto no se revise:
    tiene su propio chequeo en `doctor`.
    """
    try:
        stack = detect.stack_for(path)
        return {s.port for s in stack.resolve() if s.port}
    except (config.ConfigError, OSError):
        return set()


def _save(items: list[Path]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    ordered = sorted({str(p) for p in items})
    tmp = PROJECTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    tmp.replace(PROJECTS)


def token() -> str:
    """Token de la API local.

    Prioriza PORTMASTER_TOKEN. Si no esta, usa uno generado en el directorio del
    usuario. Ver la desviacion documentada en CLAUDE.md: una herramienta que se
    instala con pipx no puede traer un .env, y un token generado con permisos
    0600 fuera del repo es mas seguro que uno que el usuario copia a mano.
    """
    from secrets import token_urlsafe

    from_env = os.environ.get("PORTMASTER_TOKEN")
    if from_env:
        if len(from_env) < 16:
            raise RegistryError("PORTMASTER_TOKEN es demasiado corto (minimo 16)")
        return from_env

    path = HOME / "token"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 16:
            return existing
    except OSError:
        pass

    HOME.mkdir(parents=True, exist_ok=True)
    fresh = token_urlsafe(32)
    path.write_text(fresh, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # sistemas de archivos sin permisos POSIX
    return fresh

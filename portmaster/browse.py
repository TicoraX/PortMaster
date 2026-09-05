"""Exploracion de carpetas para el selector de proyectos de la interfaz.

El navegador no puede dar rutas absolutas (webkitdirectory las oculta a
proposito), asi que el listado sale de aca. Solo nombres de carpetas y de los
archivos marcadores: nunca contenido, nunca archivos sueltos.

Recorrer el disco no tiene nada que ver con servir HTTP, y este modulo no
importa nada de fastapi: `server` traduce el ValueError a un 400.
"""

from __future__ import annotations

import os
from pathlib import Path

import psutil

from . import detect

MARKERS = ("stack.yaml", "stack.yml", *detect.COMPOSE_NAMES, "package.json", "manage.py")

# Carpetas que nunca son un proyecto y solo hacen ruido al navegar.
SKIP = {"node_modules", "__pycache__", "venv", "env", "dist", "build", "target"}
LIMIT = 300


def listing(raw: str) -> dict:
    """Contenido navegable de `raw`, o las raices si viene vacio.

    Levanta ValueError con un motivo legible si la ruta no sirve.
    """
    if not raw:
        return roots()

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
        "markers": markers(path),
        "truncated": len(names) > LIMIT,
        "entries": [
            {"name": name, "path": str(path / name), "markers": markers(path / name)}
            for name in names[:LIMIT]
        ],
    }


def _subdirs(path: Path) -> list[str]:
    found = []
    try:
        with os.scandir(path) as items:
            for item in items:
                if item.name.startswith(".") or item.name in SKIP:
                    continue
                try:
                    if item.is_dir():
                        found.append(item.name)
                except OSError:
                    continue  # enlace roto o unidad desconectada
    except OSError:
        return []  # sin permisos se ve vacia, que no es un error del usuario
    return sorted(found, key=str.lower)


def markers(path: Path) -> list[str]:
    """Archivos que delatan un proyecto.

    ponytail: un stat por marcador y por carpeta, hasta ~1800 en un listado
    grande. Es local y en SSD no se nota. Si alguna vez pesa, la salida es un
    solo scandir por carpeta e intersecar los nombres.
    """
    return [name for name in MARKERS if (path / name).is_file()]


def roots() -> dict:
    """Punto de partida: la home del usuario y las unidades montadas."""
    seen = {str(Path.home())}
    entries = [{"name": "Inicio", "path": str(Path.home()), "markers": []}]
    try:
        partitions = psutil.disk_partitions(all=False)
    except OSError:
        partitions = []
    for partition in partitions:
        mount = partition.mountpoint
        if mount not in seen and os.path.isdir(mount):
            seen.add(mount)
            entries.append({"name": mount, "path": mount, "markers": []})
    return {"path": "", "parent": None, "markers": [], "truncated": False, "entries": entries}

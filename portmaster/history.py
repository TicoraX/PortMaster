import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from portmaster import guardrails, registry

MAX_LIMIT = 50
MAX_ENTRIES = 500
RETAIN_ENTRIES = 250
_history_lock = threading.Lock()


def _history_file(pid: str) -> Path:
    clean_pid = guardrails.validate_identifier(pid, "pid")
    return (registry.HOME / "history" / f"{clean_pid}.jsonl").resolve()


def _read_tail_lines(path: Path, limit: int) -> list[str]:
    """Lee las últimas `limit` líneas de un archivo sin cargarlo entero en memoria."""
    buffer_size = 4096
    lines: list[bytes] = []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            remaining_bytes = file_size
            remainder = b""

            while remaining_bytes > 0 and len(lines) < limit:
                read_size = min(buffer_size, remaining_bytes)
                f.seek(remaining_bytes - read_size, os.SEEK_SET)
                chunk = f.read(read_size) + remainder
                chunk_lines = chunk.split(b"\n")
                if remaining_bytes - read_size > 0:
                    remainder = chunk_lines[0]
                    complete_lines = chunk_lines[1:]
                else:
                    remainder = b""
                    complete_lines = chunk_lines

                for line_bytes in reversed(complete_lines):
                    if line_bytes.strip():
                        lines.append(line_bytes)
                        if len(lines) >= limit:
                            break
                remaining_bytes -= read_size

            if remainder.strip() and len(lines) < limit:
                lines.append(remainder)
    except OSError:
        return []

    lines.reverse()
    return [line_bytes.decode("utf-8", errors="replace") for line_bytes in lines]


def _rotate_if_needed(path: Path) -> None:
    """Si el archivo supera el umbral de tamaño, lo trunca reteniendo solo los últimos RETAIN_ENTRIES."""
    try:
        if not path.is_file() or path.stat().st_size < 100_000:
            return
        last_lines = _read_tail_lines(path, RETAIN_ENTRIES)
        if len(last_lines) >= RETAIN_ENTRIES:
            tmp_path = path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                for line_str in last_lines:
                    f.write(line_str.strip() + "\n")
            tmp_path.replace(path)
    except (OSError, ValueError):
        pass


def append(pid: str, data: dict[str, Any]) -> None:
    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

    try:
        path = _history_file(pid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _history_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
            _rotate_if_needed(path)
    except (OSError, ValueError):
        pass


def read(pid: str, limit: int = 5) -> list[dict[str, Any]]:
    limit = max(1, min(limit, MAX_LIMIT))
    try:
        path = _history_file(pid)
    except ValueError:
        return []

    if not path.is_file():
        return []

    records = []
    with _history_lock:
        raw_lines = _read_tail_lines(path, limit)

    for line in raw_lines:
        if line.strip():
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except json.JSONDecodeError:
                continue

    return records

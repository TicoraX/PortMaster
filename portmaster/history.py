import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from portmaster import registry

MAX_LIMIT = 50


def _history_file(pid: str) -> Path:
    return registry.HOME / "history" / f"{pid}.jsonl"


def append(pid: str, data: dict[str, Any]) -> None:
    path = _history_file(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
    except OSError:
        pass


def read(pid: str, limit: int = 5) -> list[dict[str, Any]]:
    limit = max(1, min(limit, MAX_LIMIT))
    path = _history_file(pid)
    if not path.is_file():
        return []
    
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict):
                            lines.append(record)
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    
    return lines[-limit:]

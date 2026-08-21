import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _history_file(pid: str) -> Path:
    base = Path("~/.portmaster").expanduser()
    return base / "history" / f"{pid}.jsonl"


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
    path = _history_file(pid)
    if not path.is_file():
        return []
    
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    
    return lines[-limit:]

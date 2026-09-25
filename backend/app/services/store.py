from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import DATA_DIR

_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_project_dir() -> tuple[str, Path]:
    project_id = uuid.uuid4().hex[:12]
    project_dir = DATA_DIR / project_id
    (project_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (project_dir / "work").mkdir(parents=True, exist_ok=True)
    return project_id, project_dir


def project_file(project_dir: Path) -> Path:
    return project_dir / "project.json"


def save_state(project_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    with _LOCK:
        project_file(project_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state(project_id: str) -> dict[str, Any]:
    path = DATA_DIR / project_id / "project.json"
    if not path.exists():
        raise FileNotFoundError(project_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(DATA_DIR.glob("*/project.json"), reverse=True):
        try:
            projects.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return projects

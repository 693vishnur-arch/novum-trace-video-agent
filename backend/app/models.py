from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Scene:
    index: int
    start: float
    end: float
    duration: float
    text: str
    clip_name: str | None = None
    role: str = "body"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderResult:
    project_id: str
    output_path: str
    duration: float
    scenes: list[Scene]
    generations_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scenes"] = [scene.to_dict() for scene in self.scenes]
        return data

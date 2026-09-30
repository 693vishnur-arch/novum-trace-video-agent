from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


@dataclass
class Scene:
    index: int
    start: float
    end: float
    duration: float
    text: str
    clip_name: str | None = None
    role: str = "body"
    words: list[WordTiming] = field(default_factory=list)

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

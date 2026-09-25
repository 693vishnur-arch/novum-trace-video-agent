from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GenerationBudget:
    maximum: int = 0
    used: int = 0

    def can_generate(self) -> bool:
        return self.used < self.maximum

    def consume(self) -> None:
        if not self.can_generate():
            raise RuntimeError("Generation budget exhausted")
        self.used += 1

    @property
    def remaining(self) -> int:
        return max(self.maximum - self.used, 0)

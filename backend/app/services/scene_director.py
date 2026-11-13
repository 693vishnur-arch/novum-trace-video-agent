"""Deterministic, auditable documentary scene planning.

Does not fabricate factual footage: synthetic scenes are always illustrations.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

CAMERAS = (
    "slow cinematic dolly forward",
    "smooth lateral tracking shot",
    "subtle handheld documentary push-in",
    "slow overhead camera movement",
    "controlled wide-to-close camera move",
)
EVENT_WORDS = {"reportedly", "arrested", "killed", "injured", "explosion", "election", "outage",
               "attack", "breach", "launched", "announced", "yesterday", "today", "breaking"}


@dataclass(frozen=True)
class VisualPlan:
    scene_index: int
    start: float
    end: float
    duration: float
    narration: str
    search_query: str
    ai_prompt: str
    camera: str
    visual_type: str
    source_requirement: str
    synthetic_label: str = "AI-generated illustration; not actual event footage"


def needs_authentic_source(text: str) -> bool:
    lowered = text.casefold()
    return bool(set(re.findall(r"[a-z]+", lowered)) & EVENT_WORDS) or bool(
        re.search(r"\b(?:19|20)\d{2}\b", lowered)
    )


def make_plan(scenes: list, title: str, *, mode: str = "hybrid",
              style: str = "photorealistic documentary") -> list[VisualPlan]:
    if mode not in {"ai", "authentic", "hybrid"}:
        raise ValueError("Unsupported documentary mode")
    result = []
    for scene in scenes:
        text = scene.text.strip()
        camera = CAMERAS[int(scene.index) % len(CAMERAS)]
        factual = needs_authentic_source(text)
        visual_type = "authentic" if mode == "authentic" or (mode == "hybrid" and factual) else "ai"
        search_query = " ".join([title.strip(), text])[:180]
        prompt = (
            f"{style}. Illustrative editorial b-roll only, not actual footage. "
            f"Topic: {title}. Scene: {text}. Camera: {camera}. "
            "Real-world physical lighting, credible environment, natural movement, "
            "no captions, no logos, no fabricated news evidence, no famous people's likenesses."
        )[:1000]
        result.append(VisualPlan(
            scene_index=int(scene.index), start=float(scene.start), end=float(scene.end),
            duration=float(scene.duration), narration=text, search_query=search_query,
            ai_prompt=prompt, camera=camera, visual_type=visual_type,
            source_requirement=("verified licensed authentic event asset" if factual
                                else "licensed reusable footage or transparently labeled illustration"),
        ))
    return result


def serialized(plans: list[VisualPlan]) -> list[dict]:
    return [asdict(plan) for plan in plans]

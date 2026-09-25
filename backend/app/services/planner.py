from __future__ import annotations

import math
import re
from pathlib import Path

from backend.app.config import DEFAULT_SCENE_SECONDS, MAX_SCENE_SECONDS, MIN_SCENE_SECONDS
from backend.app.models import Scene

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def normalize_script(script: str) -> str:
    return re.sub(r"\s+", " ", script.strip())


def split_sentences(script: str) -> list[str]:
    script = script.strip()
    if not script:
        return []
    pieces = [normalize_script(p) for p in SENTENCE_RE.split(script) if normalize_script(p)]
    return pieces


def chunk_script(script: str, target_scenes: int | None = None) -> list[str]:
    sentences = split_sentences(script)
    if not sentences:
        return []
    if target_scenes is None or target_scenes <= 0:
        return sentences
    if len(sentences) <= target_scenes:
        return sentences

    chunks: list[str] = []
    per = math.ceil(len(sentences) / target_scenes)
    for i in range(0, len(sentences), per):
        chunks.append(" ".join(sentences[i : i + per]))
    return chunks


def _weights(chunks: list[str]) -> list[float]:
    weights = []
    for chunk in chunks:
        words = re.findall(r"\b\w+\b", chunk)
        punctuation_pause = 1.0 + 0.2 * len(re.findall(r"[,;:]", chunk))
        weights.append(max(len(words) * punctuation_pause, 1.0))
    return weights


def _duration_plan(total_duration: float, count: int) -> list[float]:
    if count <= 0:
        count = max(1, round(total_duration / DEFAULT_SCENE_SECONDS))
    even = total_duration / count
    if even < MIN_SCENE_SECONDS:
        count = max(1, math.floor(total_duration / MIN_SCENE_SECONDS))
    elif even > MAX_SCENE_SECONDS:
        count = max(1, math.ceil(total_duration / MAX_SCENE_SECONDS))
    return [total_duration / count] * count


def plan_scenes(
    total_duration: float,
    script: str,
    clips: list[Path],
    hook: str = "",
    ending_question: str = "",
) -> list[Scene]:
    if total_duration <= 0:
        raise ValueError("Narration duration must be greater than zero")

    if script.strip():
        initial_target = max(1, round(total_duration / DEFAULT_SCENE_SECONDS))
        chunks = chunk_script(script, initial_target)
        weights = _weights(chunks)
        scale = total_duration / sum(weights)
        durations = [w * scale for w in weights]

        # Merge very short chunks into the previous chunk so edits do not flicker.
        merged_chunks: list[str] = []
        merged_durations: list[float] = []
        for text, duration in zip(chunks, durations):
            if duration < MIN_SCENE_SECONDS and merged_chunks:
                merged_chunks[-1] = f"{merged_chunks[-1]} {text}".strip()
                merged_durations[-1] += duration
            else:
                merged_chunks.append(text)
                merged_durations.append(duration)
        chunks = merged_chunks
        durations = merged_durations
    else:
        scene_count = len(clips) if clips else max(1, round(total_duration / DEFAULT_SCENE_SECONDS))
        durations = _duration_plan(total_duration, scene_count)
        chunks = [""] * len(durations)

    scenes: list[Scene] = []
    cursor = 0.0
    for idx, (text, duration) in enumerate(zip(chunks, durations)):
        if idx == len(durations) - 1:
            end = total_duration
            duration = end - cursor
        else:
            end = min(total_duration, cursor + duration)
        clip = clips[idx % len(clips)] if clips else None
        role = "hook" if idx == 0 else "body"
        scenes.append(
            Scene(
                index=idx,
                start=round(cursor, 3),
                end=round(end, 3),
                duration=round(end - cursor, 3),
                text=text,
                clip_name=clip.name if clip else None,
                role=role,
            )
        )
        cursor = end

    if scenes:
        scenes[-1].role = "ending"
    return scenes


def derive_hook(title: str, script: str, explicit_hook: str = "") -> str:
    if explicit_hook.strip():
        return explicit_hook.strip()
    sentences = split_sentences(script)
    if sentences:
        first = sentences[0]
        words = first.split()
        return " ".join(words[:8]).upper()
    return title.strip().upper()[:80]


def derive_ending(explicit: str = "") -> str:
    return explicit.strip() or "WHAT HAPPENS NEXT?"

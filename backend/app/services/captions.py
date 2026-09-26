from __future__ import annotations

import re
import textwrap
from pathlib import Path

from backend.app.models import Scene


def ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def ass_escape(text: str) -> str:
    # Escape user/script text while preserving intentional ASS line breaks.
    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("\n", r"\N")
    return text


def wrap_caption(text: str, width: int = 22, max_lines: int = 2) -> str:
    """Wrap text without dropping words or adding ellipses."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return ""

    current_width = max(width, 12)
    lines = textwrap.wrap(
        text,
        width=current_width,
        break_long_words=False,
        break_on_hyphens=False,
    )

    # For hooks/end cards, gently widen wrapping before allowing an extra line.
    while max_lines > 0 and len(lines) > max_lines and current_width < 34:
        current_width += 2
        lines = textwrap.wrap(
            text,
            width=current_width,
            break_long_words=False,
            break_on_hyphens=False,
        )

    return "\n".join(lines)


def split_caption_chunks(
    text: str,
    *,
    max_chars: int = 42,
    max_words: int = 7,
) -> list[str]:
    """Split scene text into short, readable caption beats.

    Every source word is preserved. Unlike the V1 caption path, this never
    truncates a sentence with "...".
    """
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []

    words = normalized.split(" ")
    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(" ".join(current))
            current = []

    for word in words:
        candidate = " ".join([*current, word])
        if current and (len(candidate) > max_chars or len(current) >= max_words):
            flush()

        current.append(word)
        stripped = word.rstrip('"\'”’)]}')
        strong_pause = stripped.endswith((".", "!", "?"))
        soft_pause = stripped.endswith((",", ";", ":"))

        if strong_pause and len(current) >= 3:
            flush()
        elif soft_pause and len(current) >= 5:
            flush()

    flush()

    # Avoid a distracting one-word final flash when a safe merge is possible.
    if len(chunks) >= 2 and len(chunks[-1].split()) <= 2:
        merged = f"{chunks[-2]} {chunks[-1]}"
        if len(merged) <= max_chars + 8 and len(merged.split()) <= max_words + 1:
            chunks[-2:] = [merged]

    return chunks


def _caption_events_for_scene(scene: Scene) -> list[tuple[float, float, str]]:
    chunks = split_caption_chunks(scene.text)
    if not chunks:
        return []

    start = float(scene.start)
    end = float(scene.end)
    available = max(end - start, 0.0)
    if available < 0.35:
        return []

    weights = [max(len(chunk.split()), 1) for chunk in chunks]
    total_weight = sum(weights)
    cursor = start
    events: list[tuple[float, float, str]] = []

    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        if index == len(chunks) - 1:
            chunk_end = end
        else:
            chunk_end = cursor + available * (weight / total_weight)

        # Keep timestamps monotonic after rounding and give each beat enough
        # screen time to avoid rapid flashes.
        chunk_end = min(max(chunk_end, cursor + 0.35), end)
        events.append((cursor, chunk_end, chunk))
        cursor = chunk_end

    return events


def build_ass(
    scenes: list[Scene],
    output: Path,
    hook: str,
    ending_question: str,
    total_duration: float,
    brand: str = "NOVUM TRACE",
) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,45,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,4,1,2,75,75,235,1
Style: Hook,DejaVu Sans,62,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,1,0,1,5,2,5,70,70,0,1
Style: Ending,DejaVu Sans,52,&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,1,0,1,5,2,5,70,70,0,1
Style: Brand,DejaVu Sans,32,&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,2,0,1,3,1,2,70,70,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    # Dynamic body captions: split long scene text into short timed beats.
    for scene in scenes:
        for start, end, chunk in _caption_events_for_scene(scene):
            text = ass_escape(wrap_caption(chunk, width=22, max_lines=2))
            events.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{text}"
            )

    if hook.strip():
        hook_end = min(3.0, total_duration)
        hook_text = ass_escape(wrap_caption(hook.upper(), width=18, max_lines=3))
        events.append(
            f"Dialogue: 2,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,{hook_text}"
        )

    if ending_question.strip() and total_duration > 1.0:
        ending_start = max(total_duration - 2.4, 0.0)
        ending_text = ass_escape(
            wrap_caption(ending_question.upper(), width=19, max_lines=3)
        )
        events.append(
            f"Dialogue: 3,{ass_time(ending_start)},{ass_time(total_duration)},Ending,,0,0,0,,{ending_text}"
        )
        events.append(
            f"Dialogue: 4,{ass_time(ending_start)},{ass_time(total_duration)},Brand,,0,0,0,,{ass_escape(brand)}"
        )

    output.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

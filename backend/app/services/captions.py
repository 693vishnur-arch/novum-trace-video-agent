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
    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("\n", r"\N")
    return text


def wrap_caption(text: str, width: int = 28, max_lines: int = 2) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return ""
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= max_lines:
        return r"\N".join(lines)
    # Keep captions compact by splitting long scene text over multiple events in the future.
    # For V1, display the first lines and add an ellipsis.
    lines = lines[:max_lines]
    if not lines[-1].endswith((".", "!", "?")):
        lines[-1] = lines[-1].rstrip(" ,;:") + "..."
    return r"\N".join(lines)


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
Style: Caption,DejaVu Sans,45,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,4,1,2,75,75,255,1
Style: Hook,DejaVu Sans,62,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,1,0,1,5,2,5,70,70,0,1
Style: Ending,DejaVu Sans,52,&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,1,0,1,5,2,5,70,70,0,1
Style: Brand,DejaVu Sans,32,&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,2,0,1,3,1,2,70,70,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    # Scene captions. Reserve the final 2.8 seconds for the ending card.
    ending_start = max(total_duration - 2.8, 0.0)
    for scene in scenes:
        if not scene.text.strip():
            continue
        start = scene.start
        end = min(scene.end, ending_start)
        if end - start < 0.35:
            continue
        text = ass_escape(wrap_caption(scene.text))
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
        ending_text = ass_escape(wrap_caption(ending_question.upper(), width=19, max_lines=3))
        events.append(
            f"Dialogue: 3,{ass_time(ending_start)},{ass_time(total_duration)},Ending,,0,0,0,,{ending_text}"
        )
        events.append(
            f"Dialogue: 4,{ass_time(ending_start)},{ass_time(total_duration)},Brand,,0,0,0,,{ass_escape(brand)}"
        )

    output.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

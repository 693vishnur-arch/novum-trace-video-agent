"""Measure speech on the same PCM timeline used by the renderer.

Inference runs in a child process so its memory is released before FFmpeg starts.
No audio is sent to a speech API and failed alignment never becomes guessed timing.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.models import WordTiming


class AlignmentError(ValueError):
    pass


def normalized(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def validate_words(words: list[WordTiming], duration: float) -> list[WordTiming]:
    if not words:
        raise AlignmentError("No speech was detected in the narration.")
    previous = 0.0
    for word in words:
        if (not word.text.strip() or not math.isfinite(word.start)
                or not math.isfinite(word.end) or word.start < previous - 0.02
                or word.start < 0 or word.end <= word.start
                or word.end > duration + 0.05):
            raise AlignmentError("Speech recognition returned invalid word timestamps.")
        word.start = max(previous, word.start)
        word.end = min(duration, word.end)
        if word.end <= word.start:
            raise AlignmentError("Speech recognition returned overlapping word timestamps.")
        previous = word.end
    return words


def match_script(script: str, spoken: list[WordTiming], duration: float) -> list[WordTiming]:
    """Retain script spelling, using recognized word boundaries as anchors.

Only small substitutions (e.g. OpenAI/Open AI or 24/twenty-four) may share
an observed speech span. Missing/extra speech or large mismatches fail explicitly.
"""
    validate_words(spoken, duration)
    tokens = script.split()
    if not tokens:
        return spoken
    a = [normalized(w) for w in tokens]
    b = [normalized(w.text) for w in spoken]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    if matched / max(len(a), len(b)) < 0.75:
        raise AlignmentError("The script does not closely match the narration. Check the script and audio, then retry.")
    result: list[WordTiming] = []
    for tag, i, j, x, y in matcher.get_opcodes():
        if tag == "equal":
            result.extend(WordTiming(tokens[k], spoken[x + k - i].start,
                                     spoken[x + k - i].end) for k in range(i, j))
            continue
        if (tag != "replace" or max(j - i, y - x) > 3
                or any(spoken[k].start - spoken[k - 1].end > 0.6 for k in range(x + 1, y))):
            raise AlignmentError("Some script words could not be aligned to the narration. Check for missing or extra words, then retry.")
        if j - i == y - x:
            result.extend(WordTiming(tokens[k], spoken[x + k - i].start,
                                     spoken[x + k - i].end) for k in range(i, j))
        else:
            # A spelling/tokenization difference is bounded by measured speech,
            # never spread over the full recording or a silence interval.
            start, end = spoken[x].start, spoken[y - 1].end
            step = (end - start) / (j - i)
            result.extend(WordTiming(tokens[k], start + (k - i) * step,
                                     start + (k - i + 1) * step) for k in range(i, j))
    return validate_words(result, duration)


def align_narration(audio: Path, script: str, duration: float, work_dir: Path) -> list[WordTiming]:
    request = work_dir / "alignment_request.json"
    response = work_dir / "alignment_response.json"
    request.write_text(json.dumps({"audio": str(audio.resolve()), "script": script}), encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, "-m", "backend.app.services.alignment", str(request.resolve()), str(response.resolve())],
            check=True, capture_output=True, text=True, timeout=900,
        )
        payload = json.loads(response.read_text(encoding="utf-8"))
        spoken = [WordTiming(**word) for word in payload]
        return match_script(script, spoken, duration)
    except (subprocess.SubprocessError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AlignmentError("Audio alignment failed. Check that the speech model is installed and enough memory is available, then retry.") from exc


def _worker(request: Path, response: Path) -> None:
    from faster_whisper import WhisperModel

    payload = json.loads(request.read_text(encoding="utf-8"))
    model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny.en"), device="cpu",
                         compute_type="int8", cpu_threads=1, num_workers=1)
    segments, _ = model.transcribe(
        payload["audio"], word_timestamps=True, beam_size=5,
        condition_on_previous_text=False, vad_filter=False,
    )
    words = [{"text": word.word.strip(), "start": word.start, "end": word.end}
             for segment in segments for word in (segment.words or [])
             if word.word.strip() and word.end > word.start]
    response.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), Path(sys.argv[2]))

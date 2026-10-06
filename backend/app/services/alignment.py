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
import wave
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.models import WordTiming


class AlignmentError(ValueError):
    pass


def normalized(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


_CONTRACTION_CANONICAL = {
    "i'm": "iam",
    "i've": "ihave",
    "i'll": "iwill",
    "i'd": "iwould",
    "you're": "youare",
    "you've": "youhave",
    "you'll": "youwill",
    "you'd": "youwould",
    "he's": "heis",
    "she's": "sheis",
    "it's": "itis",
    "we're": "weare",
    "we've": "wehave",
    "we'll": "wewill",
    "we'd": "wewould",
    "they're": "theyare",
    "they've": "theyhave",
    "they'll": "theywill",
    "they'd": "theywould",
    "that's": "thatis",
    "there's": "thereis",
    "what's": "whatis",
    "who's": "whois",
    "let's": "letus",
    "can't": "cannot",
    "won't": "willnot",
    "don't": "donot",
    "doesn't": "doesnot",
    "didn't": "didnot",
    "isn't": "isnot",
    "aren't": "arenot",
    "wasn't": "wasnot",
    "weren't": "werenot",
    "haven't": "havenot",
    "hasn't": "hasnot",
    "hadn't": "hadnot",
    "wouldn't": "wouldnot",
    "shouldn't": "shouldnot",
    "couldn't": "couldnot",
    "mustn't": "mustnot",
}


def _canonical_token(text: str) -> str:
    surface = text.casefold().replace("’", "'")
    surface = re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", surface)
    if surface in _CONTRACTION_CANONICAL:
        return _CONTRACTION_CANONICAL[surface]
    return normalized(text)


def _retokenize_exact(tokens: list[str], spoken: list[WordTiming]) -> list[WordTiming] | None:
    """Reconcile identical text with different word boundaries before diffing.

    Map character offsets within measured words, preserving pauses between them.
    Never merge a script word across a long silence.
    """
    a = [_canonical_token(token) for token in tokens]
    b = [_canonical_token(word.text) for word in spoken]
    if not all(a) or not all(b) or "".join(a) != "".join(b):
        return None
    spans = []
    offset = 0
    for text, word in zip(b, spoken):
        spans.append((offset, offset + len(text), word))
        offset += len(text)
    result = []
    offset = 0
    cursor = 0
    for token, text in zip(tokens, a):
        end_offset = offset + len(text)
        while spans[cursor][1] <= offset:
            cursor += 1
        last = cursor
        while spans[last][1] < end_offset:
            last += 1
        if any(spans[k][2].start - spans[k - 1][2].end > 0.6
               for k in range(cursor + 1, last + 1)):
            raise AlignmentError(f'Cannot align script word "{token}" across a long pause in the narration.')
        left, right, first_word = spans[cursor]
        start = first_word.start + (offset - left) / (right - left) * (first_word.end - first_word.start)
        left, right, last_word = spans[last]
        end = last_word.start + (end_offset - left) / (right - left) * (last_word.end - last_word.start)
        result.append(WordTiming(token, start, end))
        offset = end_offset
    return result


def _interpolate_missing_script_words(
    tokens: list[str],
    spoken: list[WordTiming],
    i: int,
    j: int,
    x: int,
) -> list[WordTiming] | None:
    """Recover a tiny ASR omission using the measured gap between anchor words.

    This is intentionally conservative: only one or two internal script words
    may be restored, there must be recognized speech on both sides, and the
    measured gap must be short enough to represent speech rather than a pause.
    """
    count = j - i
    if count < 1 or count > 2 or x <= 0 or x >= len(spoken):
        return None

    start = float(spoken[x - 1].end)
    end = float(spoken[x].start)
    gap = end - start
    if gap < 0.04 or gap > 1.0:
        return None

    weights = [max(len(normalized(token)), 1) for token in tokens[i:j]]
    total = sum(weights)
    cursor = start
    result: list[WordTiming] = []
    for offset, (token, weight) in enumerate(zip(tokens[i:j], weights)):
        token_end = end if offset == count - 1 else cursor + gap * (weight / total)
        if token_end <= cursor:
            return None
        result.append(WordTiming(token, cursor, token_end))
        cursor = token_end
    return result


def _is_repeated_asr_insert(
    script_tokens: list[str],
    inserted_tokens: list[str],
    script_index: int,
) -> bool:
    """Return true for a substantial ASR phrase that repeats earlier script text.

    Tiny speech models can hallucinate the previous sentence again during a
    pause. We only suppress insertions of at least four normalized words when
    that exact phrase already occurs before the current script position.
    """
    if len(inserted_tokens) < 4:
        return False
    length = len(inserted_tokens)

    # SequenceMatcher may choose the second copy of a duplicated phrase as the
    # real match, leaving the first copy as an insertion at the same script
    # position. In that case the inserted phrase equals the upcoming script.
    if script_tokens[script_index:script_index + length] == inserted_tokens:
        return True

    earliest = max(0, script_index - 40)
    latest = script_index - length
    for start in range(earliest, latest + 1):
        if script_tokens[start:start + length] == inserted_tokens:
            return True
    return False


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
    retokenized = _retokenize_exact(tokens, spoken)
    if retokenized is not None:
        return validate_words(retokenized, duration)
    a = [normalized(w) for w in tokens]
    b = [normalized(w.text) for w in spoken]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    token_ratio = matched / max(len(a), len(b))
    script_chars = "".join(_canonical_token(token) for token in tokens)
    spoken_chars = "".join(_canonical_token(word.text) for word in spoken)
    char_ratio = SequenceMatcher(None, script_chars, spoken_chars, autojunk=False).ratio()
    # Do not reject on the global similarity score before inspecting the
    # diff. A tiny speech model can duplicate a whole previous sentence, which
    # lowers the global score even though the remaining narration is correct.
    # Individual unexplainable replace/delete/insert opcodes below still fail.
    result: list[WordTiming] = []
    for tag, i, j, x, y in matcher.get_opcodes():
        if tag == "equal":
            result.extend(WordTiming(tokens[k], spoken[x + k - i].start,
                                     spoken[x + k - i].end) for k in range(i, j))
            continue
        if tag == "delete" and x == y and char_ratio >= 0.97:
            # Only recover an ASR omission when the entire narration otherwise
            # matches the script almost exactly. This avoids inventing words for
            # a genuinely different/short script while tolerating one missed
            # word in a long, matching ElevenLabs narration.
            restored = _interpolate_missing_script_words(tokens, spoken, i, j, x)
            if restored is not None:
                result.extend(restored)
                continue

        if tag == "insert" and i == j and _is_repeated_asr_insert(a, b[x:y], i):
            # Ignore a duplicated phrase hallucinated by the recognizer during
            # a pause; later script words keep their measured timestamps.
            continue

        if (tag != "replace" or max(j - i, y - x) > 3
                or any(spoken[k].start - spoken[k - 1].end > 0.6 for k in range(x + 1, y))):
            expected = " ".join(tokens[i:j]) or "(no words)"
            recognized = " ".join(word.text for word in spoken[x:y]) or "(no words)"
            context = " ".join(tokens[max(0, i - 3):min(len(tokens), j + 3)])
            raise AlignmentError(
                f'Script/audio mismatch near "{context}": script "{expected}"; '
                f'recognized "{recognized}". Check this passage in the audio and script, then retry.'
            )
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
    except subprocess.CalledProcessError as exc:
        reason = ("The speech worker was killed, possibly because the server ran out of memory."
                  if exc.returncode in {-9, 137} else
                  f"The speech worker exited with code {exc.returncode}. Check the server logs.")
        print(f"Audio alignment worker failed: {exc.stderr}", file=sys.stderr, flush=True)
        raise AlignmentError(f"Audio alignment failed. {reason}") from exc
    except (subprocess.SubprocessError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AlignmentError("Audio alignment failed. Check that the speech model is installed and enough memory is available, then retry.") from exc


def _transcribe_chunks(model, audio: Path) -> list[dict]:
    """Transcribe long narration with overlapping 30-second windows.

    A previous implementation resumed each window at the last accepted word.
    That could place a real word exactly on the next Whisper window boundary,
    where tiny.en occasionally omitted it. Use a fixed 20-second stride with
    five seconds of protected overlap on each side instead.

    Words are assigned by midpoint to non-overlapping safe regions:
      first window:   0s <= midpoint < 25s
      middle windows: 5s <= midpoint < 25s
      final window:   5s <= midpoint to end

    This keeps every output word on the original PCM timeline while ensuring
    boundary speech is decoded with several seconds of context on both sides.
    """
    import numpy as np

    window_seconds = 30
    stride_seconds = 20
    guard_seconds = 5

    words = []
    with wave.open(str(audio), "rb") as source:
        rate = source.getframerate()
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or rate != 16000:
            raise AlignmentError("Alignment requires mono 16 kHz PCM audio.")

        total = source.getnframes()
        cursor = 0
        while cursor < total:
            source.setpos(cursor)
            frames = min(window_seconds * rate, total - cursor)
            samples = np.frombuffer(source.readframes(frames), dtype="<i2").astype(np.float32)
            samples /= 32768.0

            segments, _ = model.transcribe(
                samples,
                word_timestamps=True,
                beam_size=5,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 250},
            )

            final = cursor + frames >= total
            lower_midpoint = 0.0 if cursor == 0 else guard_seconds
            upper_midpoint = float("inf") if final else window_seconds - guard_seconds

            for segment in segments:
                for word in segment.words or []:
                    text = word.word.strip()
                    if not (text and math.isfinite(word.start) and math.isfinite(word.end)
                            and 0 <= word.start < word.end <= frames / rate + 0.05):
                        continue
                    midpoint = (word.start + word.end) / 2.0
                    if midpoint < lower_midpoint or midpoint >= upper_midpoint:
                        continue
                    words.append({
                        "text": text,
                        "start": cursor / rate + word.start,
                        "end": cursor / rate + word.end,
                    })

            if final:
                break
            cursor += stride_seconds * rate

    return words


def _worker(request: Path, response: Path) -> None:
    from faster_whisper import WhisperModel

    payload = json.loads(request.read_text(encoding="utf-8"))
    pcm = request.with_name("alignment_mono.wav")
    try:
        # FFmpeg streams to disk; never decode the entire stereo narration in RAM.
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", "1",
            "-i", payload["audio"], "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(pcm),
        ], check=True, capture_output=True, text=True, timeout=120)
        model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny.en"), device="cpu",
                             compute_type="int8", cpu_threads=1, num_workers=1)
        words = _transcribe_chunks(model, pcm)
        response.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    finally:
        pcm.unlink(missing_ok=True)


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), Path(sys.argv[2]))

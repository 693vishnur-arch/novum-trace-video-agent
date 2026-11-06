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
from array import array
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
    # Speech recognizers can spell the model name "Sol" as "sole" or
    # "soul". These homophones are equivalent for alignment only; captions
    # retain the exact spelling in the script.
    if surface in {"sol", "soul"}:
        return "sole"
    # Whisper sometimes adds a possessive to a numeric model-version fragment:
    # "GPT-6.1 Sol" is transcribed as "GPT 6 .1's soul". The leading dot on
    # ".1's" was stripped above, so normalize a number followed by "'s".
    if re.fullmatch(r"\d+(?:\.\d+)?'s", surface):
        return normalized(surface[:-2])
    return normalized(text)


def _script_tokens(script: str) -> list[str]:
    """Split script for alignment without treating standalone punctuation as speech.

    ElevenLabs renders standalone punctuation such as an em dash as a pause, not
    a spoken word. Attach punctuation-only tokens to the nearest lexical token
    so captions keep the original punctuation while alignment only compares
    actual spoken content.
    """
    raw = script.split()
    if not raw:
        return []

    tokens: list[str] = []
    pending_prefix: list[str] = []
    for token in raw:
        if normalized(token):
            if pending_prefix:
                token = " ".join([*pending_prefix, token])
                pending_prefix = []
            tokens.append(token)
            continue
        if tokens:
            tokens[-1] = f"{tokens[-1]} {token}"
        else:
            pending_prefix.append(token)

    if pending_prefix and tokens:
        tokens[-1] = f"{tokens[-1]} {' '.join(pending_prefix)}"
    return tokens


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
    # Tiny Whisper can omit a word while assigning almost the whole spoken
    # interval to its neighboring tokens. A very small positive gap is still
    # usable when match_script has already established strong textual anchors.
    if gap < 0.005 or gap > 1.0:
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


def _local_anchor_count(
    script_tokens: list[str],
    spoken_tokens: list[str],
    i: int,
    j: int,
    x: int,
) -> int:
    """Find a short exact context on both sides of a one/two-word omission.

    Prefer three exact neighbors; accept two on both sides when tiny.en also
    garbles another nearby token. Never apply this to short narrations.
    """
    if len(script_tokens) < 30 or not 1 <= j - i <= 2:
        return 0
    for count in (3, 2):
        if (i >= count and x >= count
                and j + count <= len(script_tokens)
                and x + count <= len(spoken_tokens)
                and script_tokens[i - count:i] == spoken_tokens[x - count:x]
                and script_tokens[j:j + count] == spoken_tokens[x:x + count]):
            return count
    return 0


def _redistribute_local_anchor_span(
    tokens: list[str],
    spoken: list[WordTiming],
    i: int,
    j: int,
    x: int,
    *,
    anchor_words: int = 3,
) -> tuple[int, list[WordTiming]] | None:
    """Re-time a short locally anchored passage when Whisper drops a word.

    If there is no literal timestamp gap for the omitted word, redistribute the
    measured span covering exact words before and after the omission. This
    keeps timing local to the real audio instead of inventing a global estimate.
    """
    if i < anchor_words or x < anchor_words or x + anchor_words > len(spoken):
        return None
    start_script = i - anchor_words
    end_script = j + anchor_words
    start_spoken = x - anchor_words
    end_spoken = x + anchor_words
    # A long silence between anchors is not evidence of a missed word.
    if any(spoken[k].start - spoken[k - 1].end > 0.6
           for k in range(start_spoken + 1, end_spoken)):
        return None
    start = float(spoken[start_spoken].start)
    end = float(spoken[end_spoken - 1].end)
    if not (math.isfinite(start) and math.isfinite(end)
            and 0.2 < end - start <= 8.0):
        return None

    local_tokens = tokens[start_script:end_script]
    weights = [max(len(normalized(token)), 1) for token in local_tokens]
    total = sum(weights)
    cursor = start
    rebuilt: list[WordTiming] = []
    for offset, (token, weight) in enumerate(zip(local_tokens, weights)):
        token_end = end if offset == len(local_tokens) - 1 else cursor + (end - start) * (weight / total)
        if token_end <= cursor:
            return None
        rebuilt.append(WordTiming(token, cursor, token_end))
        cursor = token_end
    return anchor_words, rebuilt


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


def _is_tiny_trailing_asr_insert(
    spoken: list[WordTiming],
    x: int,
    y: int,
    script_index: int,
    script_length: int,
    silent_tail_verified: bool = False,
) -> bool:
    """Ignore only a single tiny recognizer hallucination after the script ends.

    The caller must verify silence in the candidate's measured audio interval.
    Text similarity or short duration alone cannot authorize dropping speech.
    """
    if not silent_tail_verified or script_index != script_length or y - x != 1:
        return False
    word = spoken[x]
    duration = float(word.end) - float(word.start)
    return math.isfinite(duration) and 0.0 < duration <= 2.0


def _silent_trailing_word(audio: Path, script: str, spoken: list[WordTiming], duration: float) -> bool:
    """Confirm one extra trailing ASR token lies entirely in measured PCM silence.

    Text similarity cannot distinguish real extra speech from hallucination.
    Require an alignable prefix, exact final anchors, and quiet samples across
    the candidate interval and the preceding 80 ms. Fail closed for other audio
    formats or unreadable samples. The production caller provides PCM WAV.
    """
    tokens = _script_tokens(script)
    if len(tokens) < 3 or len(spoken) < 4:
        return False
    tail = spoken[-1]
    if not (0.08 <= tail.end - tail.start <= 2.0):
        return False
    if not (0 < len(normalized(tail.text)) <= 12):
        return False
    if [_canonical_token(w.text) for w in spoken[-4:-1]] != [
        _canonical_token(w) for w in tokens[-3:]
    ]:
        return False
    try:
        # Validate every other difference with the usual omission and mismatch
        # rules. Do not require a global 99% token score: valid split acronyms
        # and compound words can lower that score on otherwise matching audio.
        match_script(script, spoken[:-1], duration)
        with wave.open(str(audio), "rb") as source:
            if source.getsampwidth() != 2 or source.getcomptype() != "NONE":
                return False
            rate = source.getframerate()
            start = max(0, int((tail.start - 0.08) * rate))
            end = int(tail.end * rate)
            if end > source.getnframes() or start >= end:
                return False
            source.setpos(start)
            samples = array("h", source.readframes(end - start))
            if sys.byteorder != "little":
                samples.byteswap()
            if len(samples) != (end - start) * source.getnchannels():
                return False
            rms = math.sqrt(sum(int(s) ** 2 for s in samples) / len(samples))
            # Both peak and RMS must be low, so a short spoken burst cannot be
            # hidden by averaging it with a longer stretch of silence.
            return max(abs(int(s)) for s in samples) <= 328 and rms <= 104
    except (AlignmentError, OSError, EOFError, wave.Error, ValueError):
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


def match_script(script: str, spoken: list[WordTiming], duration: float, *,
                 silent_tail_verified: bool = False) -> list[WordTiming]:
    """Retain script spelling, using recognized word boundaries as anchors.

Only small substitutions (e.g. OpenAI/Open AI or 24/twenty-four) may share
an observed speech span. Missing/extra speech or large mismatches fail explicitly.
"""
    validate_words(spoken, duration)
    tokens = _script_tokens(script)
    if not tokens:
        return spoken
    retokenized = _retokenize_exact(tokens, spoken)
    if retokenized is not None:
        return validate_words(retokenized, duration)
    a = [_canonical_token(w) for w in tokens]
    b = [_canonical_token(w.text) for w in spoken]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    script_chars = "".join(_canonical_token(token) for token in tokens)
    spoken_chars = "".join(_canonical_token(word.text) for word in spoken)
    char_ratio = SequenceMatcher(None, script_chars, spoken_chars, autojunk=False).ratio()
    # Do not reject on the global similarity score before inspecting the
    # diff. A tiny speech model can duplicate a whole previous sentence, which
    # lowers the global score even though the remaining narration is correct.
    # Individual unexplainable replace/delete/insert opcodes below still fail.
    result: list[WordTiming] = []
    skip_script_until = -1
    for tag, i, j, x, y in matcher.get_opcodes():
        if j <= skip_script_until:
            continue
        if i < skip_script_until < j and tag == "equal":
            offset = skip_script_until - i
            i += offset
            x += offset
        if tag == "equal":
            result.extend(WordTiming(tokens[k], spoken[x + k - i].start,
                                     spoken[x + k - i].end) for k in range(i, j))
            continue
        anchor_count = _local_anchor_count(a, b, i, j, x)
        if tag == "delete" and x == y and (
            char_ratio >= 0.97 or anchor_count
        ):
            # Recover a tiny ASR omission when either the whole narration is an
            # almost-exact match or this specific passage has strong exact
            # anchors on both sides.
            restored = _interpolate_missing_script_words(tokens, spoken, i, j, x)
            if restored is not None:
                result.extend(restored)
                continue

            # Tiny Whisper sometimes gives the neighboring words touching
            # timestamps, leaving no literal gap for a word that is clearly
            # present in the audio. When local exact anchors exist on both sides,
            # rebuild only that local passage from its measured outer span.
            if anchor_count:
                local = _redistribute_local_anchor_span(
                    tokens, spoken, i, j, x, anchor_words=anchor_count
                )
                if local is not None:
                    replace_count, rebuilt = local
                    if len(result) >= replace_count:
                        del result[-replace_count:]
                        result.extend(rebuilt)
                        skip_script_until = j + replace_count
                    continue

        if tag == "insert" and i == j and _is_repeated_asr_insert(a, b[x:y], i):
            # Ignore a duplicated phrase hallucinated by the recognizer during
            # a pause; later script words keep their measured timestamps.
            continue

        if tag == "insert" and i == j and _is_tiny_trailing_asr_insert(
            spoken, x, y, i, len(a), silent_tail_verified
        ):
            # tiny.en can hallucinate one short word after otherwise exact
            # narration has ended. Do not let that recognizer-only tail block
            # rendering; larger or less-similar extra speech still fails.
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
        silent_tail_verified = _silent_trailing_word(audio, script, spoken, duration)
        return match_script(script, spoken, duration, silent_tail_verified=silent_tail_verified)
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

    # Different overlapping Whisper windows can shift boundary timestamps by a
    # few hundred milliseconds. Sort on the original PCM timeline, collapse
    # duplicate estimates of the same spoken word, and trim tiny cross-window
    # overlaps so validate_words receives a strictly monotonic sequence.
    words.sort(key=lambda item: (float(item["start"]), float(item["end"])))
    cleaned: list[dict] = []
    for item in words:
        if not cleaned:
            cleaned.append(item)
            continue

        previous = cleaned[-1]
        prev_mid = (float(previous["start"]) + float(previous["end"])) / 2.0
        item_mid = (float(item["start"]) + float(item["end"])) / 2.0
        if (normalized(str(previous["text"])) == normalized(str(item["text"]))
                and abs(item_mid - prev_mid) < 0.8):
            # Same boundary word recognized by both overlapping windows.
            continue

        if float(item["start"]) < float(previous["end"]):
            if float(item["end"]) <= float(previous["end"]):
                # Fully enclosed timestamp is another overlap artifact.
                continue
            item = dict(item)
            item["start"] = float(previous["end"])
        if float(item["end"]) > float(item["start"]):
            cleaned.append(item)

    return cleaned


def _recheck_asr_insertions(model, audio: Path, words: list[dict], script: str) -> list[dict]:
    """Re-decode one-word insertions with local audio and unprompted context.

    A word can straddle the final phoneme rather than silence, so signal level
    alone cannot verify it. Remove it only when a fresh decode independently
    recognizes the surrounding script anchors without the inserted token.
    Original timestamps for all retained words are preserved.
    """
    import numpy as np

    tokens = _script_tokens(script)
    if len(tokens) < 6 or len(words) < 6:
        return words
    expected = [_canonical_token(t) for t in tokens]
    actual = [_canonical_token(str(w["text"])) for w in words]
    matcher = SequenceMatcher(None, expected, actual, autojunk=False)
    removals: set[int] = set()
    attempts = 0
    with wave.open(str(audio), "rb") as source:
        rate = source.getframerate()
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or rate != 16000:
            return words
        duration = source.getnframes() / rate
        for tag, i, j, x, y in matcher.get_opcodes():
            if tag != "insert" or y - x != 1 or i != j or x < 4:
                continue
            tail = i == len(tokens) and y == len(words)
            left = min(4, i, x)
            right = 0 if tail else min(4, len(tokens) - i, len(words) - y)
            if left < 4 or (not tail and right < 4):
                continue
            # Both sides must already have exact anchors on the original
            # timeline. Never re-decode an unanchored or large mismatch.
            if (expected[i-left:i] != actual[x-left:x]
                    or expected[j:j+right] != actual[y:y+right]):
                continue
            if not 0 < float(words[x]["end"]) - float(words[x]["start"]) <= 2:
                continue
            if attempts >= 3:
                break
            attempts += 1
            first = x - left
            last = y + right - 1 if right else x - 1
            start = max(0.0, float(words[first]["start"]) - 1.0)
            if tail:
                start = max(0.0, duration - 10.0)
            end = duration if tail else min(duration, float(words[last]["end"]) + 1.0)
            if end - start > 15:
                continue
            source.setpos(int(start * rate))
            samples = np.frombuffer(source.readframes(int((end-start)*rate)),
                                    dtype="<i2").astype(np.float32) / 32768.0
            segments, _ = model.transcribe(
                samples, word_timestamps=True, beam_size=5,
                condition_on_previous_text=False, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 250},
            )
            local = [w for segment in segments for w in segment.words or []
                     if w.word.strip() and math.isfinite(w.start) and math.isfinite(w.end)
                     and 0 <= w.start < w.end <= end-start+0.05]
            local_tokens = [_canonical_token(w.word) for w in local]
            context = expected[i-left:j+right]
            for offset in range(len(local_tokens)-len(context)+1):
                stop = offset + len(context)
                candidate = local_tokens[offset:stop]
                differences = [(a, b) for a, b in zip(context, candidate) if a != b]
                # Keep at least seven of eight middle anchors exact. A fresh
                # decode may spell an unfamiliar name differently (Anthropic /
                # Entropic), but it must not add or omit a context word.
                if differences and not (
                    not tail and len(differences) == 1
                    and SequenceMatcher(None, *differences[0], autojunk=False).ratio() >= .75
                ):
                    continue
                if tail and stop != len(local):
                    continue  # Independent decode still heard extra speech.
                if (abs(start + local[offset].start - float(words[first]["start"])) > .6
                        or abs(start + local[stop-1].end - float(words[last]["end"])) > (.15 if tail else .6)):
                    continue
                if tail:
                    # A decoder can itself omit a real extra word. Require
                    # quiet PCM after the independently measured final word,
                    # allowing only 80 ms for its fricative/release. Unlike the
                    # old test, this does not demand silence under the final /s/.
                    after = min(len(samples), int((local[stop-1].end + .08) * rate))
                    residual = samples[after:]
                    if len(residual) < int(.08 * rate):
                        continue
                    if (float(np.max(np.abs(residual))) > .01
                            or float(np.sqrt(np.mean(residual ** 2))) > .0032):
                        continue
                removals.add(x)
                break
    return [w for index, w in enumerate(words) if index not in removals]


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
        words = _recheck_asr_insertions(model, pcm, words, payload.get("script", ""))
        response.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    finally:
        pcm.unlink(missing_ok=True)


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), Path(sys.argv[2]))

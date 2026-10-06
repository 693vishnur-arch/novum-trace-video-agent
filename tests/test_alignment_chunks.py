import wave
from types import SimpleNamespace

import pytest

from backend.app.services.alignment import _transcribe_chunks


def audio_file(tmp_path, seconds):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(seconds):
            output.writeframes(b"\0\0" * 16000)
    return path


def word(text, start, end):
    return SimpleNamespace(word=text, start=start, end=end)


def test_long_audio_is_bounded_and_preserves_boundary_words(tmp_path):
    calls = []
    class Model:
        def transcribe(self, samples, **kwargs):
            calls.append(len(samples))
            if len(calls) == 1:
                words = [word("first", 1, 2), word("edge", 24, 24.8),
                         word("crossing", 24.9, 25.4)]
            elif len(calls) == 2:
                words = [word("crossing", .1, .6), word("later", 24, 24.8)]
            else:
                words = [word("last", 10, 11)]
            return iter([SimpleNamespace(words=words)]), None
    result = _transcribe_chunks(Model(), audio_file(tmp_path, 65))
    assert max(calls) <= 30 * 16000
    assert [w["text"] for w in result] == ["first", "edge", "crossing", "later", "last"]
    assert result[2]["start"] == pytest.approx(24.9)
    assert result[-1]["end"] == pytest.approx(60.6)


def test_ten_minutes_of_silence_advances_without_full_audio_allocation(tmp_path):
    calls = []
    class Model:
        def transcribe(self, samples, **kwargs):
            calls.append(len(samples))
            return iter([]), None
    assert _transcribe_chunks(Model(), audio_file(tmp_path, 600)) == []
    assert len(calls) == 24
    assert max(calls) == 30 * 16000


def test_short_audio_keeps_last_word(tmp_path):
    class Model:
        def transcribe(self, samples, **kwargs):
            return iter([SimpleNamespace(words=[word("end", 3.5, 4)])]), None
    assert _transcribe_chunks(Model(), audio_file(tmp_path, 4)) == [
        {"text": "end", "start": 3.5, "end": 4}]

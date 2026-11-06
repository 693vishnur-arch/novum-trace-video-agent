"""Trailing recognizer tokens need audio evidence, never similarity alone."""
import json
import math
import wave
from array import array

import pytest

from backend.app.models import WordTiming
from backend.app.services.alignment import AlignmentError, align_narration, match_script


SCRIPT = 'Follow Novum Trace for AI explained beyond the headlines.'


def render_fixture(tmp_path, monkeypatch, *, speech=False, split_ai=True,
                   extra=('much.',), tail_length=1.1, missing_audio=False):
    text = SCRIPT.replace(' AI ', ' A I ') if split_ai else SCRIPT
    words = [WordTiming(w, .2 + i * .3, .4 + i * .3)
             for i, w in enumerate(text.split())]
    start = words[-1].end + .2
    for i, word in enumerate(extra):
        words.append(WordTiming(word, start + i * (tail_length + .1),
                                start + i * (tail_length + .1) + tail_length))
    duration = words[-1].end + .2
    audio = tmp_path / 'narration.wav'
    rate = 16000
    samples = array('h', [0] * math.ceil(duration * rate))
    # A measured signal for the script, followed by silence or genuine speech.
    for word in words[:len(text.split())] + (words[len(text.split()):] if speech else []):
        for i in range(int(word.start * rate), int(word.end * rate)):
            samples[i] = int(6000 * math.sin(i * .12))
    if not missing_audio:
        with wave.open(str(audio), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(samples.tobytes())

    def worker(*args, **kwargs):
        (tmp_path / 'alignment_response.json').write_text(json.dumps([
            {'text': w.text, 'start': w.start, 'end': w.end} for w in words
        ]))
    monkeypatch.setattr('backend.app.services.alignment.subprocess.run', worker)
    return audio, duration, words


def test_silent_tail_with_split_acronym_and_long_asr_span(tmp_path, monkeypatch):
    audio, duration, words = render_fixture(tmp_path, monkeypatch)
    aligned = align_narration(audio, SCRIPT, duration, tmp_path)
    assert [w.text for w in aligned] == SCRIPT.split()
    assert aligned[-1].end == words[-2].end
    assert aligned[-3].start == words[-4].start


@pytest.mark.parametrize('split_ai', [True, False])
def test_real_extra_spoken_word_still_fails(tmp_path, monkeypatch, split_ai):
    audio, duration, _ = render_fixture(tmp_path, monkeypatch, speech=True,
                                      split_ai=split_ai, tail_length=.3)
    with pytest.raises(AlignmentError, match='much'):
        align_narration(audio, SCRIPT, duration, tmp_path)


def test_multiple_extra_words_still_fail(tmp_path, monkeypatch):
    audio, duration, _ = render_fixture(tmp_path, monkeypatch, extra=('thank', 'you'))
    with pytest.raises(AlignmentError):
        align_narration(audio, SCRIPT, duration, tmp_path)


def test_unreadable_audio_cannot_authorize_tail_removal(tmp_path, monkeypatch):
    audio, duration, _ = render_fixture(tmp_path, monkeypatch, missing_audio=True)
    with pytest.raises(AlignmentError):
        align_narration(audio, SCRIPT, duration, tmp_path)


def test_text_similarity_alone_cannot_ignore_real_short_tail():
    script = ' '.join(['word'] * 120) + ' beyond the headlines.'
    words = [WordTiming(w, i * .3, i * .3 + .2)
             for i, w in enumerate((script + ' much.').split())]
    with pytest.raises(AlignmentError, match='much'):
        match_script(script, words, 40)

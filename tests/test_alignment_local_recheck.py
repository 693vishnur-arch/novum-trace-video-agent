"""Independent, bounded audio rechecks for anchored ASR insertions."""
from types import SimpleNamespace
import wave

import pytest

from backend.app.models import WordTiming
from backend.app.services.alignment import _recheck_asr_insertions, match_script, AlignmentError


def pcm(tmp_path, duration=12, silence_after=10.67):
    path = tmp_path / 'mono.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        count = int(silence_after * 16000)
        wav.writeframes(b'\x20\x10' * count + b'\0\0' * (duration * 16000 - count))
    return path


def fake_model(words):
    calls = []
    class Model:
        def transcribe(self, samples, **kwargs):
            calls.append((len(samples), kwargs))
            return iter([SimpleNamespace(words=[SimpleNamespace(
                word=w['text'], start=w['start'], end=w['end']) for w in words])]), None
    return Model(), calls


@pytest.mark.parametrize('extra', ['much.', 'Thanks.'])
def test_final_phoneme_hallucination_rechecked_against_actual_audio(tmp_path, extra):
    # Reproduced MP3 timestamps: the inserted token overlaps the final /s/.
    # This cannot pass the silence-only check. A fresh final-sentence decode
    # independently ends at headlines, with real measured timestamps.
    script = 'Follow Novum Trace for AI explained beyond the headlines.'
    words = [dict(text=t, start=8+i*.3, end=8.2+i*.3)
             for i, t in enumerate(script.split())]
    words.append(dict(text=extra, start=words[-1]['end'], end=words[-1]['end']+.02))
    model, calls = fake_model([{**w, 'start':w['start']-2, 'end':w['end']-2}
                               for w in words[:-1]])
    result = _recheck_asr_insertions(model, pcm(tmp_path), words, script)
    assert result == words[:-1]
    assert match_script(script, [WordTiming(**w) for w in result], 12)[-1].end == words[-2]['end']
    assert len(calls) == 1 and calls[0][0] <= 15*16000
    assert 'initial_prompt' not in calls[0][1]


def test_real_extra_narration_survives_independent_recheck(tmp_path):
    script = 'Follow Novum Trace for AI explained beyond the headlines.'
    words = [dict(text=t, start=8+i*.3, end=8.2+i*.3)
             for i, t in enumerate((script+' much.').split())]
    model, _ = fake_model([{**w, 'start':w['start']-2, 'end':w['end']-2} for w in words])
    result = _recheck_asr_insertions(model, pcm(tmp_path), words, script)
    assert result == words
    with pytest.raises(AlignmentError):
        match_script(script, [WordTiming(**w) for w in result], 12)


def test_middle_split_proper_name_has_independent_anchors(tmp_path):
    script = 'examined internal data at Anthropic the company behind Claude today'
    words = [dict(text=t, start=2+i*.3, end=2.2+i*.3)
             for i,t in enumerate(script.replace('Anthropic', 'an Anthropic').split())]
    decoded = script.replace('Anthropic','Entropic').split()
    local = [dict(text=t, start=1+i*.3, end=1.2+i*.3) for i,t in enumerate(decoded)]
    model, _ = fake_model(local)
    result = _recheck_asr_insertions(model, pcm(tmp_path), words, script)
    assert [w['text'] for w in result] == script.split()
    assert result[-1] is words[-1]


def test_large_unanchored_mismatch_does_not_invoke_recheck(tmp_path):
    words = [dict(text=t, start=2+i*.3, end=2.2+i*.3)
             for i,t in enumerate('this is completely unrelated spoken narration with extra words'.split())]
    model, calls = fake_model([])
    assert _recheck_asr_insertions(model, pcm(tmp_path), words,
                                  'Follow Novum Trace for AI explained beyond the headlines.') == words
    assert not calls


def test_second_decode_omitting_real_tail_cannot_override_pcm_speech(tmp_path):
    script = 'Follow Novum Trace for AI explained beyond the headlines.'
    words = [dict(text=t, start=8+i*.3, end=8.2+i*.3)
             for i,t in enumerate((script+' much.').split())]
    model, _ = fake_model([{**w, 'start':w['start']-2, 'end':w['end']-2}
                           for w in words[:-1]])
    result = _recheck_asr_insertions(model, pcm(tmp_path, silence_after=11.5), words, script)
    assert result == words

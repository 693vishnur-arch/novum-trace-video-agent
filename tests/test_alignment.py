import math
import subprocess

import pytest

from backend.app.models import WordTiming
from backend.app.services.alignment import AlignmentError, align_narration, match_script, validate_words
from backend.app.services.captions import _caption_events_for_scene, ass_time, build_ass
from backend.app.services.planner import plan_aligned_scenes
from backend.app.services.stock import build_review_queries
from backend.app.services import renderer


def measured(text, start=0.8, step=0.4):
    return [WordTiming(word, start + i * step, start + i * step + 0.2)
            for i, word in enumerate(text.split())]


def test_long_pause_moves_scene_and_captions_with_speech():
    script = "One short sentence. Another short sentence."
    words = measured("One short sentence.") + measured("Another short sentence.", start=8.0)
    scenes = plan_aligned_scenes(12, match_script(script, words, 12), script, [], 2)
    assert scenes[0].start == 0
    assert scenes[0].end == scenes[1].start == 8
    assert scenes[-1].end == 12
    assert _caption_events_for_scene(scenes[0]) == [(0.8, 1.8, "One short sentence.")]
    assert _caption_events_for_scene(scenes[1])[0][0] == 8


def test_pause_inside_sentence_splits_caption():
    words = measured("This comes first") + measured("and this comes later.", start=6)
    scenes = plan_aligned_scenes(9, words, "This comes first and this comes later.", [])
    events = _caption_events_for_scene(scenes[0])
    assert events[0][1] < 3
    assert events[1][0] == 6


def test_spelling_is_preserved_without_moving_measured_words():
    words = measured("Open AI works all day and all night.")
    aligned = match_script("OpenAI works all day and all night.", words, 5)
    assert aligned[0].text == "OpenAI"
    assert aligned[0].start == words[0].start
    assert aligned[0].end == words[1].end
    assert aligned[1].start == words[2].start


def test_split_acronym_is_retokenized_without_failure():
    words = measured("A I can work all day.")
    aligned = match_script("AI can work all day.", words, 5)
    assert aligned[0].text == "AI"
    assert aligned[0].start == words[0].start
    assert aligned[0].end == words[1].end
    assert aligned[1].text == "can"


def test_contraction_tokenization_difference_is_allowed():
    words = measured("It is already working.")
    aligned = match_script("It's already working.", words, 5)
    assert [word.text for word in aligned] == ["It's", "already", "working."]
    assert aligned[0].start == words[0].start
    assert aligned[0].end == words[1].end


def test_missing_script_word_reports_exact_mismatch():
    words = measured("Google sent chips into orbit today.")
    with pytest.raises(AlignmentError) as exc:
        match_script("Google sent AI chips into orbit today.", words, 8)
    message = str(exc.value)
    assert "Script/audio mismatch near" in message
    assert 'script "AI"' in message
    assert 'recognized "(no words)"' in message


@pytest.mark.parametrize("script", ["An entirely unrelated narration.", "One two three missing four five six seven."])
def test_mismatched_script_does_not_get_estimated_timestamps(script):
    with pytest.raises(AlignmentError):
        match_script(script, measured("One two three four five six seven."), 8)


@pytest.mark.parametrize("words", [[], [WordTiming("bad", math.nan, 2)],
                                     [WordTiming("bad", 2, 1)],
                                     [WordTiming("bad", 0, 30)]])
def test_invalid_recognition_is_rejected(words):
    with pytest.raises(AlignmentError):
        validate_words(words, 5)


def test_worker_failure_is_actionable(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("alignment", 900)
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(AlignmentError, match="Audio alignment failed"):
        align_narration(tmp_path / "voice.wav", "hello", 4, tmp_path)


def test_review_and_render_keep_identical_scene_indices():
    script = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine."
    scenes = plan_aligned_scenes(12, measured(script), script, [], 8)
    queries = build_review_queries(script, "Test", max_clips=8)
    assert [(s.index, s.text) for s in scenes] == [(q["scene_index"], q["text"]) for q in queries]


def test_ending_question_uses_speech_onset(tmp_path):
    script = "This is the story. Would you trust it?"
    words = measured("This is the story.") + measured("Would you trust it?", start=7)
    scenes = plan_aligned_scenes(12, words, script, [])
    output = tmp_path / "captions.ass"
    build_ass(scenes, output, "Hook", "Would you trust it?", 12)
    assert "Dialogue: 3,0:00:07.00,0:00:12.00,Ending" in output.read_text()


def test_absolute_frame_boundaries_do_not_accumulate_rounding(monkeypatch, tmp_path):
    script = "One. Two. Three. Four. Five. Six. Seven. Eight."
    words = measured(script, start=0.017, step=1.019)
    scenes = plan_aligned_scenes(9.013, words, script, [], 8)
    durations = []
    commands = []
    monkeypatch.setattr(renderer, "_render_scene", lambda src, out, duration: durations.append(duration))
    monkeypatch.setattr(renderer, "run", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(
        renderer,
        "probe_streams",
        lambda path: [
            {"codec_type": "video", "start_time": "0", "duration": "9.042"},
            {"codec_type": "audio", "start_time": "0", "duration": "9.042"},
        ],
    )
    renderer.render_video(tmp_path, scenes, [], tmp_path / "clean.wav", 9.013,
                          "", "", narration_prepared=True)
    cumulative = 0
    for duration, scene in zip(durations[:-1], scenes[:-1]):
        cumulative += duration
        assert abs(cumulative - scene.end) <= 0.5 / renderer.OUTPUT_FPS + 1e-9
    assert sum(durations) == pytest.approx(math.ceil(9.013 * 24) / 24)
    assert any("pcm_s16le" in cmd for cmd in commands)


def test_ass_time_carries_rounding_into_next_minute():
    assert ass_time(59.999) == "0:01:00.00"

from pathlib import Path

from backend.app.services import renderer


def test_prepare_narration_rebuilds_continuous_pcm_timeline(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, *, cwd=None):
        captured["cmd"] = cmd

    monkeypatch.setattr(renderer, "run", fake_run)

    source = tmp_path / "voice.mp3"
    source.write_bytes(b"fake")
    output = renderer._prepare_narration(source, tmp_path)

    assert output == tmp_path / "narration_clean.wav"
    cmd = captured["cmd"]
    assert "-fflags" in cmd
    assert "+genpts" in cmd
    assert "aresample=48000:async=0:first_pts=0,asetpts=N/SR/TB" in cmd
    assert "pcm_s16le" in cmd
    assert "48000" in cmd


def test_voice_filter_rebuilds_output_audio_pts():
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in renderer.VOICE_FILTER
    assert "aresample=48000" in renderer.VOICE_FILTER
    assert "asetpts=N/SR/TB" in renderer.VOICE_FILTER


import pytest


@pytest.mark.parametrize("with_music", [False, True])
def test_final_render_uses_clean_narration(monkeypatch, tmp_path, with_music):
    commands = []
    monkeypatch.setattr(renderer, "run", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(
        renderer,
        "probe_streams",
        lambda path: [
            {"codec_type": "video", "start_time": "0", "duration": "4.0"},
            {"codec_type": "audio", "start_time": "0", "duration": "4.0"},
        ],
    )
    source = tmp_path / "voice.mp3"
    renderer.render_video(
        tmp_path, [], [], source, 4.0, "Hook", "Question?",
        music_path=tmp_path / "music.mp3" if with_music else None,
    )
    final = commands[-1]
    inputs = [final[i + 1] for i, arg in enumerate(final) if arg == "-i"]
    assert str(tmp_path / "work" / "narration_master.wav") in inputs
    assert str(source) not in inputs
    assert any("pcm_s16le" in cmd for cmd in commands)



def test_validate_final_av_rejects_duration_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        renderer,
        "probe_streams",
        lambda path: [
            {"codec_type": "video", "start_time": "0", "duration": "10.0"},
            {"codec_type": "audio", "start_time": "0", "duration": "8.9"},
        ],
    )
    import pytest
    with pytest.raises(ValueError, match="duration mismatch"):
        renderer._validate_final_av(tmp_path / "bad.mp4", 10.0)

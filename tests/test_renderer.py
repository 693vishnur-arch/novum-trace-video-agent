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

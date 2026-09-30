"""Run in the deployment container under its 512 MB memory limit (CI)."""
import json
import tempfile
from pathlib import Path

from backend.app.services.alignment import align_narration
from backend.app.services.media import probe_duration, run
from backend.app.services.planner import plan_aligned_scenes
from backend.app.services.renderer import _prepare_narration, render_video


def main():
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        work = project / "work"
        work.mkdir()
        source = Path("/fixture/narration.wav")
        clean = _prepare_narration(source, work)
        duration = probe_duration(clean)
        words = align_narration(clean, "", duration, work)
        # The fixture starts with two seconds of silence. Words must not be
        # redistributed to time zero, as the old word-count planner did.
        assert words[0].start >= 1.5, words[0]
        assert len(words) >= 8, words
        scenes = plan_aligned_scenes(duration, words, "", [], 4)
        output = render_video(project, scenes, [], clean, duration, "", "",
                              narration_prepared=True)
        assert abs(probe_duration(output) - duration) < 0.1
        streams = json.loads(run(["ffprobe", "-v", "error", "-show_streams",
                                  "-of", "json", str(output)]).stdout)["streams"]
        assert {s["codec_type"] for s in streams} == {"audio", "video"}
        for stream in streams:
            assert abs(float(stream.get("start_time", 0))) < 0.05
        print(json.dumps({"words": len(words), "duration": duration,
                          "first_word": words[0].start, "status": "passed"}))


if __name__ == "__main__":
    main()

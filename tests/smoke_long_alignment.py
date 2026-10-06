"""Exercise six minutes of speech under the deployment memory limit."""
import tempfile
from pathlib import Path

from backend.app.services.alignment import align_narration
from backend.app.services.media import probe_duration, run


def main():
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        audio = work / "long.wav"
        run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
             "-i", "/fixture/narration.wav", "-t", "360", "-ar", "48000",
             "-ac", "2", "-c:a", "pcm_s16le", str(audio)])
        duration = probe_duration(audio)
        words = align_narration(audio, "", duration, work)
        assert len(words) > 200, len(words)
        assert words[0].start >= 1.5, words[0]
        assert words[-1].end > duration - 15, words[-1]
        print(f"Long alignment passed: {len(words)} words over {duration}s")


if __name__ == "__main__":
    main()

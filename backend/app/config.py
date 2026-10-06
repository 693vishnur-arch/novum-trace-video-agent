from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "projects"
STATIC_DIR = Path(__file__).resolve().parent / "static"

OUTPUT_FPS = 24
FFMPEG_THREADS = 1
FFMPEG_PRESET = "ultrafast"
FFMPEG_CRF = 24

VIDEO_PROFILES = {
    "short": {
        "width": 720,
        "height": 1280,
        "max_scenes": 8,
        "prefer_portrait": True,
        "caption_mode": "full",
    },
    # 1280x720 keeps 6-10 minute renders realistic on the current 512 MB
    # Render instance. The architecture can be moved to 1080p later by changing
    # this single profile after compute/storage are upgraded.
    "long": {
        "width": 1280,
        "height": 720,
        "max_scenes": 36,
        "prefer_portrait": False,
        "caption_mode": "key",
    },
}

OUTPUT_WIDTH = VIDEO_PROFILES["short"]["width"]
OUTPUT_HEIGHT = VIDEO_PROFILES["short"]["height"]

DEFAULT_SCENE_SECONDS = 4.0
MIN_SCENE_SECONDS = 2.5
MAX_SCENE_SECONDS = 5.5
DEFAULT_MUSIC_VOLUME = 0.10
ALLOWED_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}


def video_profile(mode: str) -> dict[str, object]:
    return VIDEO_PROFILES.get(mode, VIDEO_PROFILES["short"])

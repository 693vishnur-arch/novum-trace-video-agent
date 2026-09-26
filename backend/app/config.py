from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "projects"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Free Render instances have 512 MB RAM and 0.1 CPU. Keep V1 deliberately
# lightweight so a 30-60 second Short can finish without the service restarting.
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280
OUTPUT_FPS = 24
FFMPEG_THREADS = 1
FFMPEG_PRESET = "ultrafast"
FFMPEG_CRF = 24

DEFAULT_SCENE_SECONDS = 4.0
MIN_SCENE_SECONDS = 2.5
MAX_SCENE_SECONDS = 5.5
DEFAULT_MUSIC_VOLUME = 0.10
ALLOWED_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}

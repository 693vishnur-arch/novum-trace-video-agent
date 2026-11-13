"""Low-cost perceptual first-frame fingerprints for video/image assets.

Near-duplicate checks require ffmpeg; callers may fall back to provider IDs
if media is corrupt or ffmpeg is unavailable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def visual_hash(path: Path) -> str | None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        cmd.extend(["-ss", "0.5"])
    cmd.extend(["-i", str(path), "-frames:v", "1",
                "-vf", "scale=9:8,format=gray", "-f", "rawvideo", "pipe:1"])
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=20, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None
    pixels = result.stdout
    if len(pixels) != 72:
        return None
    bits = 0
    for row in range(8):
        for column in range(8):
            a = pixels[row * 9 + column]
            b = pixels[row * 9 + column + 1]
            bits = (bits << 1) | int(a > b)
    return f"{bits:016x}"


def similar(a: str | None, b: str | None, threshold: int = 5) -> bool:
    if not a or not b:
        return False
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count() <= threshold
    except ValueError:
        return False


def historical_hashes(projects: list[dict]) -> set[str]:
    return {str(item["fingerprint"]) for project in projects
            for item in (project.get("stock_credits") or [])
            if item.get("fingerprint")}

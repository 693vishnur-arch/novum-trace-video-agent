"""Runway Dev tasks for optional synthetic documentary B-roll.

Uses only the official Runway Dev API; never exposes an API key to the browser.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.dev.runwayml.com/v1"
VERSION = "2024-11-06"
MAX_VIDEO_BYTES = 60 * 1024 * 1024
GEN45_CREDITS_PER_SECOND = 12


def estimated_credits(duration: float) -> int:
    """Gen-4.5 list-price estimate; actual billing is determined by Runway."""
    return max(2, min(10, round(duration))) * GEN45_CREDITS_PER_SECOND



class AIVideoError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("RUNWAYML_API_SECRET", "").strip())


def _request(path: str, *, payload: dict | None = None) -> dict:
    secret = os.environ.get("RUNWAYML_API_SECRET", "").strip()
    if not secret:
        raise AIVideoError("RUNWAYML_API_SECRET is not configured")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, headers={
            "Authorization": f"Bearer {secret}",
            "X-Runway-Version": VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
        raise AIVideoError(f"Runway API request failed: {type(exc).__name__}") from exc


def create_task(prompt: str, *, portrait: bool, image_uri: str | None = None,
                duration: int = 5, model: str = "gen4.5") -> str:
    if model != "gen4.5":
        raise AIVideoError("Only the verified gen4.5 model is supported")
    duration = max(2, min(int(duration), 10))
    # Remote image inputs must be an explicitly provided trusted HTTPS URL.
    if image_uri and not image_uri.startswith("https://"):
        raise AIVideoError("Image input must be an HTTPS URL")
    payload = {
        "model": model,
        "promptText": prompt[:1000],
        "ratio": "720:1280" if portrait else "1280:720",
        "duration": duration,
    }
    if image_uri:
        payload["promptImage"] = {"uri": image_uri, "position": "first"}
    response = _request("/image_to_video" if image_uri else "/text_to_video", payload=payload)
    task_id = str(response.get("id") or "")
    if not task_id:
        raise AIVideoError("Runway did not return a task id")
    return task_id


def get_task(task_id: str) -> dict:
    if not task_id or not all(ch.isalnum() or ch in "-_" for ch in task_id):
        raise AIVideoError("Invalid task identifier")
    return _request("/tasks/" + task_id)


def wait_task(task_id: str, *, timeout_seconds: int = 480, poll_seconds: int = 8,
              on_update=None) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = get_task(task_id)
        status = str(task.get("status") or "").upper()
        if on_update:
            on_update(task)
        if status == "SUCCEEDED":
            urls = task.get("output") or []
            if not urls or not isinstance(urls[0], str):
                raise AIVideoError("Runway completed without a downloadable video")
            return urls[0]
        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            raise AIVideoError(f"Runway generation ended with status {status}")
        time.sleep(poll_seconds)
    raise AIVideoError("Runway generation timed out; task can be checked later")


def download_result(url: str, path: Path) -> Path:
    # Generated task outputs should only be downloaded over HTTPS.
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AIVideoError("Invalid Runway output URL")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NovumTrace/AI"})
        with urllib.request.urlopen(req, timeout=90) as response, path.open("wb") as out:
            if int(response.headers.get("Content-Length") or 0) > MAX_VIDEO_BYTES:
                raise AIVideoError("Generated video exceeds download limit")
            count = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > MAX_VIDEO_BYTES:
                    raise AIVideoError("Generated video exceeds download limit")
                out.write(block)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if path.stat().st_size < 1024:
        path.unlink(missing_ok=True)
        raise AIVideoError("Generated video is empty")
    return path

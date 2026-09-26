from __future__ import annotations

import shutil
from pathlib import Path

from backend.app.config import (
    DEFAULT_MUSIC_VOLUME,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    FFMPEG_THREADS,
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
)
from backend.app.models import Scene
from backend.app.services.captions import build_ass
from backend.app.services.media import is_image, is_video, run


def _video_filter() -> str:
    return (
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1,fps={OUTPUT_FPS},format=yuv420p"
    )


def _encode_args() -> list[str]:
    return [
        "-c:v", "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf", str(FFMPEG_CRF),
        "-threads", str(FFMPEG_THREADS),
        "-pix_fmt", "yuv420p",
    ]


def _render_scene(source: Path | None, output: Path, duration: float) -> None:
    duration = max(duration, 0.25)
    vf = _video_filter()

    if source is None:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=0x070b12:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:r={OUTPUT_FPS}",
            "-t", f"{duration:.3f}", "-an",
            *_encode_args(),
            str(output),
        ]
        run(cmd)
        return

    if is_image(source):
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", str(OUTPUT_FPS), "-i", str(source),
            "-t", f"{duration:.3f}", "-an", "-vf", vf,
            *_encode_args(),
            str(output),
        ]
    elif is_video(source):
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(source),
            "-t", f"{duration:.3f}", "-an", "-vf", vf,
            *_encode_args(),
            str(output),
        ]
    else:
        raise ValueError(f"Unsupported visual file: {source.name}")

    run(cmd)


def _concat_scenes(scene_files: list[Path], output: Path, work_dir: Path) -> None:
    concat_file = work_dir / "concat.txt"
    lines = []
    for scene in scene_files:
        escaped = str(scene).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy", str(output),
    ])


def render_video(
    project_dir: Path,
    scenes: list[Scene],
    visual_paths: list[Path],
    narration_path: Path,
    total_duration: float,
    hook: str,
    ending_question: str,
    music_path: Path | None = None,
    music_volume: float = DEFAULT_MUSIC_VOLUME,
) -> Path:
    work_dir = project_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    visual_by_name = {p.name: p for p in visual_paths}
    scene_files: list[Path] = []

    for scene in scenes:
        scene_file = work_dir / f"scene_{scene.index:03d}.mp4"
        source = visual_by_name.get(scene.clip_name or "")
        _render_scene(source, scene_file, scene.duration)
        scene_files.append(scene_file)

    concat_video = work_dir / "visuals.mp4"
    _concat_scenes(scene_files, concat_video, work_dir)

    captions = project_dir / "captions.ass"
    build_ass(scenes, captions, hook, ending_question, total_duration)

    final_path = project_dir / "final.mp4"
    ass_path = str(captions).replace("\\", "/").replace(":", r"\:")

    if music_path:
        fade_out_start = max(total_duration - 1.0, 0.0)
        filter_complex = (
            f"[0:v]ass='{ass_path}'[v];"
            f"[2:a]volume={music_volume:.3f},atrim=0:{total_duration:.3f},"
            f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_start:.3f}:d=1[m];"
            "[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(concat_video), "-i", str(narration_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-t", f"{total_duration:.3f}",
            *_encode_args(),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(final_path),
        ]
    else:
        filter_complex = f"[0:v]ass='{ass_path}'[v]"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(concat_video), "-i", str(narration_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "1:a:0",
            "-t", f"{total_duration:.3f}",
            *_encode_args(),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(final_path),
        ]

    run(cmd)
    return final_path


def cleanup_work(project_dir: Path) -> None:
    work = project_dir / "work"
    if work.exists():
        shutil.rmtree(work)

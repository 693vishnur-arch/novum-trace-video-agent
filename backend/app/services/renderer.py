from __future__ import annotations

import shutil
import math
from pathlib import Path

from backend.app.config import (
    DEFAULT_MUSIC_VOLUME,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    FFMPEG_THREADS,
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    video_profile,
)
from backend.app.models import Scene
from backend.app.services.captions import build_ass
from backend.app.services.media import is_image, is_video, probe_streams, run

VOICE_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000:async=0:first_pts=0,asetpts=N/SR/TB"


def _video_filter(width: int = OUTPUT_WIDTH, height: int = OUTPUT_HEIGHT) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={OUTPUT_FPS},format=yuv420p"
    )


def _encode_args() -> list[str]:
    return [
        "-c:v", "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf", str(FFMPEG_CRF),
        "-threads", str(FFMPEG_THREADS),
        "-pix_fmt", "yuv420p",
    ]


def _render_scene(
    source: Path | None,
    output: Path,
    duration: float,
    *,
    width: int = OUTPUT_WIDTH,
    height: int = OUTPUT_HEIGHT,
) -> None:
    duration = max(duration, 1 / OUTPUT_FPS)
    frames = max(1, round(duration * OUTPUT_FPS))
    vf = _video_filter(width, height)

    if source is None:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=0x070b12:s={width}x{height}:r={OUTPUT_FPS}",
            "-frames:v", str(frames), "-an",
            *_encode_args(),
            str(output),
        ]
        run(cmd)
        return

    if is_image(source):
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", str(OUTPUT_FPS), "-i", str(source),
            "-frames:v", str(frames), "-an", "-vf", vf,
            *_encode_args(),
            str(output),
        ]
    elif is_video(source):
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(source),
            "-frames:v", str(frames), "-an", "-vf", vf,
            *_encode_args(),
            str(output),
        ]
    else:
        raise ValueError(f"Unsupported visual file: {source.name}")

    run(cmd)


def _prepare_narration(source: Path, work_dir: Path) -> Path:
    """Decode narration to a continuous PCM timeline before the final mux.

    Some MP3/M4A files carry packet timestamps or encoder delay metadata that can
    produce gaps after filtering/muxing. Rebuilding timestamps from decoded sample
    count makes the voice track continuous and deterministic.
    """
    output = work_dir / "narration_clean.wav"
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-fflags", "+genpts",
        "-i", str(source),
        "-vn",
        "-af", "aresample=48000:async=0:first_pts=0,asetpts=N/SR/TB",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(output),
    ])
    return output


def _normalize_narration(source: Path, work_dir: Path, total_duration: float) -> Path:
    """Create the exact master voice track used by the final MP4.

    Normalizing to PCM in a separate pass avoids audio timestamps being
    rewritten inside the final video filter graph. The result is padded/trimmed
    to the measured narration duration before AAC encoding.
    """
    output = work_dir / "narration_master.wav"
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-vn",
        "-af",
        f"{VOICE_FILTER},apad=pad_dur={total_duration:.3f},"
        f"atrim=0:{total_duration:.3f},asetpts=N/SR/TB",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(output),
    ])
    return output


def _validate_final_av(path: Path, expected_duration: float) -> None:
    streams = probe_streams(path)
    by_type = {str(stream.get("codec_type")): stream for stream in streams}
    if "audio" not in by_type or "video" not in by_type:
        raise ValueError("Rendered MP4 is missing an audio or video stream")

    def number(stream: dict[str, object], key: str) -> float:
        try:
            return float(stream.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    audio_duration = number(by_type["audio"], "duration")
    video_duration = number(by_type["video"], "duration")
    audio_start = number(by_type["audio"], "start_time")
    video_start = number(by_type["video"], "start_time")

    if abs(audio_start - video_start) > 0.08:
        raise ValueError("Rendered audio/video start timestamps are not synchronized")
    if abs(audio_duration - video_duration) > 0.20:
        raise ValueError(
            f"Rendered audio/video duration mismatch: audio {audio_duration:.2f}s, "
            f"video {video_duration:.2f}s"
        )
    if abs(video_duration - expected_duration) > 0.20:
        raise ValueError(
            f"Rendered duration {video_duration:.2f}s differs from narration "
            f"{expected_duration:.2f}s"
        )


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
    narration_prepared: bool = False,
    video_mode: str = "short",
) -> Path:
    profile = video_profile(video_mode)
    width = int(profile["width"])
    height = int(profile["height"])
    work_dir = project_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    visual_by_name = {p.name: p for p in visual_paths}
    scene_files: list[Path] = []

    frame_cursor = 0
    for scene in scenes:
        scene_file = work_dir / f"scene_{scene.index:03d}.mp4"
        source = visual_by_name.get(scene.clip_name or "")
        # Round absolute boundaries, not every clip duration: rounding each
        # duration independently accumulates visible drift over many scenes.
        end_frame = (math.ceil(total_duration * OUTPUT_FPS) if scene is scenes[-1]
                     else round(scene.end * OUTPUT_FPS))
        if end_frame <= frame_cursor:
            raise ValueError("Scene is shorter than one output frame")
        _render_scene(
            source,
            scene_file,
            (end_frame - frame_cursor) / OUTPUT_FPS,
            width=width,
            height=height,
        )
        frame_cursor = end_frame
        scene_files.append(scene_file)

    concat_video = work_dir / "visuals.mp4"
    _concat_scenes(scene_files, concat_video, work_dir)

    captions = project_dir / "captions.ass"
    build_ass(
        scenes,
        captions,
        hook,
        ending_question,
        total_duration,
        video_mode=video_mode,
    )

    narration_clean = narration_path if narration_prepared else _prepare_narration(narration_path, work_dir)
    narration_master = _normalize_narration(narration_clean, work_dir, total_duration)

    final_path = project_dir / "final.mp4"
    ass_path = str(captions).replace("\\", "/").replace(":", r"\:")

    if music_path:
        fade_out_start = max(total_duration - 1.0, 0.0)
        filter_complex = (
            f"[0:v]ass='{ass_path}'[v];"
            f"[1:a]anull[voice];"
            f"[2:a]aresample=48000:async=0:first_pts=0,asetpts=N/SR/TB,"
            f"volume={music_volume:.3f},atrim=0:{total_duration:.3f},"
            f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_start:.3f}:d=1[m];"
            "[voice][m]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95[a]"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(concat_video), "-i", str(narration_master),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-t", f"{total_duration:.3f}",
            *_encode_args(),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final_path),
        ]
    else:
        filter_complex = f"[0:v]ass='{ass_path}'[v]"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(concat_video), "-i", str(narration_master),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "1:a:0",
            "-t", f"{total_duration:.3f}",
            *_encode_args(),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final_path),
        ]

    run(cmd)
    _validate_final_av(final_path, total_duration)
    return final_path


def cleanup_work(project_dir: Path) -> None:
    work = project_dir / "work"
    if work.exists():
        shutil.rmtree(work)

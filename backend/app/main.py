from __future__ import annotations

import shutil
import traceback
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import ALLOWED_AUDIO, ALLOWED_IMAGE, ALLOWED_VIDEO, DATA_DIR, STATIC_DIR
from backend.app.services.budget import GenerationBudget
from backend.app.services.media import probe_duration
from backend.app.services.metadata import build_metadata
from backend.app.services.planner import derive_ending, derive_hook, plan_scenes
from backend.app.services.renderer import cleanup_work, render_video
from backend.app.services.store import create_project_dir, list_projects, load_state, now_iso, save_state

app = FastAPI(title="Novum Trace Video Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def safe_name(name: str | None, fallback: str) -> str:
    value = Path(name or fallback).name
    return value.replace("\x00", "") or fallback


def allowed(path: Path, allowed_set: set[str]) -> bool:
    return path.suffix.lower() in allowed_set


def save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)


def process_project(
    project_id: str,
    title: str,
    prompt: str,
    script: str,
    hook_text: str,
    ending_question: str,
    narration_path: Path,
    visual_paths: list[Path],
    music_path: Path | None,
    max_generations: int,
) -> None:
    project_dir = DATA_DIR / project_id
    try:
        state = load_state(project_id)
        state.update({"status": "analyzing", "progress": 12, "error": None})
        save_state(project_dir, state)

        total_duration = probe_duration(narration_path)
        if total_duration <= 0.5:
            raise ValueError("Narration file is too short")

        # V1 deliberately never invokes a visual generation provider.
        budget = GenerationBudget(maximum=max(0, max_generations), used=0)
        hook = derive_hook(title, script, hook_text)
        ending = derive_ending(ending_question)
        scenes = plan_scenes(total_duration, script, visual_paths, hook, ending)

        state.update({
            "status": "planning",
            "progress": 28,
            "duration": round(total_duration, 3),
            "hook": hook,
            "ending_question": ending,
            "scenes": [scene.to_dict() for scene in scenes],
            "generation_budget": {
                "maximum": budget.maximum,
                "used": budget.used,
                "remaining": budget.remaining,
                "enabled": False,
            },
        })
        save_state(project_dir, state)

        state.update({"status": "rendering", "progress": 48})
        save_state(project_dir, state)

        final_path = render_video(
            project_dir=project_dir,
            scenes=scenes,
            visual_paths=visual_paths,
            narration_path=narration_path,
            total_duration=total_duration,
            hook=hook,
            ending_question=ending,
            music_path=music_path,
        )

        metadata = build_metadata(title, prompt, script)
        state.update({
            "status": "complete",
            "progress": 100,
            "completed_at": now_iso(),
            "output_file": final_path.name,
            "metadata": metadata,
            "generation_budget": {
                "maximum": budget.maximum,
                "used": budget.used,
                "remaining": budget.remaining,
                "enabled": False,
            },
        })
        save_state(project_dir, state)
        cleanup_work(project_dir)
    except Exception as exc:
        try:
            state = load_state(project_id)
        except Exception:
            state = {"project_id": project_id}
        state.update({
            "status": "failed",
            "progress": 100,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        })
        save_state(project_dir, state)


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/projects")
def create_project(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    prompt: str = Form(""),
    script: str = Form(""),
    hook_text: str = Form(""),
    ending_question: str = Form("WHAT HAPPENS NEXT?"),
    max_generations: int = Form(0),
    narration: UploadFile = File(...),
    clips: list[UploadFile] = File(default=[]),
    music: UploadFile | None = File(default=None),
) -> dict[str, object]:
    project_id, project_dir = create_project_dir()
    upload_dir = project_dir / "uploads"

    narration_name = safe_name(narration.filename, "narration.mp3")
    narration_path = upload_dir / narration_name
    if not allowed(narration_path, ALLOWED_AUDIO):
        raise HTTPException(status_code=400, detail="Unsupported narration format")
    save_upload(narration, narration_path)

    visual_paths: list[Path] = []
    for index, clip in enumerate(clips):
        clip_name = safe_name(clip.filename, f"clip_{index:02d}.mp4")
        path = upload_dir / clip_name
        if not allowed(path, ALLOWED_VIDEO | ALLOWED_IMAGE):
            raise HTTPException(status_code=400, detail=f"Unsupported visual format: {clip_name}")
        # Avoid accidental overwrite when users upload repeated filenames.
        if path.exists():
            path = upload_dir / f"{index:02d}_{clip_name}"
        save_upload(clip, path)
        visual_paths.append(path)

    music_path: Path | None = None
    if music and music.filename:
        music_name = safe_name(music.filename, "music.mp3")
        candidate = upload_dir / music_name
        if not allowed(candidate, ALLOWED_AUDIO):
            raise HTTPException(status_code=400, detail="Unsupported music format")
        save_upload(music, candidate)
        music_path = candidate

    state = {
        "project_id": project_id,
        "title": title.strip() or "Novum Trace Short",
        "prompt": prompt.strip(),
        "script": script.strip(),
        "status": "queued",
        "progress": 3,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "duration": None,
        "visual_count": len(visual_paths),
        "narration_file": narration_path.name,
        "music_file": music_path.name if music_path else None,
        "generation_budget": {
            "maximum": max(0, max_generations),
            "used": 0,
            "remaining": max(0, max_generations),
            "enabled": False,
        },
        "scenes": [],
        "metadata": None,
        "error": None,
    }
    save_state(project_dir, state)

    background_tasks.add_task(
        process_project,
        project_id,
        state["title"],
        state["prompt"],
        state["script"],
        hook_text,
        ending_question,
        narration_path,
        visual_paths,
        music_path,
        max_generations,
    )
    return {"project_id": project_id, "status": "queued"}


@app.get("/api/projects")
def projects() -> list[dict[str, object]]:
    return list_projects()


@app.get("/api/projects/{project_id}")
def project(project_id: str) -> dict[str, object]:
    try:
        return load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@app.get("/api/projects/{project_id}/video")
def project_video(project_id: str) -> FileResponse:
    project_dir = DATA_DIR / project_id
    path = project_dir / "final.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered video is not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"novum_trace_{project_id}.mp4")


@app.get("/api/projects/{project_id}/download")
def project_download(project_id: str) -> FileResponse:
    project_dir = DATA_DIR / project_id
    path = project_dir / "final.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered video is not ready")
    return FileResponse(path, media_type="application/octet-stream", filename=f"novum_trace_{project_id}.mp4")

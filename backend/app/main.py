from __future__ import annotations

import json
import shutil
import traceback
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import ALLOWED_AUDIO, ALLOWED_IMAGE, ALLOWED_VIDEO, DATA_DIR, STATIC_DIR
from backend.app.services.budget import GenerationBudget
from backend.app.services.media import probe_duration
from backend.app.services.metadata import build_metadata
from backend.app.services.planner import derive_ending, derive_hook, plan_aligned_scenes
from backend.app.services.renderer import cleanup_work, render_video, _prepare_narration
from backend.app.services.alignment import align_narration
from backend.app.services.stock import (
    StockProviderError,
    api_status as stock_api_status,
    build_review_queries,
    build_search_query,
    candidate_key,
    credit_record,
    download_candidate,
    first_unused_candidate,
    get_candidate,
    normalize_providers,
    promote_unused_candidate,
    search_stock,
    write_credits,
)
from backend.app.services.store import create_project_dir, list_projects, load_state, now_iso, save_state

app = FastAPI(title="Novum Trace Video Agent", version="1.4.2")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_project_lock = threading.Lock()


def safe_name(name: str | None, fallback: str) -> str:
    value = Path(name or fallback).name
    return value.replace("\x00", "") or fallback


def allowed(path: Path, allowed_set: set[str]) -> bool:
    return path.suffix.lower() in allowed_set


def save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)


def _parse_stock_selections(raw: str) -> dict[int, dict[str, str]]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid stock selection data") from exc

    if not isinstance(payload, list):
        raise ValueError("Stock selections must be a list")

    selections: dict[int, dict[str, str]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            scene_index = int(item.get("scene_index"))
        except (TypeError, ValueError):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        video_id = str(item.get("id") or "").strip()
        query = str(item.get("query") or "").strip()
        if provider in {"pexels", "pixabay"} and video_id:
            selections[scene_index] = {
                "provider": provider,
                "id": video_id,
                "query": query,
            }
    return selections


def _download_stock_for_scenes(
    *,
    project_dir: Path,
    scenes: list[Any],
    visual_paths: list[Path],
    title: str,
    prompt: str,
    visual_source: str,
    providers: str,
    max_clips: int,
    selections_raw: str,
    prefer_portrait: bool,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Attach stock clips to scenes while keeping strict download limits."""
    if visual_source not in {"stock_auto", "stock_mix"}:
        return visual_paths, []

    status = stock_api_status()
    requested = normalize_providers(providers)
    available = [provider for provider in requested if status.get(provider)]
    if not available:
        raise StockProviderError(
            "No stock API key is configured. Add PEXELS_API_KEY and/or PIXABAY_API_KEY in Render."
        )

    max_clips = min(max(int(max_clips or 1), 1), 8)
    selections = _parse_stock_selections(selections_raw)
    upload_dir = project_dir / "uploads"
    credits: list[dict[str, Any]] = []
    used_ids: set[tuple[str, str]] = set()
    stock_paths: list[Path] = []

    # In mixed mode, use each uploaded clip once first, then let stock fill the
    # remaining scenes. This avoids blindly cycling one user clip across the Short.
    if visual_source == "stock_mix" and visual_paths:
        for scene, uploaded in zip(scenes, visual_paths):
            scene.clip_name = uploaded.name

    stock_start_index = len(visual_paths) if visual_source == "stock_mix" else 0

    for scene in scenes:
        if scene.index < stock_start_index and scene.clip_name:
            continue
        if len(stock_paths) >= max_clips:
            break

        query = build_search_query(scene.text, fallback=f"{title} {prompt}")
        candidate: dict[str, Any] | None = None

        selected = selections.get(int(scene.index))
        if selected:
            requested_key = (
                selected["provider"].strip().lower(),
                selected["id"].strip(),
            )
            # Review mode used to honor duplicate radio defaults across scenes,
            # which could render the same stock clip repeatedly. Keep a reviewed
            # selection only if that provider/video ID has not already been used.
            if requested_key not in used_ids:
                resolved = get_candidate(
                    selected["provider"],
                    selected["id"],
                    query=selected.get("query") or query,
                    prefer_portrait=prefer_portrait,
                )
                if candidate_key(resolved) not in used_ids:
                    candidate = resolved

        if candidate is None:
            candidates = search_stock(
                query,
                providers=available,
                limit=8,
                prefer_portrait=prefer_portrait,
            )
            candidate = first_unused_candidate(candidates, used_ids)

        if not candidate:
            continue

        key = candidate_key(candidate)
        used_ids.add(key)
        destination = upload_dir / (
            f"stock_{scene.index:02d}_{candidate['provider']}_{candidate['id']}.mp4"
        )
        download_candidate(candidate, destination)
        stock_paths.append(destination)
        scene.clip_name = destination.name
        credits.append(credit_record(candidate, scene_index=int(scene.index)))

    all_paths = [*visual_paths, *stock_paths]

    # Do not cycle already-used stock into unmatched scenes. V1.4.1 keeps one
    # provider/video ID per scene; if a provider cannot supply another distinct
    # match, the renderer uses its neutral background instead of repeating B-roll.
    # In mixed mode, uploaded clips are also consumed only once above.

    if credits:
        write_credits(project_dir / "credits.txt", credits)

    return all_paths, credits


def process_project(*args: Any, **kwargs: Any) -> None:
    # One inference/render at a time on the memory-limited single-worker server.
    with _project_lock:
        _process_project(*args, **kwargs)


def _process_project(
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
    visual_source: str,
    stock_providers: str,
    stock_max_clips: int,
    stock_selections: str,
    prefer_portrait: bool,
) -> None:
    project_dir = DATA_DIR / project_id
    try:
        state = load_state(project_id)
        state.update({"status": "analyzing", "progress": 12, "error": None})
        save_state(project_dir, state)

        work_dir = project_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        narration_clean = _prepare_narration(narration_path, work_dir)
        total_duration = probe_duration(narration_clean)
        if total_duration <= 0.5:
            raise ValueError("Narration file is too short")

        budget = GenerationBudget(maximum=max(0, max_generations), used=0)
        hook = derive_hook(title, script, hook_text)
        ending = derive_ending(ending_question)

        # When stock search is enabled, scene planning should follow the narration
        # rather than cycling uploaded filenames before the matching step.
        planning_clips = visual_paths if visual_source == "upload" else []
        state.update({"status": "aligning narration", "progress": 18})
        save_state(project_dir, state)
        words = align_narration(narration_clean, script, total_duration, work_dir)
        scene_limit = stock_max_clips if visual_source in {"stock_auto", "stock_mix"} else 8
        scenes = plan_aligned_scenes(total_duration, words, script, planning_clips, scene_limit)
        state["timing_method"] = "speech_word_timestamps"

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

        credits: list[dict[str, Any]] = []
        if visual_source in {"stock_auto", "stock_mix"}:
            state.update({"status": "finding stock clips", "progress": 36})
            save_state(project_dir, state)
            visual_paths, credits = _download_stock_for_scenes(
                project_dir=project_dir,
                scenes=scenes,
                visual_paths=visual_paths,
                title=title,
                prompt=prompt,
                visual_source=visual_source,
                providers=stock_providers,
                max_clips=stock_max_clips,
                selections_raw=stock_selections,
                prefer_portrait=prefer_portrait,
            )

        state.update({
            "status": "rendering",
            "progress": 48,
            "visual_count": len(visual_paths),
            "stock_clip_count": len(credits),
            "stock_credits": credits,
            "scenes": [scene.to_dict() for scene in scenes],
        })
        save_state(project_dir, state)

        final_path = render_video(
            project_dir=project_dir,
            scenes=scenes,
            visual_paths=visual_paths,
            narration_path=narration_clean,
            total_duration=total_duration,
            hook=hook,
            ending_question=ending,
            music_path=music_path,
            narration_prepared=True,
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


@app.get("/api/stock/status")
def stock_status() -> dict[str, Any]:
    return {
        "configured": stock_api_status(),
        "providers": ["pexels", "pixabay"],
        "max_stock_clips": 8,
    }


@app.post("/api/stock/search")
def stock_search_preview(
    title: str = Form(""),
    prompt: str = Form(""),
    script: str = Form(""),
    stock_providers: str = Form("pexels,pixabay"),
    stock_max_clips: int = Form(8),
    prefer_portrait: bool = Form(True),
) -> dict[str, Any]:
    queries = build_review_queries(
        script,
        title,
        max_clips=stock_max_clips,
        prompt=prompt,
    )
    results: list[dict[str, Any]] = []
    configured = stock_api_status()

    if not any(configured.values()):
        raise HTTPException(
            status_code=400,
            detail="No stock API key is configured. Add PEXELS_API_KEY and/or PIXABAY_API_KEY in Render.",
        )

    preview_used_ids: set[tuple[str, str]] = set()

    for item in queries:
        try:
            candidates = search_stock(
                item["query"],
                providers=stock_providers,
                limit=8,
                prefer_portrait=prefer_portrait,
            )
            # The first candidate is auto-selected in the browser. Promote a
            # globally unused clip to the first position so eight reviewed
            # scenes default to eight different source IDs whenever possible.
            candidates = promote_unused_candidate(candidates, preview_used_ids)
            if candidates:
                preview_used_ids.add(candidate_key(candidates[0]))
            results.append({**item, "candidates": candidates[:3], "error": None})
        except StockProviderError as exc:
            results.append({**item, "candidates": [], "error": str(exc)})

    return {
        "configured": configured,
        "results": results,
        "attribution": {
            "pexels": "https://www.pexels.com/",
            "pixabay": "https://pixabay.com/",
        },
    }


@app.post("/api/projects")
def create_project(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    prompt: str = Form(""),
    script: str = Form(""),
    hook_text: str = Form(""),
    ending_question: str = Form("WHAT HAPPENS NEXT?"),
    max_generations: int = Form(0),
    visual_source: str = Form("upload"),
    stock_providers: str = Form("pexels,pixabay"),
    stock_max_clips: int = Form(8),
    stock_selections: str = Form(""),
    prefer_portrait: bool = Form(True),
    narration: UploadFile = File(...),
    clips: list[UploadFile] = File(default=[]),
    music: UploadFile | None = File(default=None),
) -> dict[str, object]:
    if visual_source not in {"upload", "stock_auto", "stock_mix"}:
        raise HTTPException(status_code=400, detail="Invalid visual source")

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
        "visual_source": visual_source,
        "stock_providers": normalize_providers(stock_providers),
        "stock_max_clips": min(max(stock_max_clips, 1), 8),
        "stock_clip_count": 0,
        "stock_credits": [],
        "stock_provider_status": stock_api_status(),
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
        visual_source,
        stock_providers,
        stock_max_clips,
        stock_selections,
        prefer_portrait,
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


@app.get("/api/projects/{project_id}/credits")
def project_credits(project_id: str) -> FileResponse:
    project_dir = DATA_DIR / project_id
    path = project_dir / "credits.txt"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No stock credits for this project")
    return FileResponse(path, media_type="text/plain", filename=f"novum_trace_{project_id}_credits.txt")

# Novum Trace Video Agent V1

A self-hosted automatic editor for vertical YouTube Shorts.

Input:
- Editing prompt
- ElevenLabs narration (MP3/WAV/M4A)
- Multiple video clips and/or images
- Optional narration script
- Optional background music
- Optional logo

Output:
- 1080x1920 vertical MP4
- 30 FPS H.264 video + AAC audio
- Automatically timed scenes
- Burned-in captions
- Opening hook
- Novum Trace ending card
- Generated YouTube metadata

The V1 renderer uses FFmpeg for editing. It does not control CapCut and does not consume browser-agent editing credits. AI video generation is intentionally disabled by default. The generation budget is enforced by the backend and cannot be exceeded by the planner.

## Features

- FastAPI web application
- Drag-and-drop uploads
- Automatic narration duration detection
- Script-to-scene timing
- Deterministic fallback planning when no AI API is configured
- Automatic center crop/scale to 9:16
- Images and video clips can be mixed
- Clip reuse if there are fewer visuals than scenes
- ASS subtitle rendering
- Optional background music mixing
- Project history and render status
- Generation budget tracking
- Docker deployment

## Quick start

Requirements:
- Python 3.11+
- FFmpeg and ffprobe available on PATH

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

`http://localhost:8000`

## Docker

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

## Typical workflow

1. Enter a project title and an editing prompt.
2. Upload the ElevenLabs narration.
3. Paste the narration script when available.
4. Upload 5-12 video clips or images.
5. Keep AI generation disabled and max generations at 0 for zero generation-credit usage.
6. Click Create Short.
7. Wait for rendering to complete.
8. Preview and download the MP4.

## Generation budget

V1 never generates visual clips. It records the requested maximum but always uses zero generations. This is deliberate: the editor must never burn through external video-generation credits unexpectedly.

Future providers can be added behind the `GenerationBudget` interface. Any provider must call `consume()` before generation. Once the configured limit is reached, the renderer must reuse uploaded footage instead.

## Project data

Runtime uploads and renders are written under `data/projects/` and are ignored by Git.

Each project stores:
- `project.json`
- uploaded media
- generated scene clips
- `captions.ass`
- `final.mp4`

## Notes

- Supplying the narration script gives the best captions.
- Without a script, V1 can still build the video but omits speech captions unless an optional transcription integration is added.
- The renderer uses center cropping, not CapCut Auto Reframe.
- V1 has no dependency on CapCut Pro features.

## Roadmap

- Optional Whisper transcription
- OpenAI scene-planning adapter
- ElevenLabs API integration
- Optional image/video generation providers with hard spend limits
- YouTube OAuth upload
- Smart visual matching using embeddings
- Automatic safe-zone caption positioning

## License

MIT

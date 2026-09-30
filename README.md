# Novum Trace Video Agent V1.4

A self-hosted automatic editor for vertical YouTube Shorts.

## Speech-synchronized timing

New renders decode narration once to PCM, then use local faster-whisper word
timestamps for captions and scene boundaries. Script spelling is preserved where
recognition matches; small spelling/tokenization differences use the measured
speech span. Large mismatches, missing speech, and alignment failures stop with
an error instead of silently estimating timings from word counts.

Stock review and rendering share the same scene groups. Captions stop during
long pauses, the final question follows its spoken onset, and video cuts use
absolute 24 FPS frame boundaries to avoid cumulative rounding drift.

The Docker image bundles the `tiny.en` English model. No speech API key or paid
service is required, and narration stays on the server. Set `WHISPER_MODEL` to a
local compatible model directory to use another model/language. Non-Docker runs
download `tiny.en` on first use. Recognition adds processing time and its word
boundaries remain model estimates; review the rendered captions. Projects are
processed serially, and the recognition subprocess exits before FFmpeg rendering
to release memory. Larger models need more RAM. Use a single Uvicorn worker.

Existing MP4s are unchanged: create a new render to apply speech timing.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/693vishnur-arch/novum-trace-video-agent)

## What V1.3 does

Input:
- Editing prompt
- ElevenLabs narration (MP3/WAV/M4A)
- Narration script
- Optional uploaded video clips/images
- Optional background music

Visual sourcing:
- Upload your own clips
- Automatically find free stock video
- Mix your clips with stock
- Pexels primary source
- Pixabay additional/fallback source
- Relevance-first matching with portrait preference
- Maximum 8 downloaded stock clips per Short
- Review three candidate clips per scene before rendering, or let the agent auto-select

Output:
- 720x1280 vertical MP4 for the Render free tier
- 24 FPS H.264 + AAC
- Dynamic non-truncating captions
- Opening hook
- Novum Trace ending card
- Narration normalized for mobile/Shorts playback
- YouTube metadata
- Stock source/creator credits

The editor uses FFmpeg, not CapCut. Stock search does not consume AI video-generation credits.

## Stock provider setup

V1.3 supports the official Pexels and Pixabay video APIs.

Add these environment variables to your deployment:

```text
PEXELS_API_KEY=your_key_here
PIXABAY_API_KEY=your_key_here
```

You may configure one provider or both. API keys are read only from environment variables and are never stored in project files or returned to the browser.

The agent:
1. Breaks the narration into visual scenes.
2. Converts each scene into a stock-friendly search query.
3. Searches configured providers.
4. Scores semantic relevance before orientation, then prefers portrait/HD clips with suitable durations.
5. Rejects obvious off-topic results for strong themes (for example football or airplane footage in a rocket story).\n6. Downloads only selected clips to the current project.
7. Reuses downloaded footage if the Short has more scenes than the configured download cap.
8. Stores source URLs and contributor names in `credits.txt`.

Pexels attribution is surfaced in the UI and project credits. Pixabay sources are also retained.

## Quick start

Requirements:
- Python 3.11+
- FFmpeg and ffprobe on PATH

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PEXELS_API_KEY="..."
export PIXABAY_API_KEY="..."
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`.

## Docker

```bash
docker compose up --build
```

## Render

The root-level `render.yaml` configures:
- Docker runtime
- Singapore region
- `/health` health checks
- deploy after GitHub CI passes
- free compute for testing
- secret placeholders for Pexels and Pixabay API keys

The free Render filesystem is ephemeral. Project history, downloaded stock, and output videos can disappear after a restart/redeploy/spin-down. Download completed MP4s promptly. For regular use, move to paid compute with persistent storage.

## Typical workflow

1. Enter project title and editing prompt.
2. Paste the narration script.
3. Upload the ElevenLabs narration.
4. Choose **Find free stock automatically**.
5. Choose Pexels + Pixabay.
6. Keep maximum stock clips at 8 for most 30-50 second Shorts.
7. Optionally click **Find Matching Clips** to review candidates.
8. Click **Create Short**.
9. Preview and download the MP4.
10. Download the stock credits file if stock media was used.

## Safety limits

- AI video generation remains OFF in V1.3.
- Stock clips are capped at 8 per project.
- Individual stock downloads are capped at 60 MB.
- Pixabay searches use SafeSearch.
- Only HTTPS provider URLs are downloaded.
- API keys never appear in client responses.

## Tests

```bash
PYTHONPATH=. python -m pytest -q
```

GitHub Actions runs compile and test checks on every push.

## Roadmap

- Larger multilingual speech models for higher-resource deployments
- semantic/embedding-based stock ranking
- ElevenLabs API integration
- optional AI video-generation providers behind hard spend limits
- YouTube OAuth upload
- persistent object storage
- 1080x1920 production render profile

## License

MIT

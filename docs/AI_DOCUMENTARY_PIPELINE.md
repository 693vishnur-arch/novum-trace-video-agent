# AI documentary pipeline (feature preview)

This branch adds optional AI-generated illustrative footage while leaving legacy
`upload`, `stock_auto` and `stock_mix` modes available.

## Setup

- Configure `RUNWAYML_API_SECRET` as a secret environment variable in Render.
- Keep `PEXELS_API_KEY` / `PIXABAY_API_KEY` for licensed-stock search.
- Use `ai_auto`, `authentic_auto` or `hybrid_auto` as Visual Source.
- Set **Max AI generations** above zero before paid Runway generation will occur.
- This feature uses Runway Dev's `gen4.5` text-to-video endpoint and optionally
  image-to-video when a trusted HTTPS input image is provided via the Python client.
- Confirm account permissions and credit balance before processing.

Official API documentation: https://docs.dev.runwayml.com/api/

## Reporting and factual accuracy

- Synthetic scenes are `AI-generated illustration; not actual event footage`.
- Synthetic scenes must not be offered as evidence or actual footage of a reported
  event. The visual plan records narration, camera motion and source requirements.
- Current authentic source discovery uses Pexels and Pixabay, **not arbitrary
  web, YouTube, NASA or Wikimedia downloads**.
- User review of authenticity, attribution and required license conditions is
  mandatory before publishing.

## Implementation notes

- The scene director creates distinct narration-based prompts and flags some
  event-specific statements for genuine footage.
- Runway tasks are asynchronous on Runway's side, but the application worker
  currently polls them synchronously, recording task IDs/status in project.json.
- Video downloads are capped at 60 MB. Unmatched scenes retain the existing
  neutral-background fallback.
- Credits are charged by the external provider, not by FFmpeg. The field labeled
  Max AI generations limits calls, not a currency-denominated spend.
- On the current Render free instance, local project files are ephemeral.
  Production deployment needs persistent project storage and a durable job queue.
- A restart during task polling is not yet automatically recovered.
- A storyboard review/approval flow, provider expansion, stronger semantic matching,
  near-duplicate video fingerprints and cost quotes remain planned follow-ups.

## Suggested verification

```bash
python -m compileall backend
python -m pytest -q
```

CI also builds a Docker image and runs alignment smoke tests inside a 512 MB
container. Do not merge or deploy before these checks pass.

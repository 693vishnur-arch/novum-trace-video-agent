# AI documentary pipeline (feature preview)

This branch adds optional AI-generated illustrative footage while leaving legacy
`upload`, `stock_auto` and `stock_mix` modes available.

## Setup

- Configure `RUNWAYML_API_SECRET` and `NOVUM_ADMIN_TOKEN` as secret environment variables in Render.
- The administrator must enter the token in the production form to approve billable requests; never place this token in frontend source code.
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
- Authentic discovery uses Pexels and Pixabay clips, plus conservative Wikimedia
  Commons still images explicitly marked Public Domain / CC0. Asset rights and
  possible trademark/personality issues still require manual confirmation.
- Arbitrary web, YouTube and news videos are not scraped or reused.
- User review of authenticity, attribution and required license conditions is
  mandatory before publishing.

## Implementation notes

- The scene director creates distinct narration-based prompts and flags some
  event-specific statements for genuine footage. Before creating a project,
  review and approve the editable storyboard. These preview timings are estimates.
- Runway tasks are asynchronous on Runway's side, but the application worker
  currently polls them synchronously, recording task IDs/status in project.json.
- Video downloads are capped at 60 MB. Unmatched scenes retain the existing
  neutral-background fallback.
- Credits are charged by the external provider, not by FFmpeg. The field labeled
  Max AI generations limits calls, not a currency-denominated spend.
- On the current Render free instance, local project files are ephemeral.
  Production deployment needs persistent project storage and a durable job queue.
- A restart during task polling is not yet automatically recovered.
- Basic storyboard approval and first-frame perceptual duplicate detection are
  implemented. They are not a full finished-video scene-review interface or
  multi-frame semantic matching system. Exact creator permissions and credits
  still require review.
- A finished-footage replacement/regeneration interface, durable job recovery,
  cost quotes and richer licensed archival sources remain planned follow-ups.

## Suggested verification

```bash
python -m compileall backend
python -m pytest -q
```

CI also builds a Docker image and runs alignment smoke tests inside a 512 MB
container. Do not merge or deploy before these checks pass.

## Safe rollout

1. Wait for green CI, then exercise a dry-run storyboard preview.
2. Test authentic-only mode (no Runway cost) and verify captions and credits.
3. Configure Runway and admin token secrets, start a one-scene AI job,
   and verify its resulting MP4 and billing in the provider dashboard.
4. Only after that pilot, scale to long-form generation. Never publish AI
   recreations as genuine documentary footage.
5. Render free-tier storage and process lifetime are not sufficiently durable
   for unattended paid multi-scene production. Use persistent storage and
   a durable queue/workflow before exposing this commercially.

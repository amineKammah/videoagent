---
name: gcs-media-and-signed-url-debugger
description: Diagnose media delivery failures involving `gs://` paths, signed URLs, generated scene blobs, and browser playback/export behavior. Use when videos or voice-over audio fail to load, metadata URLs are missing, exports fail, or generated clips are not resolvable in frontend preview.
---

# GCS Media And Signed URL Debugger

## Quick Start
- Open `references/gcs-media-debug-map.md`.
- Identify the failing surface first: metadata endpoint, player load, audio load, or export download.
- Trace path shape across backend and frontend (`gs://`, `https://`, local path).

## Debug Workflow
1. Confirm path classification.
- Backend should sign only `gs://` paths.
- Frontend should reject raw `gs://` for direct playback and use signed URLs.
2. Verify storage configuration.
- Check `GCS_BUCKET_NAME`, bucket location guard, and signed URL TTL settings.
3. Validate metadata endpoint behavior.
- Confirm `/agent/library/videos/{video_id}` returns `url` for regular and generated assets.
- For `generated:<session_id>:<filename>`, verify sidecar metadata and blob existence.
4. Validate frontend source resolution.
- Ensure player resolves `meta.url` or `audio_url` and never attempts to play raw `gs://`.
5. Validate export fallback.
- If JS fetch to signed URL fails (CORS), verify fallback direct-open path works.
6. Reproduce with tests.
- Run targeted media URL and player tests before broad code changes.

## Triage Matrix
- `Video source is unavailable`: missing/invalid signed URL in metadata response.
- `Failed to load video file`: signed URL expired, object missing, or blocked fetch.
- Audio mismatch/missing VO: `voice_over.audio_url` not set or stale metadata.
- Generated clip missing: incorrect generated key, sidecar absent, or company scope mismatch.

## Guardrails
- Do not convert `gs://` paths into local filesystem assumptions.
- Do not bypass signing by forcing plain bucket HTTP URLs.
- Keep backend and frontend fixes paired when changing path/URL semantics.

# GCS Media Debug Map

## Table of Contents
- URL lifecycle
- Backend signing path
- Generated media pathing
- Frontend media resolution
- Storage client behavior
- Relevant tests

## URL Lifecycle
1. Backend stores canonical media path as `gs://...`.
2. API signs URL when serving metadata.
3. Frontend resolves signed URL for `<video>` and `<audio>` tags.
4. Export attempts blob fetch then direct open fallback.

## Backend Signing Path
- GCS key builder for generated scenes: `backend/src/videoagent/api.py:200`.
- Signer that passes through `http(s)` and signs only `gs://`: `backend/src/videoagent/api.py:205`.
- Scene media hydration injects signed `audio_url` for voice-over assets: `backend/src/videoagent/api.py:220`.
- Metadata endpoint for library and generated videos: `backend/src/videoagent/api.py:474`.

## Generated Media Pathing
- Generated IDs use `generated:<session_id>:<filename>` format: `backend/src/videoagent/api.py:492`.
- Generated blob scope uses company-specific prefix with global fallback: `backend/src/videoagent/api.py:200`.
- Sidecar read (`.metadata.json`) controls duration/resolution/fps response fields: `backend/src/videoagent/api.py:505`.

## Frontend Media Resolution
- Raw `gs://` is rejected for direct playback: `videoagent-studio/src/components/VideoPlayer.tsx:58`.
- Video source prioritizes signed `meta.url` over storage path: `videoagent-studio/src/components/VideoPlayer.tsx:67`.
- Voice-over source uses `audio_url` then `audio_path`: `videoagent-studio/src/components/VideoPlayer.tsx:73`.
- Export fallback to direct-open when fetch fails: `videoagent-studio/src/components/VideoPlayer.tsx:281`.

## Storage Client Behavior
- GCS-only client with bucket mismatch guard for `gs://`: `backend/src/videoagent/storage.py:59`.
- Bucket location guard (`europe-west2` default): `backend/src/videoagent/storage.py:42`.
- Signed URL generation path: `backend/src/videoagent/storage.py:110`.
- Singleton cache keyed by bucket/ttl/location env: `backend/src/videoagent/storage.py:171`.

## Relevant Tests
- API media URL signing and generated key coverage: `backend/tests/test_api_media_urls.py:1`.
- Storage client path normalization and env cache behavior: `backend/tests/test_storage.py:1`.
- Frontend playback/export signed URL behavior: `videoagent-studio/src/components/VideoPlayer.test.tsx:104`.

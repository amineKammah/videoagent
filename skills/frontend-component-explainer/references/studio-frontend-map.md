# VideoAgent Studio Frontend Map

## Table of Contents
- System entry points
- Component inventory
- Studio page composition
- Deep dive: VideoPlayer
- Deep dive: SceneTimeline
- Data contracts and state flow
- Test coverage anchors
- Explanation order

## System Entry Points
- Main studio route: `videoagent-studio/src/app/studio/page.tsx:14`
- Global store for session, scenes, messages, and processing status: `videoagent-studio/src/store/session.ts:59`
- Frontend API client: `videoagent-studio/src/lib/api.ts:1`
- Core media and storyboard types: `videoagent-studio/src/lib/types.ts:76`

## Component Inventory
- Studio shell and layout:
- `videoagent-studio/src/components/Sidebar.tsx`
- `videoagent-studio/src/components/RightSidebar.tsx`
- `videoagent-studio/src/components/ProjectBrief.tsx`
- Chat stack:
- `videoagent-studio/src/components/chat/Chat.tsx`
- `videoagent-studio/src/components/chat/MessageList.tsx`
- `videoagent-studio/src/components/chat/EventStream.tsx`
- Storyboard editing:
- `videoagent-studio/src/components/Storyboard.tsx`
- Playback and timeline:
- `videoagent-studio/src/components/VideoPlayer.tsx`
- `videoagent-studio/src/components/SceneTimeline.tsx`
- `videoagent-studio/src/components/VideoStatus.tsx`

## Studio Page Composition
- `StudioPage` selects `videoGenerating` and `scenes` from Zustand: `videoagent-studio/src/app/studio/page.tsx:15`.
- It computes `hasMatchedScenes` and shows the preview block only when generation is active or scenes have matches: `videoagent-studio/src/app/studio/page.tsx:50`.
- The preview body switches between `VideoStatus` and `VideoPlayer`: `videoagent-studio/src/app/studio/page.tsx:62`.
- The storyboard panel remains visible and is independent from preview playback state: `videoagent-studio/src/app/studio/page.tsx:71`.

## Deep Dive: VideoPlayer

### Public Surface
- Imperative ref API:
- `seekTo`, `play`, `pause`, `getCurrentTime`: `videoagent-studio/src/components/VideoPlayer.tsx:32`
- Optional outward callbacks:
- `onTimeUpdate`, `onPlayChange`: `videoagent-studio/src/components/VideoPlayer.tsx:39`

### Media Source Guardrails
- Browser-safe URL filter rejects `gs://` paths and non-direct schemes:
- `resolveMediaSource`: `videoagent-studio/src/components/VideoPlayer.tsx:58`
- Video source resolution prioritizes signed URL (`meta.url`) over storage path:
- `resolveMetadataVideoSource`: `videoagent-studio/src/components/VideoPlayer.tsx:67`
- Voice-over source resolution uses `audio_url` then `audio_path`:
- `resolveSceneAudioSource`: `videoagent-studio/src/components/VideoPlayer.tsx:73`

### Metadata Loading
- Fetches metadata per `source_video_id` once user identity exists in store: `videoagent-studio/src/components/VideoPlayer.tsx:368`.
- Tracks failed IDs to avoid repeated fetch loops: `videoagent-studio/src/components/VideoPlayer.tsx:346`.
- Supports one retry via `refreshMetadataForVideo` when video element raises an error: `videoagent-studio/src/components/VideoPlayer.tsx:349` and `videoagent-studio/src/components/VideoPlayer.tsx:896`.

### Playback Engine
- Builds composition timeline from per-scene start/end offsets: `videoagent-studio/src/components/VideoPlayer.tsx:328`.
- Main transition function is `playSegment`: `videoagent-studio/src/components/VideoPlayer.tsx:419`.
- `isTransitioningRef` prevents duplicate transitions from pause and ended event races: `videoagent-studio/src/components/VideoPlayer.tsx:320` and `videoagent-studio/src/components/VideoPlayer.tsx:580`.
- Voice-over mode:
- Enables hidden audio element when `use_voice_over` and signed audio URL are present: `videoagent-studio/src/components/VideoPlayer.tsx:445`.
- Sets source video to muted during VO playback: `videoagent-studio/src/components/VideoPlayer.tsx:503`.
- Speeds up voice-over if VO duration exceeds clip duration, capped at `2.0x`: `videoagent-studio/src/components/VideoPlayer.tsx:480`.
- Waits for both video and audio readiness before play to avoid partial start: `videoagent-studio/src/components/VideoPlayer.tsx:455`.

### Segment Advancement and Sync
- `requestAnimationFrame` loop updates global timeline position and handles clip boundaries: `videoagent-studio/src/components/VideoPlayer.tsx:560`.
- If video ends before VO, sets `playbackState` to `waiting_for_audio` and delays advancing scenes: `videoagent-studio/src/components/VideoPlayer.tsx:612`.
- Backup `ended` listeners on video/audio prevent missed transitions: `videoagent-studio/src/components/VideoPlayer.tsx:640`.
- Seek handler maps global scrubber time to scene index and source clip offset: `videoagent-studio/src/components/VideoPlayer.tsx:828`.

### Timeline and Trim Integration
- Renders `SceneTimeline` with callbacks for scene selection and trim updates: `videoagent-studio/src/components/VideoPlayer.tsx:1056`.
- `handleTrimChange` performs optimistic local updates to `scenes`: `videoagent-studio/src/components/VideoPlayer.tsx:763`.
- `handleTrimEnd` persists to backend through `api.updateStoryboard`: `videoagent-studio/src/components/VideoPlayer.tsx:782`.

### Export and Feedback
- Export path calls render API and attempts blob download first: `videoagent-studio/src/components/VideoPlayer.tsx:241`.
- Falls back to opening signed URL directly when fetch fails (common signed URL CORS issue): `videoagent-studio/src/components/VideoPlayer.tsx:281`.
- Feedback flow queues per-scene notes and submits batch text to `sendMessage`: `videoagent-studio/src/components/VideoPlayer.tsx:196` and `videoagent-studio/src/components/VideoPlayer.tsx:225`.

## Deep Dive: SceneTimeline
- Computes cumulative segment offsets from scene durations: `videoagent-studio/src/components/SceneTimeline.tsx:38`.
- Converts mouse X position into composition time, then maps into active source clip time: `videoagent-studio/src/components/SceneTimeline.tsx:82`.
- Enforces trim constraints:
- Minimum duration is `0.5s` when no VO, or `0.9 * voice_over.duration`: `videoagent-studio/src/components/SceneTimeline.tsx:69`.
- Maximum duration is source video duration when no VO, or `1.1 * voice_over.duration`: `videoagent-studio/src/components/SceneTimeline.tsx:70`.
- Emits continuous updates during drag via `onTrimChange` and final commit on mouseup via `onTrimEnd`: `videoagent-studio/src/components/SceneTimeline.tsx:137` and `videoagent-studio/src/components/SceneTimeline.tsx:142`.
- Visual behavior:
- Active segment is tall teal bar with trim handles.
- Inactive segments are compact gray bars with hover tooltip metadata.

## Data Contracts And State Flow
- Scene model fields used most in playback:
- `matched_scene.source_video_id`, `start_time`, `end_time`, `description`: `videoagent-studio/src/lib/types.ts:87`
- Voice-over fields:
- `voice_over.audio_url`, `audio_path`, `duration`: `videoagent-studio/src/lib/types.ts:96`
- Metadata fields driving playback:
- `url`, `path`, `duration`: `videoagent-studio/src/lib/types.ts:103`
- Store actions touched by playback and editing:
- `setScenes`, `sendMessage`: `videoagent-studio/src/store/session.ts:86` and `videoagent-studio/src/store/session.ts:230`

## Test Coverage Anchors
- Media source guard behavior and signed URL preference: `videoagent-studio/src/components/VideoPlayer.test.tsx:104`
- Signed URL playback assertion: `videoagent-studio/src/components/VideoPlayer.test.tsx:129`
- Metadata refresh retry and user-facing error after second failure: `videoagent-studio/src/components/VideoPlayer.test.tsx:146`
- Voice-over muting and audio source wiring: `videoagent-studio/src/components/VideoPlayer.test.tsx:174`
- Dual readiness gate (video plus audio): `videoagent-studio/src/components/VideoPlayer.test.tsx:209`
- Export fallback behavior when fetch fails: `videoagent-studio/src/components/VideoPlayer.test.tsx:265`

## Explanation Order
1. Start at `StudioPage` to show where `VideoPlayer` and `Storyboard` fit.
2. Explain data contracts in `types.ts` and how `useSessionStore` supplies `scenes` and callbacks.
3. Walk `VideoPlayer` lifecycle: source resolution -> metadata fetch -> segment playback -> timeline callbacks -> export/feedback.
4. Zoom into `SceneTimeline` for trim math and constraints.
5. End with extension points and concrete file edits for the user's requested change.

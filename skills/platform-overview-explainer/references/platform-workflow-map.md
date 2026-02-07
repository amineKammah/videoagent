# VideoAgent Platform Workflow Map

## Table of Contents
- Product idea
- User-facing flow
- Agent workflow stages
- Tool responsibilities
- Data model and persistence
- API and UI surfaces
- Fallback generation rules
- Suggested explanation sequence

## Product Idea
- The platform takes prospect/customer context and creates a personalized sales video.
- It prioritizes reusing existing company asset videos, then composes a final narrative from selected clips.
- Core backend prompt framing: `backend/src/videoagent/agent/prompts.py:9`.

## User-Facing Flow
1. User provides prospect/customer context (goals, pain points, current tooling, metrics).
2. Agent creates a `VideoBrief` (shown in UI as "Video Brief" in the Project Brief panel).
3. Agent creates storyboard scenes with scripts and audio mode (`use_voice_over`).
4. Agent generates voice-over for VO scenes.
5. Agent matches scenes to candidate company assets.
6. Agent updates matched scenes; render output becomes available in preview/export flow.

## Agent Workflow Stages

### Stage 0: Video Brief (Mandatory)
- Prompt requires this first step before storyboard work: `backend/src/videoagent/agent/prompts.py:17`.
- Persistence tool: `update_video_brief`: `backend/src/videoagent/agent/prompts.py:21`.

### Stage 1: Storyboard
- Agent builds scene-level plan (title, purpose, script, `use_voice_over`): `backend/src/videoagent/agent/prompts.py:32`.
- Persistence tool: `update_storyboard`: `backend/src/videoagent/agent/prompts.py:36`.
- Testimony rule: testimonies should keep authentic audio and be introduced in prior scene: `backend/src/videoagent/agent/prompts.py:38`.

### Stage 2: Production
- Voice-over generation tool: `generate_voice_overs`: `backend/src/videoagent/agent/prompts.py:72`.
- Asset matching tool: `match_scene_to_video`: `backend/src/videoagent/agent/prompts.py:76`.
- AI fallback tool: `generate_scene` only when matching fails or user asks: `backend/src/videoagent/agent/prompts.py:90`.

## Tool Responsibilities
- `update_video_brief`: save objective/persona/key messages: `backend/src/videoagent/agent/tools.py:506`.
- `update_storyboard`: replace storyboard while preserving existing `voice_over` and `matched_scene` fields: `backend/src/videoagent/agent/tools.py:392`.
- `update_matched_scenes`: apply selected clip matches to specific scenes: `backend/src/videoagent/agent/tools.py:471`.
- `generate_voice_overs`: create and persist per-scene voice-over assets: `backend/src/videoagent/agent/tools.py:537`.
- `match_scene_to_video`: evaluate candidate asset clips for each scene request: `backend/src/videoagent/agent/tools.py:633` and `backend/src/videoagent/agent/scene_matcher.py:68`.
- `generate_scene`: generate short AI fallback clips and auto-attach to scene: `backend/src/videoagent/agent/tools.py:769`.

## Data Model And Persistence
- Brief model (`VideoBrief`): objective, persona, key_messages: `videoagent-studio/src/lib/types.ts:114`.
- Scene model (`StoryboardScene`) carries script, `use_voice_over`, `voice_over`, and `matched_scene`: `videoagent-studio/src/lib/types.ts:76`.
- Session context injected into agent includes:
- `video_transcripts` from company library
- current `video_brief`
- current `storyboard_scenes`
- Source: `backend/src/videoagent/agent/service.py:138`.

## API And UI Surfaces
- API `PATCH /agent/sessions/{session_id}/brief`: update brief: `backend/src/videoagent/api.py:370`.
- API `PATCH /agent/sessions/{session_id}/storyboard`: update storyboard: `backend/src/videoagent/api.py:376`.
- UI Project Brief component reads/edits `VideoBrief`: `videoagent-studio/src/components/ProjectBrief.tsx:8`.
- UI naming note: panel label is "Video Brief" under component `ProjectBrief`.

## Fallback Generation Rules
- Use AI generation only as fallback when matching cannot find acceptable assets or user requests generation: `backend/src/videoagent/agent/prompts.py:90`.
- Prerequisite: voice-over must already exist for that scene: `backend/src/videoagent/agent/tools.py:809`.
- Voice-over duration must be under 9 seconds for `generate_scene`: `backend/src/videoagent/agent/tools.py:829`.
- Allowed generated durations: 4, 6, or 8 seconds: `backend/src/videoagent/agent/tools.py:842`.

## Suggested Explanation Sequence
1. One sentence: “Prospect context in, personalized video out.”
2. Explain three stages: brief -> storyboard -> production.
3. Explain audio mode choice per scene (VO vs original audio, especially testimony authenticity).
4. Explain tool chain and fallback branch.
5. If needed, map each concept to file references above.

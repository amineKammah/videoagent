---
name: scene-matching-operator
description: Operate the scene matching loop for VideoAgent from candidate shortlisting through final match updates. Use when matching storyboard scenes to company assets, writing matching notes, handling warnings/errors, or iterating on `match_scene_to_video` and `update_matched_scenes`.
---

# Scene Matching Operator

## Quick Start
- Open `references/scene-matching-runbook.md`.
- Verify Stage 2 constraints in `backend/src/videoagent/agent/prompts.py` before selecting candidates.
- Read current storyboard scene fields (`use_voice_over`, `voice_over.duration`, `script`) before matching.

## Workflow
1. Validate prerequisites.
- Ensure target scene exists.
- Ensure candidate list has at most 5 video IDs.
- If `use_voice_over` is true, ensure voice-over has been generated before matching.
2. Build candidate shortlist.
- Select 3-5 candidate asset IDs per scene from the library.
- Prefer assets that can visually support the script without contradiction.
3. Write strong `notes`.
- State desired visual action, context, pacing, and forbidden visuals.
- Add mode-specific constraints (voice-over mode vs original-audio mode).
4. Execute `match_scene_to_video`.
- Pass one batch request with explicit `scene_id`, `candidate_video_ids`, and `notes`.
5. Triage results.
- Read `results`, `warnings`, `errors`, and any guidance message.
- If warnings or low-quality candidates appear, refine notes and rerun.
6. Commit selected candidates.
- Apply final picks using `update_matched_scenes`.
- Persist storyboard updates before replying.

## Quality Checklist
- Avoid talking heads or burnt subtitles in voice-over scenes.
- Keep testimony scenes authentic and duration-appropriate.
- Do not rely on transcript-only relevance; use tool output and visual fit.
- If script changes affect duration, regenerate voice-over and rematch.

## Failure Handling
- If tool call fails, rerun once.
- If still failing, return concise user-facing status and next action.
- Keep prior valid matches untouched while retrying one scene.

## Output Pattern
- Return concise recommendation by scene.
- Include 1-2 alternative candidates only when quality tradeoffs exist.
- State exactly which scene IDs to update with which video IDs.

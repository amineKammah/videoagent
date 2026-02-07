# Scene Matching Runbook

## Table of Contents
- Core constraints
- Payload contract
- Matching execution path
- Result interpretation
- Update commit path
- Verification script

## Core Constraints
- Matching is Stage 2 and follows voice-over generation for VO scenes: `backend/src/videoagent/agent/prompts.py:72`.
- Keep candidate lists to 3-5 IDs and run `match_scene_to_video` after VO generation: `backend/src/videoagent/agent/prompts.py:75`.
- Do not use transcript-only heuristics as final matching logic: `backend/src/videoagent/agent/prompts.py:85`.

## Payload Contract
- Request schema (`scene_id`, `candidate_video_ids`, `notes`, optional `duration_seconds`): `backend/src/videoagent/agent/schemas.py:64`.
- Batch wrapper schema (`requests`): `backend/src/videoagent/agent/schemas.py:79`.
- `candidate_video_ids` intent includes max-5 expectation: `backend/src/videoagent/agent/schemas.py:66`.

## Matching Execution Path
- Tool entrypoint for matching: `backend/src/videoagent/agent/tools.py:633`.
- Scene matcher orchestration method: `backend/src/videoagent/agent/scene_matcher.py:68`.
- Core validation checks include:
- scene exists and candidates provided: `backend/src/videoagent/agent/scene_matcher.py:231`.
- candidate count <= 5: `backend/src/videoagent/agent/scene_matcher.py:251`.
- candidate IDs exist in library: `backend/src/videoagent/agent/scene_matcher.py:260`.

## Result Interpretation
- Response includes `results` plus optional `warnings` and `errors`: `backend/src/videoagent/agent/scene_matcher.py:127`.
- Tool message instructs follow-up update via `update_matched_scenes`: `backend/src/videoagent/agent/scene_matcher.py:146`.

## Update Commit Path
- Commit selected clip matches with `update_matched_scenes`: `backend/src/videoagent/agent/tools.py:471`.
- Storyboard save and event append happen in this tool path: `backend/src/videoagent/agent/tools.py:495`.

## Verification Script
- End-to-end invocation reference for local validation: `backend/scripts/verify_match_scene.py:24`.
- Script demonstrates wrapped tool payload structure: `backend/scripts/verify_match_scene.py:116`.

# Multi-Candidate Scene Matching and Selection History Migration Plan

Date: 2026-02-06  
Status: Proposed (implementation-ready)  
Primary goal: Let users browse up to 5 ranked scene-match candidates quickly and restore previous selections safely.

## 1. Product Requirements

1. Each scene supports up to 5 ranked candidate clips.
2. User can switch to candidate #2/#3 quickly without opening the scene modal.
3. User can restore a previous selection if it was better.
4. History tracks selection changes only.
5. Trim changes must remain in-place on the active selection and must not create history entries.
6. Re-running matching for the same scene must append/merge new candidates, not wipe candidate/history state.
7. Existing playback/render behavior must remain stable.

## 2. Current State Summary

1. Matching tool already returns multiple candidates in tool output (`backend/src/videoagent/agent/scene_matcher.py`).
2. Storyboard scene persists only one active clip in `matched_scene` (`backend/src/videoagent/story.py`).
3. Frontend player and renderer consume only `matched_scene` (`videoagent-studio/src/components/VideoPlayer.tsx`, `backend/src/videoagent/editor.py`).
4. Storyboards are stored as JSON inside `session_storyboards.scenes` (`backend/src/videoagent/db/models.py`).

## 3. Core Design Decisions

1. Keep `matched_scene` as the canonical active clip for playback/render.
2. Add candidate and history fields to storyboard scene JSON.
3. Candidate and history updates use narrow server-side merge operations.
4. Do not rely on full storyboard rewrites for candidate selection actions.
5. Preserve all specialized scene fields when storyboard structure updates are saved by `scene_id`.

## 4. Target Scene Schema

Add the following fields to `_StoryboardScene` in `backend/src/videoagent/story.py`:

```json
{
  "scene_id": "scene_1",
  "title": "string",
  "purpose": "string",
  "script": "string",
  "use_voice_over": true,
  "voice_over": {},
  "matched_scene": {},
  "matched_scene_candidates": [
    {
      "candidate_id": "cand_abc123",
      "source_video_id": "video_1",
      "start_time": 12.3,
      "end_time": 18.7,
      "description": "what is shown",
      "rationale": "why it fits",
      "keep_original_audio": false,
      "last_rank": 1,
      "shortlisted": true,
      "created_at": "2026-02-06T10:10:00Z",
      "updated_at": "2026-02-06T10:10:00Z"
    }
  ],
  "selected_candidate_id": "cand_abc123",
  "matched_scene_history": [
    {
      "entry_id": "hist_001",
      "candidate_id": "cand_prev999",
      "changed_at": "2026-02-06T10:15:00Z",
      "changed_by": "user",
      "reason": "restored older option"
    }
  ]
}
```

## 5. Data Invariants

1. `matched_scene` must always mirror `selected_candidate_id` when selected candidate exists.
2. `matched_scene_candidates` max length in active shortlist is 5.
3. Candidate pool can be larger than 5, but UI shortlist must always be max 5.
4. `matched_scene_history` records only selection transitions.
5. Trim-only changes (`start_time`/`end_time` on current selected candidate) do not create history entries.
6. Consecutive duplicate history entries are not allowed.
7. History length is capped (recommended: 20 entries per scene).

## 6. Candidate Identity and Merge Rules

Candidate dedupe fingerprint:

1. `source_video_id`
2. rounded `start_time` (for example 0.1s precision)
3. rounded `end_time`

Merge behavior on new matching results:

1. Upsert candidates by fingerprint.
2. Update `last_rank`, `shortlisted`, `updated_at`.
3. Keep older candidates in pool unless explicit pruning policy is applied.
4. If no selected candidate exists, auto-select best ranked candidate and sync `matched_scene`.
5. If selected candidate still exists after merge, keep it selected.

## 7. Backend Changes

## 7.1 Models and Schemas

1. `backend/src/videoagent/story.py`
   - Add candidate model and history model.
   - Extend `_StoryboardScene`.
2. `backend/src/videoagent/agent/schemas.py`
   - Extend payloads for candidate merge/select/restore actions.
   - Keep backward-compatible payload shape for existing clients/tools.

## 7.2 Tooling

1. Update `update_matched_scenes` in `backend/src/videoagent/agent/tools.py`:
   - Accept candidate deltas.
   - Merge with existing scene state.
   - Apply selection transition and history append.
2. Add dedicated tools:
   - `select_scene_candidate(scene_id, candidate_id, reason?)`
   - `restore_scene_selection(scene_id, history_entry_id, reason?)`
3. Keep `update_storyboard` and `update_storyboard_scene` preserving new fields by `scene_id`.

## 7.3 Scene Matcher Output Mapping

1. Keep matcher flow in `backend/src/videoagent/agent/scene_matcher.py`.
2. Normalize matcher output into candidate shape expected by merge logic.
3. Enforce max 5 shortlisted ranked candidates per run.

## 8. Main Agent Behavior

Update prompt guidance in `backend/src/videoagent/agent/prompts.py`:

1. After `match_scene_to_video`, persist ranked candidates and choose active selection.
2. On re-run for same scene, add/merge candidates rather than replacing full scene object.
3. Use restore/select tools for candidate switching actions.
4. Do not create history for trim refinements.

## 9. API Changes for Frontend

Add narrow endpoints in `backend/src/videoagent/api.py`:

1. `POST /agent/sessions/{session_id}/scenes/{scene_id}/select-candidate`
2. `POST /agent/sessions/{session_id}/scenes/{scene_id}/restore-selection`
3. Optional: `POST /agent/sessions/{session_id}/scenes/{scene_id}/merge-candidates`

Response pattern:

1. Return updated scene.
2. Emit `storyboard_update` event so existing SSE/polling refresh flow still works.

## 10. Frontend UX and Interaction Design

## 10.1 Quick Access in Player (no modal required)

File: `videoagent-studio/src/components/VideoPlayer.tsx`

1. Add candidate pill strip for active scene (`#1 #2 #3 #4 #5`).
2. Clicking a pill switches active candidate immediately.
3. Add `Undo last` button for fast restore of previous selection.
4. Keep timeline trim behavior unchanged.
5. Trim commits still call storyboard update, but do not touch history endpoints.

## 10.2 Full Detail in Scene Modal

File: `videoagent-studio/src/components/Storyboard.tsx`

1. Show `Alternatives` list with rank, range, source, description, rationale.
2. Show `History` list with timestamp and restore button.
3. Show selected marker and allow explicit `Use this candidate`.
4. Keep modal optional for detailed inspection only.

## 10.3 Types and State

1. Extend `StoryboardScene` in `videoagent-studio/src/lib/types.ts`.
2. Keep existing app store shape in `videoagent-studio/src/store/session.ts`.
3. Optional transient preview state is allowed, but history updates occur only on committed selection.

## 11. Single Production DB Safety Plan (GCP)

You have one main DB in production. Use expand/contract with compatibility-first rollout.

## 11.1 Phase 0 - Safety Preconditions

1. Create a verified restore point (backup/snapshot) before deployment.
2. Restore that backup to a temporary clone and run a restore drill.
3. Confirm rollback owner and rollback SLA before starting.

## 11.2 Phase 1 - Backend Compatibility Deployment

1. Deploy backend that can read old and new scene JSON.
2. New fields optional, no backfill required yet.
3. Keep frontend unchanged at this phase.

## 11.3 Phase 2 - Narrow Mutation Endpoints and Tools

1. Deploy select/restore/merge endpoints and tool changes.
2. Keep feature flags off for user-visible UI until validated.

## 11.4 Phase 3 - Internal Enablement

1. Enable feature flags for internal users only.
2. Monitor error rate and scene serialization issues.
3. Validate no regressions in render/export/playback.

## 11.5 Phase 4 - Frontend Rollout

1. Deploy candidate strip + history UI.
2. Enable for small cohort first, then full rollout.

## 11.6 Phase 5 - Optional Backfill

Backfill is optional because compatibility read path exists.

1. Run idempotent backfill in batches:
   - If scene has `matched_scene` and no candidates: create one candidate and set selected id.
   - Initialize empty history.
2. Use dry run mode and audit logs.
3. Abort criteria on elevated errors.

## 12. Feature Flags

Recommended flags:

1. `SCENE_CANDIDATES_ENABLED`
2. `SCENE_SELECTION_HISTORY_ENABLED`
3. `PLAYER_CANDIDATE_SWITCHER_ENABLED`
4. `SCENE_HISTORY_RESTORE_ENABLED`

Rollout order:

1. Backend flags on internally.
2. Player switcher on for canary users.
3. History restore on after stability confirmation.

## 13. Concurrency and Data Integrity

1. Wrap select/restore/merge actions in a transaction.
2. Lock storyboard row while merging to avoid lost updates.
3. Validate payload limits server-side:
   - shortlist <= 5
   - history <= cap
   - valid selected candidate id
4. Never trust frontend to maintain consistency.

## 14. Rollback Plan

1. Immediate mitigation:
   - Disable feature flags.
2. Application rollback:
   - Redeploy previous backend/frontend image.
3. Data rollback:
   - Usually not required if old code ignores unknown JSON fields.
   - Use backup restore only for confirmed corruption.

## 15. Testing Plan

## 15.1 Backend Tests

1. Merge dedupe and rank update.
2. Selection change appends history.
3. Trim-only update does not append history.
4. Restore swaps active selection and appends prior active.
5. Backward compatibility with old storyboard JSON.

## 15.2 API/Integration Tests

1. Select endpoint updates scene and emits `storyboard_update`.
2. Restore endpoint updates scene and emits `storyboard_update`.
3. Existing render endpoint still works with new scene JSON.

## 15.3 Frontend Tests

1. Candidate pills visible for active scene.
2. Candidate switch works without opening modal.
3. Undo/restore flow works.
4. Trim flow unchanged and no history side effects.

## 16. Implementation Sequence (PR Plan)

1. PR-1: Data model and schema extensions, compatibility readers.
2. PR-2: Merge/select/restore backend logic, tool changes, tests.
3. PR-3: API endpoints for select/restore and event emission.
4. PR-4: Prompt updates for main agent candidate workflow.
5. PR-5: Frontend types + player quick switch + modal history.
6. PR-6: Optional backfill script and operational runbook.
7. PR-7: Canary enablement and production rollout.

## 17. Acceptance Criteria

1. User switches among up to 5 ranked candidates from player UI.
2. User restores prior selection successfully.
3. Re-running matching appends/merges candidate pool for same scene.
4. History contains selection transitions only.
5. Trim edits do not add history.
6. Playback/render/export continue using active `matched_scene` without regressions.

## 18. Open Items (Decide Before Build)

1. Candidate pool retention policy:
   - unlimited vs capped (recommended cap: 50 per scene)
2. History cap:
   - recommended 20 entries per scene
3. Candidate fingerprint precision:
   - recommended 0.1s rounding
4. Whether to expose rationale in player tooltip or modal only.


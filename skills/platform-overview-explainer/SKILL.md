---
name: platform-overview-explainer
description: Explain the end-to-end platform concept for VideoAgent, including how prospect/customer context is converted into personalized sales videos from existing company assets. Use when asked for product overviews, workflow walkthroughs, architecture summaries, agent-tool responsibilities, or stage-by-stage explanation of brief, storyboard, matching, voice-over, and AI fallback generation.
---

# Platform Overview Explainer

## Quick Start
- Open `references/platform-workflow-map.md`.
- Anchor the explanation on `backend/src/videoagent/agent/prompts.py` first.
- If the user asks for technical details, trace through:
- `backend/src/videoagent/agent/service.py`
- `backend/src/videoagent/agent/tools.py`
- `backend/src/videoagent/agent/scene_matcher.py`
- `videoagent-studio/src/components/ProjectBrief.tsx`

## Explanation Workflow
1. Start with the one-sentence product idea.
- Explain that the platform transforms prospect/customer context into a personalized sales video by recombining company video assets.
2. Explain the staged workflow in order.
- Stage 0: Video brief creation.
- Stage 1: Storyboard scene creation.
- Stage 2: Voice-over generation, scene matching, optional AI scene fallback, and rendering.
3. Clarify audio strategy.
- State that scenes may use generated voice-over or keep original clip audio (especially testimonies).
4. Map platform behavior to tools.
- Cover `update_video_brief`, `update_storyboard`, `generate_voice_overs`, `match_scene_to_video`, `update_matched_scenes`, and `generate_scene`.
5. Clarify persistence and UI.
- Mention that tool calls persist state and frontend reads updated brief/storyboard via API.

## Operator Runbook
1. Enforce stage order.
- Do not skip Stage 0 (brief) before Stage 1 and Stage 2.
2. Persist before reply.
- Ensure storyboard/brief updates are saved through update tools before sending user-facing text.
3. Treat matching as iterative.
- If candidate quality is weak or warnings exist, refine notes and rerun matching before committing.
4. Use fallback generation narrowly.
- Use AI scene generation only when asset matching cannot satisfy requirements or the user asks.

## Output Format
- Short concept summary.
- Stage-by-stage workflow bullets.
- Tool responsibility bullets.
- Optional technical appendix with file references when requested.

## Guardrails
- Use user-friendly language first; add tool names when helpful or explicitly requested.
- Keep the distinction clear between default path (existing asset matching) and fallback path (`generate_scene`).
- Clarify that UI label "Project Brief" corresponds to backend/frontend `VideoBrief`.
- Keep responses concise unless the user asks for deep architecture detail.

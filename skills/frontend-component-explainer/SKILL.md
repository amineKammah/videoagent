---
name: frontend-component-explainer
description: Explain VideoAgent Studio frontend components for onboarding, debugging, and implementation planning. Use when asked to map responsibilities, props and state flow, store and API interactions, or editing and playback behavior in `videoagent-studio/src`, especially `VideoPlayer.tsx` and `SceneTimeline.tsx`.
---

# Frontend Component Explainer

## Quick Start
- Open `references/studio-frontend-map.md`.
- Read `videoagent-studio/src/app/studio/page.tsx` first to anchor page composition.
- If the request involves playback, seeking, audio sync, trimming, or export, inspect both `videoagent-studio/src/components/VideoPlayer.tsx` and `videoagent-studio/src/components/SceneTimeline.tsx` before answering.
- If the request involves data shape or persistence, inspect `videoagent-studio/src/lib/types.ts`, `videoagent-studio/src/store/session.ts`, and `videoagent-studio/src/lib/api.ts`.

## Explanation Workflow
1. Identify scope.
- Decide whether the user needs route-level layout, single-component walkthrough, or behavior trace.
2. Trace data flow in this order.
- Follow `useSessionStore` state into component props, then into handlers, then into API side effects.
3. Deep dive required components when relevant.
- `VideoPlayer`: cover media source resolution, metadata loading, playback transitions, voice-over sync, seek and trim behavior, export and feedback.
- `SceneTimeline`: cover segment math, drag constraints, and callback contracts (`onTrimChange`, `onTrimEnd`).
4. Surface extension points and risks.
- Call out where to add features safely and where race conditions or stale-state reads could occur.
5. Cite concrete file locations.
- Attach file references for every non-obvious claim.

## Output Format
- Start with a short architecture summary.
- List component responsibilities.
- Describe data flow step-by-step.
- Add a dedicated focus section for `VideoPlayer` and `SceneTimeline` when either component is in scope.
- End with change guidance that names exact files to edit.

## Guardrails
- Prefer concrete behavior over generic React advice.
- Do not assume backend guarantees that are not explicit in frontend code.
- Mention dead props, unused state, or TODO-like comments only when they affect understanding or maintainability.
- Keep explanations concise unless the user asks for full internals.

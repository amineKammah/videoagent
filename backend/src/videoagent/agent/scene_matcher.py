"""Scene matching pipeline for match_scene_to_video."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from google.genai import types
from pydantic import ValidationError

from videoagent.config import Config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.story import _StoryboardScene

from .schemas import (
    SceneMatchBatchRequest,
    SceneMatchRequest,
    SceneMatchResponse,
    SceneMatchVoiceOverResponse,
)
from .storage import EventStore, StoryboardStore, _parse_timestamp


class SceneMatchMode(str, Enum):
    """Audio mode for scene matching."""

    VOICE_OVER = "voice_over"
    ORIGINAL_AUDIO = "original_audio"


@dataclass(frozen=True)
class SceneMatchJob:
    """A single scene x candidate-video evaluation job."""

    scene_id: str
    scene: _StoryboardScene
    video_id: str
    metadata: object
    notes: str
    mode: SceneMatchMode
    duration_section: str
    target_duration: Optional[float]
    start_offset_seconds: Optional[float] = None
    end_offset_seconds: Optional[float] = None


# Keep this aligned with tools._check_scene_warnings (>10% is considered mismatch).
_VOICE_OVER_DURATION_MISMATCH_RATIO_THRESHOLD = 0.10


class SceneMatcher:
    """Encapsulates scene-to-video matching orchestration."""

    def __init__(
        self,
        config: Config,
        storyboard_store: StoryboardStore,
        event_store: EventStore,
        session_id: str,
        company_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        self.config = config
        self.storyboard_store = storyboard_store
        self.event_store = event_store
        self.session_id = session_id
        self.company_id = company_id
        self.user_id = user_id

    async def match_scene_to_video(self, payload: SceneMatchBatchRequest) -> str:
        """Find candidate video clips for one or more storyboard scenes using uploaded video context."""
        scenes = self.storyboard_store.load(self.session_id, user_id=self.user_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before matching scenes."
        if not payload.requests:
            return "No scene match requests provided."

        library = VideoLibrary(self.config, company_id=self.company_id)
        library.scan_library()

        # 1. Validation and Job Building
        jobs, errors, warnings_by_scene_id = _validate_and_build_jobs(
            payload.requests,
            scenes,
            library,
        )
        if not jobs:
            response_payload = {"results": []}
            if errors:
                response_payload["errors"] = errors
            return json.dumps(response_payload)

        # 2. Upload Videos
        client = GeminiClient(self.config)
        client.use_vertexai = True
        uploaded_files, failed_uploads = _upload_job_videos(client, jobs)

        # Filter jobs if upload failed
        valid_jobs: list[SceneMatchJob] = []
        for job in jobs:
            if job.video_id in failed_uploads:
                errors.append(
                    {
                        "scene_id": job.scene_id,
                        "video_id": job.video_id,
                        "error": f"Failed to upload video: {failed_uploads[job.video_id]}",
                    }
                )
            else:
                valid_jobs.append(job)
        jobs = valid_jobs

        if not jobs:
            response_payload = {"results": []}
            if errors:
                response_payload["errors"] = errors
            return json.dumps(response_payload)

        # 3. Execution (Analysis)
        analysis_results = await _execute_analysis_jobs(client, jobs, uploaded_files)

        # 4. Processing Results
        results_by_scene_id, notes_by_scene_id = _process_analysis_results(
            jobs,
            analysis_results,
            errors,
        )

        response_payload = {
            "results": list(results_by_scene_id.values()),
        }
        if notes_by_scene_id:
            response_payload["notes"] = notes_by_scene_id
        if warnings_by_scene_id:
            final_warnings = {k: v for k, v in warnings_by_scene_id.items() if v}
            if final_warnings:
                response_payload["warnings"] = final_warnings
        if errors:
            response_payload["errors"] = errors

        self.event_store.append(
            self.session_id,
            {"type": "video_render_complete"},
            user_id=self.user_id,
        )

        return (
            f"{json.dumps(response_payload)}\n"
            "Message: Review the candidates above. Curate the 2-4 BEST candidates per scene "
            "(ranked from best to worst) and call 'set_scene_candidates' to save them. "
            "The UI will display your curated candidates so the user can switch between "
            "alternatives without another LLM call. "
            "If no clips match the requirements, update the notes and call this tool again."
        )


def _duration_section(target_duration: Optional[float]) -> str:
    if not target_duration:
        return ""
    return f"Duration Target: {target_duration}s (Tolerance: +/- 1s)\n"


def _analysis_window_section(job: SceneMatchJob) -> str:
    if job.start_offset_seconds is None or job.end_offset_seconds is None:
        return ""
    return (
        "Analysis Window (Sub-Span):\n"
        f"- Start: {job.start_offset_seconds:.3f}s\n"
        f"- End: {job.end_offset_seconds:.3f}s\n"
        "- Analyze ONLY this window and return timestamps in absolute source-video time.\n"
    )


def _build_voice_over_jobs(
    request: SceneMatchRequest,
    scene: _StoryboardScene,
    candidate_ids: list[str],
    video_map: dict[str, object],
    duration_section: str,
    target_duration: Optional[float],
    start_offset_seconds: Optional[float],
    end_offset_seconds: Optional[float],
) -> list[SceneMatchJob]:
    jobs: list[SceneMatchJob] = []
    for video_id in candidate_ids:
        metadata = video_map.get(video_id)
        if not metadata:
            continue
        jobs.append(
            SceneMatchJob(
                scene_id=request.scene_id,
                scene=scene,
                video_id=video_id,
                metadata=metadata,
                notes=request.notes,
                mode=SceneMatchMode.VOICE_OVER,
                duration_section=duration_section,
                target_duration=target_duration,
                start_offset_seconds=start_offset_seconds,
                end_offset_seconds=end_offset_seconds,
            )
        )
    return jobs


def _build_original_audio_jobs(
    request: SceneMatchRequest,
    scene: _StoryboardScene,
    candidate_ids: list[str],
    video_map: dict[str, object],
    duration_section: str,
    target_duration: Optional[float],
    start_offset_seconds: Optional[float],
    end_offset_seconds: Optional[float],
) -> list[SceneMatchJob]:
    jobs: list[SceneMatchJob] = []
    for video_id in candidate_ids:
        metadata = video_map.get(video_id)
        if not metadata:
            continue
        jobs.append(
            SceneMatchJob(
                scene_id=request.scene_id,
                scene=scene,
                video_id=video_id,
                metadata=metadata,
                notes=request.notes,
                mode=SceneMatchMode.ORIGINAL_AUDIO,
                duration_section=duration_section,
                target_duration=target_duration,
                start_offset_seconds=start_offset_seconds,
                end_offset_seconds=end_offset_seconds,
            )
        )
    return jobs


def _validate_and_build_jobs(
    requests: list[SceneMatchRequest],
    scenes: list[_StoryboardScene],
    video_library: VideoLibrary,
) -> tuple[list[SceneMatchJob], list[dict], dict[str, list[str]]]:
    """Validate request and build jobs. Returns (jobs, errors, warnings)."""
    scene_map = {scene.scene_id: scene for scene in scenes}

    all_candidate_ids = {
        video_id for request in requests for video_id in request.candidate_video_ids
    }
    video_map = {
        video_id: video_library.get_video(video_id)
        for video_id in all_candidate_ids
    }

    jobs: list[SceneMatchJob] = []
    errors: list[dict] = []
    warnings_by_scene_id: dict[str, list[str]] = {}

    for request in requests:
        scene = scene_map.get(request.scene_id)
        if not scene:
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": f"Storyboard scene id not found: {request.scene_id}",
                }
            )
            continue

        if not request.candidate_video_ids:
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": "No candidate videos provided.",
                }
            )
            continue

        if len(request.candidate_video_ids) > 5:
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": "Provide up to 5 candidate video ids.",
                }
            )
            continue

        invalid_ids = [
            video_id
            for video_id in request.candidate_video_ids
            if not video_map.get(video_id)
        ]
        if invalid_ids:
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": "Video id(s) not found: " + ", ".join(invalid_ids),
                }
            )
            continue

        voice_over = scene.voice_over
        if scene.use_voice_over and not (voice_over and voice_over.duration) and request.duration_seconds is None:
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": (
                        "Voice over duration missing for this scene. "
                        "Generate voice overs first for scenes that need them, "
                        "or provide duration_seconds."
                    ),
                }
            )
            continue

        target_duration = None
        if voice_over and voice_over.duration:
            target_duration = voice_over.duration
        elif request.duration_seconds is not None:
            target_duration = request.duration_seconds

        warnings_by_scene_id.setdefault(request.scene_id, [])
        if request.duration_seconds is not None and not (voice_over and voice_over.duration):
            warnings_by_scene_id[request.scene_id].append(
                "duration_seconds was provided without a voice over; "
                "used it as the target duration for matching."
            )

        duration_section = _duration_section(target_duration)

        start_offset_seconds = request.start_offset_seconds
        end_offset_seconds = request.end_offset_seconds
        if (start_offset_seconds is None) != (end_offset_seconds is None):
            errors.append(
                {
                    "scene_id": request.scene_id,
                    "error": (
                        "Provide both start_offset_seconds and end_offset_seconds, "
                        "or omit both."
                    ),
                }
            )
            continue
        if start_offset_seconds is not None and end_offset_seconds is not None:
            if start_offset_seconds < 0:
                errors.append(
                    {
                        "scene_id": request.scene_id,
                        "error": "start_offset_seconds must be >= 0.",
                    }
                )
                continue
            if end_offset_seconds <= start_offset_seconds:
                errors.append(
                    {
                        "scene_id": request.scene_id,
                        "error": "end_offset_seconds must be greater than start_offset_seconds.",
                    }
                )
                continue

        if scene.use_voice_over:
            jobs.extend(
                _build_voice_over_jobs(
                    request=request,
                    scene=scene,
                    candidate_ids=request.candidate_video_ids,
                    video_map=video_map,
                    duration_section=duration_section,
                    target_duration=target_duration,
                    start_offset_seconds=start_offset_seconds,
                    end_offset_seconds=end_offset_seconds,
                )
            )
        else:
            jobs.extend(
                _build_original_audio_jobs(
                    request=request,
                    scene=scene,
                    candidate_ids=request.candidate_video_ids,
                    video_map=video_map,
                    duration_section=duration_section,
                    target_duration=target_duration,
                    start_offset_seconds=start_offset_seconds,
                    end_offset_seconds=end_offset_seconds,
                )
            )

    return jobs, errors, warnings_by_scene_id


def _upload_job_videos(
    client: GeminiClient,
    jobs: list[SceneMatchJob],
) -> tuple[dict[str, object], dict[str, str]]:
    """Upload videos for the jobs. Returns (uploaded_files_map, failed_uploads_map)."""
    uploaded_files: dict[str, object] = {}
    failed_uploads: dict[str, str] = {}

    video_id_to_metadata = {job.video_id: job.metadata for job in jobs}
    
    # Determine which videos MUST have original audio
    video_ids_needing_audio = set()
    for job in jobs:
        if job.mode == SceneMatchMode.ORIGINAL_AUDIO:
            video_ids_needing_audio.add(job.video_id)

    for video_id in video_id_to_metadata:
        metadata = video_id_to_metadata[video_id]
        print(metadata)
        
        path = metadata.path
        # Use voiceless video ONLY if:
        # 1. It is NOT required to have audio by any job in this batch
        # 2. It IS effectively used in a VOICE_OVER job (implied by not being in needing_audio, 
        #    since if it's in the batch it must be in at least one job)
        if video_id not in video_ids_needing_audio:
            # Switch to voiceless video path
            if "/videos/" in path:
                path = path.replace("/videos/", "/videos_voiceless/")
        
        try:
            uploaded_files[video_id] = client.get_or_upload_file(path)
        except Exception as exc:
            failed_uploads[video_id] = str(exc)

    return uploaded_files, failed_uploads


def _build_voice_over_prompt(job: SceneMatchJob) -> str:
    scene_text = f'Voice-Over Script: "{job.scene.script}"' if job.scene.script else "Voice-Over Script: (None)"
    metadata = job.metadata
    window_section = _analysis_window_section(job)
    return f"""You are an expert Video Editor.
Your task is to find a background video clip that perfectly fits a voice-over script.

### AUDIO MODE: REPLACE WITH VOICE OVER
The original audio of the source video will be removed.

### 1. ANALYZE THE CONTEXT
Scene Title: {job.scene.title}
Scene Purpose: {job.scene.purpose}
{scene_text}
Agent Notes: {job.notes}

### 2. STRICT VISUAL RULES (CRITICAL)
Since this is a background for a voice-over:
- [ ] NO TALKING HEADS: Do NOT select clips where people are speaking to the camera.
- [ ] NO EDGE CASES: Be mindful of clips where there is a camera recording of a
person speaking to the camera on the edge of the frame.
- [ ] NO SUBTITLES: Do NOT select clips with burnt-in subtitles.
- [ ] COMPATIBLE WITH SCRIPT: You should not include scenes with text overs and
widgets that don’t match the scene script. Ensure the selected clip is compatible
with the scene script.
- [ ] NO STATIC SCENES: Do NOT select clips where there is a static frame for the entire duration of the clip.

### 3. YOUR MISSION
Evaluate the single video provided below.
1. Find a continuous clip that matches the Voice-Over Script and Agent Notes.
2. {job.duration_section}
3. Only perfect matches**: Pay very careful attention to the candidate visual description and ensure it works perfectly with the voiceover.
    * If the clip only matches visually part of the script, Do NOT return it.
    * E.g. If the voice over script talks about a product, but the clip shows a similar but different product, discard it.
    * E.g. If the voice over script talks about a painpoint, but the clip shows the solution, discard it.
    * E.g. If the script talks about integration with company X, and the clip shows a generic office environment, DO NOT return it.
    * E.g. If the video has a logo that has nothing to do with the voice over, you should not include this video.
    * We need to hold an extremely high bar for the produced videos. If you are not 100% sure that the clip works with the voiceover, discard it.
4. This video will be used a B2B sales video. The quality bar is very high. If there is no perfect matches, DO NOT return it. 

### 4. Scene-Specific Priorities
- **Intro:** Highest bar in the video; must be specific, authentic, and immediately engaging. Avoid product demos at this stage.
- **Closing:** Must clearly show the company logo and feel brand-authentic.


### 5 Hard Rejection Checklist (Non-Negotiable)
Reject immediately if any condition is true:
1. Visual is adjacent but not exact to script meaning.
2. Wrong industry context/environment cues.
3. Competitor brand/logo/UI appears when a specific brand is referenced.
4. Shows the solution LOGO when a pain is being discussed in the voice over.
5. Voice over talks about Pain but visual shows a solution, or vice versa.
6. Technical-function mismatch (e.g., analytics visuals for compliance/reporting claim).
7. Script has multiple key points but visual supports only part.
8. VO scene has speaking talking head or obvious mouth-sync conflict.
9. Burned-in subtitles/captions/[MUSIC] tags/conflicting overlays.
10. Language mismatch for original-audio scenes.
11. Intro feels generic or weak.
15. Personalization cues in early scenes are not visually supported.
17. Style/quality breaks continuity of the full video.
18. Confidence is below perfect-match bar.


### VIDEO TO EVALUATE
- ID: {metadata.id}
- Filename: {metadata.filename}
- Total Duration: {metadata.duration:.1f}s
{window_section}

### OUTPUT INSTRUCTIONS
- Make sure each candidate clip is -/+1second of the target duration.
- Return up to 3 candidate clips, RANKED from best to worst.
- The first candidate should be your top recommendation.
- Return EXACTLY the `video_id` provided above.
- Include a detailed visual description for each candidate. This description MUST include all the logos, text, and any other elements that are present in the clip.
- Include rationale proving visual-rules compliance.

Example Output:
{{
  "candidates": [
    {{
      "video_id": "{metadata.id}",
      "start_timestamp": "00:12.500",
      "end_timestamp": "00:30.000",
      "description": "...",
      "rationale": "Confirmed: No talking...",
      "no_talking_heads_confirmed": true,
      "no_subtitles_confirmed": true,
      "no_camera_recording_on_edge_of_frame_confirmed": true,
      "clip_compatible_with_scene_script_confirmed": true
    }}
  ]
}}
"""


def _build_original_audio_prompt(job: SceneMatchJob) -> str:
    scene_text = f'Script/Target Line: "{job.scene.script}"' if job.scene.script else "Script/Target Line: (None)"
    metadata = job.metadata
    window_section = _analysis_window_section(job)
    return f"""You are an expert Video Editor.
Your task is to find a talking segment where original audio should be kept.

### AUDIO MODE: KEEP ORIGINAL AUDIO
The selected clip must contain usable on-camera speech that matches the scene intent.

### 1. ANALYZE THE CONTEXT
Scene Title: {job.scene.title}
Scene Purpose: {job.scene.purpose}
{scene_text}
Agent Notes: {job.notes}

### 2. STRICT AUDIO/VISUAL RULES (CRITICAL)
- [ ] TALKING HEAD REQUIRED: Select clips where a person is clearly speaking to camera.
- [ ] NO B-ROLL: Avoid cutaways/wide shots where speaker is absent.
- [ ] HARD IN/OUT TIMING: Start on the first meaningful spoken word and end immediately after final syllable.

### 3. YOUR MISSION
Evaluate the single video provided below.
1. Find a continuous speaking clip matching the scene context.
2. {job.duration_section}
3. Use transcript + visual cues to align timestamps tightly to speech.

### VIDEO TO EVALUATE
- ID: {metadata.id}
- Filename: {metadata.filename}
- Total Duration: {metadata.duration:.1f}s
{window_section}

### OUTPUT INSTRUCTIONS
- Return up to 3 candidate clips, RANKED from best to worst.
- The first candidate should be your top recommendation.
- Return EXACTLY the `video_id` provided above.
- Include what is being said and seen in each candidate description.
- Include rationale confirming speaking-head and timing rule compliance.

Example Output:
{{
  "candidates": [
    {{
      "video_id": "{metadata.id}",
      "start_timestamp": "00:12.500",
      "end_timestamp": "00:30.000",
      "description": "...",
      "rationale": "Confirmed: Speaker on-camera and tightly trimmed."
    }}
  ]
}}
"""


def _response_schema_for_mode(job: SceneMatchJob) -> dict:
    # Placeholder for mode-specific output schemas.
    if job.mode == SceneMatchMode.VOICE_OVER:
        return SceneMatchVoiceOverResponse.model_json_schema()
    return SceneMatchResponse.model_json_schema()


def _parse_voice_over_response(raw_json: str) -> SceneMatchVoiceOverResponse:
    return SceneMatchVoiceOverResponse.model_validate_json(raw_json)


def _parse_original_audio_response(raw_json: str) -> SceneMatchResponse:
    return SceneMatchResponse.model_validate_json(raw_json)


def _parse_response_for_mode(job: SceneMatchJob, raw_json: str) -> SceneMatchResponse:
    if job.mode == SceneMatchMode.VOICE_OVER:
        return _parse_voice_over_response(raw_json)
    return _parse_original_audio_response(raw_json)


def _print_prompt_log(
    job: SceneMatchJob,
    llm_response_time: Optional[float],
    usage: Optional[object] = None,
) -> None:
    dur = f"{llm_response_time:.2f}s" if llm_response_time is not None else "N/A"
    mode = job.mode.value
    tokens = ""
    if usage:
        prompt_tok = getattr(usage, "prompt_token_count", "?")
        cand_tok = getattr(usage, "candidates_token_count", "?")
        tokens = f" (in: {prompt_tok}, out: {cand_tok})"
    print(f"[Analysis] {job.scene_id}:{job.video_id}:{mode} finished in {dur}{tokens}")


def _clip_duration_matches_target(
    *,
    clip_start: float,
    clip_end: float,
    target_duration: Optional[float],
) -> bool:
    """Return True when clip duration is within the accepted mismatch threshold."""
    if target_duration is None or target_duration <= 0:
        return True

    clip_duration = float(clip_end) - float(clip_start)
    if clip_duration <= 0:
        return False

    diff_ratio = abs(clip_duration - target_duration) / target_duration
    return diff_ratio <= _VOICE_OVER_DURATION_MISMATCH_RATIO_THRESHOLD


def _duration_mismatch_ratio(
    *,
    clip_start: float,
    clip_end: float,
    target_duration: Optional[float],
) -> Optional[float]:
    """Return mismatch ratio for clip vs target duration, or None when not applicable."""
    if target_duration is None or target_duration <= 0:
        return None

    clip_duration = float(clip_end) - float(clip_start)
    if clip_duration <= 0:
        return None

    return abs(clip_duration - target_duration) / target_duration


async def _analyze_job_with_prompt(
    client: GeminiClient,
    job: SceneMatchJob,
    uploaded_file: Optional[object],
    prompt: str,
) -> dict:
    """Shared LLM execution path; mode-specific parts are routed around this."""


    if not uploaded_file:
        _print_prompt_log(job, None)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": "Video file was not uploaded.",
        }

    video_part = uploaded_file
    if (
        isinstance(uploaded_file, types.Part)
        and uploaded_file.file_data is not None
        and job.start_offset_seconds is not None
        and job.end_offset_seconds is not None
    ):
        video_part = types.Part(
            file_data=uploaded_file.file_data,
            video_metadata=types.VideoMetadata(
                start_offset=f"{job.start_offset_seconds:.3f}s",
                end_offset=f"{job.end_offset_seconds:.3f}s",
            ),
        )
    contents = types.Content(role="user", parts=[video_part, types.Part(text=prompt)])
    llm_start = time.perf_counter()
    try:
        response = await client.client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": _response_schema_for_mode(job),
                "thinking_config": types.ThinkingConfig(thinking_budget=6024),
            },
        )
    except Exception as exc:
        _print_prompt_log(job, time.perf_counter() - llm_start, None)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": f"LLM generation failed: {exc}",
        }

    llm_response_time = time.perf_counter() - llm_start
    if not response.text:
        _print_prompt_log(job, llm_response_time, response.usage_metadata)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": "Model returned an empty response.",
        }

    try:
        selection = _parse_response_for_mode(job, response.text)
    except ValidationError as exc:
        _print_prompt_log(job, llm_response_time, response.usage_metadata)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": f"Model response validation error: {exc}",
        }

    invalid_selected = [
        c.video_id for c in selection.candidates if c.video_id != job.video_id
    ]
    if invalid_selected:
        _print_prompt_log(job, llm_response_time, response.usage_metadata)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": f"Model selected bad video_id(s): {', '.join(invalid_selected)}",
        }

    # Filter candidates based on confirmation flags (Voice Over mode only)
    if job.mode == SceneMatchMode.VOICE_OVER:
        valid_candidates = []
        for cand in selection.candidates:
            # We assume selection.candidates are SceneMatchVoiceOverCandidate objects
            # which have the boolean flags.
            # Per plan: Discard if any flag is FALSE.
            if (
                cand.no_talking_heads_confirmed and
                cand.no_subtitles_confirmed and
                cand.no_camera_recording_on_edge_of_frame_confirmed and
                cand.clip_compatible_with_scene_script_confirmed
            ):
                valid_candidates.append(cand)
        selection.candidates = valid_candidates

    try:
        normalized_candidates = _normalize_candidates(
            selection=selection,
            video_id=job.video_id,
            duration=job.metadata.duration,
            start_offset_seconds=job.start_offset_seconds,
            end_offset_seconds=job.end_offset_seconds,
        )
    except ValueError as exc:
        _print_prompt_log(job, llm_response_time, response.usage_metadata)
        return {
            "scene_id": job.scene_id,
            "video_id": job.video_id,
            "error": str(exc),
        }

    # In voice-over mode, discard clips that do not closely match the target duration.
    if job.mode == SceneMatchMode.VOICE_OVER:
        filtered_candidates: list[dict] = []
        for candidate in normalized_candidates:
            matches_duration = _clip_duration_matches_target(
                clip_start=candidate["start_seconds"],
                clip_end=candidate["end_seconds"],
                target_duration=job.target_duration,
            )
            if not matches_duration:
                ratio = _duration_mismatch_ratio(
                    clip_start=candidate["start_seconds"],
                    clip_end=candidate["end_seconds"],
                    target_duration=job.target_duration,
                )
                clip_duration = candidate["end_seconds"] - candidate["start_seconds"]
                mismatch_pct = ratio * 100 if ratio is not None else None
                mismatch_text = f"{mismatch_pct:.1f}%" if mismatch_pct is not None else "unknown"
                print(
                    "[DurationFilter] "
                    f"Discarded candidate for scene={job.scene_id}, video={job.video_id}, "
                    f"range={candidate['start_timestamp']}->{candidate['end_timestamp']}, "
                    f"clip_duration={clip_duration:.3f}s, "
                    f"target_duration={job.target_duration}, "
                    f"mismatch={mismatch_text} "
                    f"(threshold={_VOICE_OVER_DURATION_MISMATCH_RATIO_THRESHOLD * 100:.1f}%)."
                )
                continue
            filtered_candidates.append(candidate)
        normalized_candidates = filtered_candidates

    _print_prompt_log(job, llm_response_time, response.usage_metadata)
    return {
        "scene_id": job.scene_id,
        "video_id": job.video_id,
        "candidates": normalized_candidates,
        "notes": selection.notes,
    }


async def _analyze_voice_over_job(
    client: GeminiClient,
    job: SceneMatchJob,
    uploaded_file: Optional[object],
) -> dict:
    prompt = _build_voice_over_prompt(job)
    return await _analyze_job_with_prompt(client, job, uploaded_file, prompt)


async def _analyze_original_audio_job(
    client: GeminiClient,
    job: SceneMatchJob,
    uploaded_file: Optional[object],
) -> dict:
    prompt = _build_original_audio_prompt(job)
    return await _analyze_job_with_prompt(client, job, uploaded_file, prompt)


async def _analyze_single_job(
    client: GeminiClient,
    job: SceneMatchJob,
    uploaded_file: Optional[object],
) -> dict:
    if job.mode == SceneMatchMode.VOICE_OVER:
        return await _analyze_voice_over_job(client, job, uploaded_file)
    return await _analyze_original_audio_job(client, job, uploaded_file)


async def _execute_analysis_jobs(
    client: GeminiClient,
    jobs: list[SceneMatchJob],
    uploaded_files: dict[str, object],
) -> list[dict]:
    """Execute analysis in parallel."""
    tasks = [
        _analyze_single_job(client, job, uploaded_files.get(job.video_id))
        for job in jobs
    ]
    return await asyncio.gather(*tasks)


def _normalize_candidates(
    selection: SceneMatchResponse,
    video_id: str,
    duration: Optional[float],
    start_offset_seconds: Optional[float] = None,
    end_offset_seconds: Optional[float] = None,
) -> list[dict]:
    normalized_candidates: list[dict] = []
    for candidate in selection.candidates:
        try:
            start_seconds = _parse_timestamp(candidate.start_timestamp)
            end_seconds = _parse_timestamp(candidate.end_timestamp)
        except ValueError as exc:
            raise ValueError(
                f"Detailed timestamp error: {exc}. "
                "Expected format MM:SS.sss (e.g. 02:23.456) or HH:MM:SS.sss (e.g. 00:02:23.456)"
            ) from exc

        if start_seconds >= end_seconds:
            raise ValueError(
                f"Start time {start_seconds} must be less than end time {end_seconds}"
            )
        if duration and start_seconds > duration:
            pass
        if start_offset_seconds is not None and start_seconds < start_offset_seconds - 0.25:
            raise ValueError(
                f"Candidate start {start_seconds:.3f}s is outside analysis window "
                f"start {start_offset_seconds:.3f}s."
            )
        if end_offset_seconds is not None and end_seconds > end_offset_seconds + 0.25:
            raise ValueError(
                f"Candidate end {end_seconds:.3f}s is outside analysis window "
                f"end {end_offset_seconds:.3f}s."
            )

        normalized_candidates.append(
            {
                "video_id": video_id,
                "start_timestamp": candidate.start_timestamp,
                "end_timestamp": candidate.end_timestamp,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "description": candidate.description,
                "rationale": candidate.rationale,
            }
        )
    return normalized_candidates


def _process_analysis_results(
    jobs: list[SceneMatchJob],
    analysis_results: list[dict],
    errors: list[dict],
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Process results into structured output."""
    results_by_scene_id: dict[str, dict] = {}
    notes_by_scene_id: dict[str, list[str]] = {}

    for job in jobs:
        results_by_scene_id.setdefault(
            job.scene_id,
            {"scene_id": job.scene_id, "candidates": []},
        )
        notes_by_scene_id.setdefault(job.scene_id, [])

    for result in analysis_results:
        scene_id = result.get("scene_id")
        video_id = result.get("video_id")

        if result.get("error"):
            errors.append(
                {
                    "scene_id": scene_id,
                    "video_id": video_id,
                    "error": result["error"],
                }
            )
            continue

        if "candidates" in result:
            results_by_scene_id[scene_id]["candidates"].extend(result["candidates"])

        if result.get("notes"):
            notes_by_scene_id[scene_id].append(f"[{video_id}] {result['notes']}")

    return results_by_scene_id, notes_by_scene_id

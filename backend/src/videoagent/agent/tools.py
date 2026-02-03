"""
Tool definitions for the Video Agent.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import time
import traceback
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from pydantic import ValidationError
from google.genai import types

from agents import function_tool, custom_span

from videoagent.config import Config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.models import RenderResult, VoiceOver
from videoagent.story import _StoryboardScene
from videoagent.db import crud, connection, models
from videoagent.voice import VoiceOverGenerator, estimate_speech_duration
from videoagent.editor import VideoEditor

from .schemas import (
    StoryboardUpdatePayload,
    StoryboardSceneUpdatePayload,
    StoryboardSceneUpdate,
    MatchedScenesUpdatePayload,
    VideoBriefUpdatePayload,
    SceneMatchBatchRequest,
    SceneMatchResponse,
)
from .storage import (
    EventStore,
    StoryboardStore,
    BriefStore,
    _parse_timestamp,
)


def _sanitize_output_filename(filename: str) -> str:
    if not filename:
        return "output.mp4"
    path = Path(filename)
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        return filename
    return f"{path.stem}.mp4"


def _voice_over_path_for_id(
    session_id: str,
    base_dir: Path,
    audio_id: str,
) -> Path:
    return base_dir / session_id / "voice_overs" / f"vo_{audio_id}.wav"


def _build_storyboard_voice_over_paths(
    scenes: list[_StoryboardScene],
    session_id: str,
    base_dir: Path,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for scene in scenes:
        voice_over = scene.voice_over
        if not voice_over or not voice_over.audio_id:
            continue
        candidate = _voice_over_path_for_id(session_id, base_dir, voice_over.audio_id)
        if candidate.exists():
            paths[scene.scene_id] = candidate
    return paths


def _render_storyboard_scenes(
    scenes: list[_StoryboardScene],
    config: Config,
    session_id: str,
    base_dir: Path,
    output_filename: str,
    company_id: Optional[str] = None,
) -> RenderResult:
    if not scenes:
        return RenderResult(
            success=False,
            error_message="No storyboard scenes found. Create a storyboard before rendering.",
        )
    missing_sources = [
        scene.scene_id
        for scene in scenes
        if not scene.matched_scene
        or not scene.matched_scene.source_video_id
        or scene.matched_scene.start_time is None
        or scene.matched_scene.end_time is None
    ]
    if missing_sources:
        return RenderResult(
            success=False,
            error_message=(
                "Missing clip data (source/timing) for storyboard scene(s): "
                + ", ".join(missing_sources)
            ),
        )
    library = VideoLibrary(config, company_id=company_id)
    library.scan_library()
    video_paths: dict[str, Path] = {}
    for scene in scenes:
        matched_scene = scene.matched_scene
        if not matched_scene:
            continue
        if matched_scene.source_video_id in video_paths:
            continue
        
        video_id = matched_scene.source_video_id
        
        # Handle generated videos (format: "generated:<session_id>:<filename>")
        if video_id.startswith("generated:"):
            parts = video_id.split(":", 2)
            if len(parts) == 3:
                _, gen_session_id, filename = parts
                generated_path = base_dir / gen_session_id / "generated_videos" / filename
                if generated_path.exists():
                    video_paths[video_id] = generated_path
                    continue
                else:
                    return RenderResult(
                        success=False,
                        error_message=f"Generated video not found: {video_id}",
                    )
            else:
                return RenderResult(
                    success=False,
                    error_message=f"Invalid generated video_id format: {video_id}",
                )
        
        # Handle regular library videos
        metadata = library.get_video(video_id)
        if not metadata:
            return RenderResult(
                success=False,
                error_message=(
                    "Video id(s) not found: " + video_id
                ),
            )
        video_paths[video_id] = metadata.path
    editor = VideoEditor(config)
    try:
        voice_over_paths = _build_storyboard_voice_over_paths(
            scenes,
            session_id,
            base_dir,
        )
        return editor.render_storyboard_scenes(
            scenes,
            output_filename=_sanitize_output_filename(output_filename),
            video_paths=video_paths,
            voice_over_paths=voice_over_paths,
        )
    finally:
        editor.cleanup()



def _resolve_render_target(
    config: Config,
    session_id: str,
    output_path: Optional[str],
) -> Path:
    if output_path:
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = config.output_dir / candidate
        return candidate
    
    def _find_latest_render_path_inner(conf, sid):
        output_dir = conf.output_dir
        if not output_dir.exists():
            return None
        candidates: list[Path] = []
        for ext in (".mp4", ".mov", ".mkv", ".webm"):
            candidates.extend(output_dir.glob(f"*{ext}"))
        if not candidates:
            return None
        def _score(path: Path) -> tuple[int, float]:
            name = path.name
            score = 0
            if sid in name:
                score += 10
            if name.startswith(f"{sid}_auto"):
                score += 5
            if name.startswith("output"):
                score += 1
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            return score, mtime
        return max(candidates, key=_score)

    latest = _find_latest_render_path_inner(config, session_id)
    if latest:
        return latest
    return config.output_dir / f"{session_id}_final.mp4"


def _validate_and_build_jobs(
    requests: list[SceneMatchBatchRequest],
    scenes: list[_StoryboardScene],
    video_library: VideoLibrary,
) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
    """Validate request and build jobs. Returns (jobs, errors, warnings)."""
    scene_map = {scene.scene_id: scene for scene in scenes}
    
    # Pre-fetch all candidate videos
    all_candidate_ids = {
        video_id
        for request in requests
        for video_id in request.candidate_video_ids
    }
    video_map = {
        video_id: video_library.get_video(video_id)
        for video_id in all_candidate_ids
    }

    jobs: list[dict] = []
    errors: list[dict] = []
    warnings_by_scene_id: dict[str, list[str]] = {}

    for request in requests:
        scene = scene_map.get(request.scene_id)
        if not scene:
            errors.append({
                "scene_id": request.scene_id,
                "error": f"Storyboard scene id not found: {request.scene_id}",
            })
            continue
        if not request.candidate_video_ids:
            errors.append({
                "scene_id": request.scene_id,
                "error": "No candidate videos provided.",
            })
            continue
        if len(request.candidate_video_ids) > 5:
            errors.append({
                "scene_id": request.scene_id,
                "error": "Provide up to 5 candidate video ids.",
            })
            continue

        invalid_ids = [
            video_id for video_id in request.candidate_video_ids
            if not video_map.get(video_id)
        ]
        if invalid_ids:
            errors.append({
                "scene_id": request.scene_id,
                "error": "Video id(s) not found: " + ", ".join(invalid_ids),
            })
            continue

        if scene.use_voice_over:
            voice_over = scene.voice_over
            if (
                not (voice_over and voice_over.duration)
                and request.duration_seconds is None
            ):
                errors.append({
                    "scene_id": request.scene_id,
                    "error": (
                        "Voice over duration missing for this scene. "
                        "Generate voice overs first for scenes that need them, "
                        "or provide duration_seconds."
                    ),
                })
                continue

        target_duration = None
        duration_source = None
        voice_over = scene.voice_over
        if voice_over and voice_over.duration:
            target_duration = voice_over.duration
            duration_source = "voice_over"
        elif request.duration_seconds is not None:
            target_duration = request.duration_seconds
            duration_source = "duration_seconds"

        if scene.use_voice_over:
            audio_mode_header = "AUDIO MODE: REPLACE WITH VOICE OVER"
            visual_constraints = (
                "### STRICT VISUAL CONSTRAINT: NO TALKING (B-ROLL ONLY)\n"
                "The original audio will be muted and replaced by a distinct voice-over track. "
                "You should completely ignore the current video voice.\n"
                "You must strictly AVOID clips where a person is speaking to the camera.\n"
                "You must strictly AVOID clips where there is visible subtitles embedded in the video. "
                "These won't match the voice over.\n"
                "**CRITICAL:** If you select a clip where a person is talking, it will look like a "
                "'bad lip reading' or broken dubbing.\n\n"
                "### YOUR TASK:\n"
                "- Take you time to understand the attached video.\n"
                "- Understand the scene context and its transcript. Identify a clip that matches the scene context and its transcript.\n"
                "- Try to identify scenes that closely match the visuals described in note included from the main agent."
                "- If the clip partly matches the transcript, you must communicate this in the description to the main agent. \n"
                "For example, the transcript talks about reducing the processing time and great customer support but the clip only "
                "reprensent reduced processing time, in your description, you must communicate that the clip only represents reduced processing time but does not represent great customer support.\n"
            )
        else:
            audio_mode_header = "AUDIO MODE: KEEP ORIGINAL AUDIO"
            visual_constraints = (
                "### VISUAL REQUIREMENT: TALKING HEADS REQUIRED\n"
                "We are keeping the original audio from the video file.\n"
                "1. You MUST select clips where the person is speaking to the camera.\n"
                "2. The lip movements MUST match the transcript provided below.\n"
                "3. Do not select B-roll or wide shots where the speaker is not visible.\n\n"
                "AUDIO REQUIREMENT:\n"
                "You are acting as a high-precision Video Editor.\n"
                "No Lead-ins: The start_timestamp MUST begin exactly on the first meaningful word. "
                "Do not include filler words (\"Um\", \"So\", \"Well\"), silence, or breath intakes "
                "before the sentence starts.\n"
                "Hard Stop: The end_timestamp MUST cut immediately after the last syllable of the "
                "final word. Do not include trailing silence, laughter, or reaction pauses."
            )
        
        duration_section = ""
        if target_duration:
            duration_section = (
                "\nDURATION TARGET:\n"
                f"- Target duration (seconds): {target_duration}\n"
                f"- Source: {duration_source}\n"
                "- Duration tolerance: +/- 1s\n"
            )

        transcript_text = "(none)"

        warnings_by_scene_id.setdefault(request.scene_id, [])
        if (
            request.duration_seconds is not None
            and not (voice_over and voice_over.duration)
        ):
            warnings_by_scene_id[request.scene_id].append(
                "duration_seconds was provided without a voice over; "
                "used it as the target duration for matching."
            )

        for video_id in request.candidate_video_ids:
            metadata = video_map.get(video_id)
            if metadata:
                jobs.append({
                    "scene_id": request.scene_id,
                    "scene": scene,
                    "video_id": video_id,
                    "metadata": metadata,
                    "notes": request.notes,
                    "audio_mode_header": audio_mode_header,
                    "visual_constraints": visual_constraints,
                    "duration_section": duration_section,
                    "transcript_text": transcript_text,
                })

    return jobs, errors, warnings_by_scene_id


def _upload_job_videos(
    client: GeminiClient,
    jobs: list[dict],
) -> tuple[dict[str, object], dict[str, str]]:
    """Upload videos for the jobs. Returns (uploaded_files_map, failed_uploads_map)."""
    uploaded_files: dict[str, object] = {}
    failed_uploads: dict[str, str] = {}
    
    unique_video_ids = {job["video_id"] for job in jobs}
    # Map video_id to path from jobs (we need metadata)
    video_id_to_metadata = {}
    for job in jobs:
        video_id_to_metadata[job["video_id"]] = job["metadata"]

    for video_id in unique_video_ids:
        metadata = video_id_to_metadata[video_id]
        try:
            # Note: client.get_or_upload_file handles caching logic internally if implemented,
            # or we rely on it being idempotent enough.
            uploaded_files[video_id] = client.get_or_upload_file(metadata.path)
        except Exception as exc:
            failed_uploads[video_id] = str(exc)
            
    return uploaded_files, failed_uploads


def _build_prompt(job: dict) -> str:
    scene = job["scene"]
    scene_text = (
        f"Scene title: {scene.title}\n"
        f"Scene purpose: {scene.purpose}\n"
    )
    notes_text = f"\nNOTES:\n{job['notes']}\n" if job["notes"] else ""
    metadata = job["metadata"]
    return f"""You are an expert video asset manager. This request evaluates a candidate video for a specific scene in a personalized video. The agent cannot see the video, so your descriptions must be vivid.

SCENE CONTEXT:
{scene_text}

SCENE DETAILS:
- Scene id: {job['scene_id']}
- {job['audio_mode_header']}
- Existing transcript (if any): {job['transcript_text']}
{notes_text}{job['duration_section']}

{job['visual_constraints']}

VIDEO TO EVALUATE (SINGLE VIDEO):
- {metadata.id}: {metadata.filename} ({metadata.duration:.1f}s)

WHAT TO RETURN:
- Return 0, 1 or 2 candidate clip from the single video above.
- If this video does not fulfill the requirements, return an empty candidates list and include a notes field explaining why.
- For each candidate include start_timestamp, end_timestamp, description, rationale.
- Use MM:SS.sss format for start_timestamp and end_timestamp (milliseconds required).
- **RATIONALE REQUIREMENT:** In your rationale, explicitly state how the clip fits the visual constraints (e.g., "Confirmed: Subject is listening, lips are not moving" or "Confirmed: Subject is speaking to camera").
- Use only the video_id value listed above; copy it exactly.

EXAMPLE OUTPUT:
{{"candidates":[{{"video_id":"abcd1234","start_timestamp":"02:15.000","end_timestamp":"02:24.250","description":"Executive smiling and nodding while looking at a colleague.","rationale":"Perfect B-roll match; subject is engaged but not speaking, fitting the voice-over requirement."}}]}}
"""

def _print_prompt_log(job: dict, llm_response_time: Optional[float], usage: Optional[object] = None) -> None:
    vid = job["video_id"]
    sid = job["scene_id"]
    dur = f"{llm_response_time:.2f}s" if llm_response_time is not None else "N/A"
    tokens = ""
    if usage:
        prompt_tok = getattr(usage, "prompt_token_count", "?")
        cand_tok = getattr(usage, "candidates_token_count", "?")
        tokens = f" (in: {prompt_tok}, out: {cand_tok})"
    print(f"[Analysis] {sid}:{vid} finished in {dur}{tokens}")


async def _analyze_single_job(
    client: GeminiClient,
    job: dict,
    uploaded_file: Optional[object],
) -> dict:
    """Run analysis for a single job."""
    video_id = job["video_id"]
    scene_id = job["scene_id"]
    video_metadata = job["metadata"]

    span_data = {
        "scene_id": scene_id,
        "video_id": video_id,
        "video_duration_seconds": video_metadata.duration,
        "video_filename": video_metadata.filename,
    }

    with custom_span("analyze_video_content", data=span_data):
        if not uploaded_file:
            _print_prompt_log(job, None)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": "Video file was not uploaded.",
            }

        prompt = _build_prompt(job)
        parts = []
        file_uri = getattr(uploaded_file, "uri", None)
        if file_uri:
            parts.append(
                types.Part(
                    file_data=types.FileData(file_uri=file_uri),
                    video_metadata=types.VideoMetadata(fps=2),
                )
            )
            parts.append(types.Part(text=prompt))
            contents = types.Content(parts=parts)
        else:
            contents = [uploaded_file, prompt]

        llm_start = time.perf_counter()
        try:
            response = await client.client.aio.models.generate_content(
                model=client.config.gemini_model,
                contents=contents,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": SceneMatchResponse.model_json_schema(),
                    "thinking_config": types.ThinkingConfig(thinking_budget=4096)
                },
            )
        except Exception as exc:
            _print_prompt_log(job, time.perf_counter() - llm_start, None)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": f"LLM generation failed: {exc}",
            }

        llm_response_time = time.perf_counter() - llm_start
        if not response.text:
            _print_prompt_log(job, llm_response_time, response.usage_metadata)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": "Model returned an empty response.",
            }

        try:
            selection = SceneMatchResponse.model_validate_json(response.text)
        except ValidationError as exc:
            _print_prompt_log(job, llm_response_time, response.usage_metadata)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": f"Model response validation error: {exc}",
            }

        invalid_selected = [
            c.video_id for c in selection.candidates if c.video_id != video_id
        ]
        if invalid_selected:
            _print_prompt_log(job, llm_response_time, response.usage_metadata)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": f"Model selected bad video_id(s): {', '.join(invalid_selected)}",
            }

        try:
            normalized_candidates = _normalize_candidates(
                selection, video_id, video_metadata.duration
            )
        except ValueError as exc:
            _print_prompt_log(job, llm_response_time, response.usage_metadata)
            return {
                "scene_id": scene_id,
                "video_id": video_id,
                "error": str(exc),
            }

        _print_prompt_log(job, llm_response_time, response.usage_metadata)
        return {
            "scene_id": scene_id,
            "video_id": video_id,
            "candidates": normalized_candidates,
            "notes": selection.notes,
        }


async def _execute_analysis_jobs(
    client: GeminiClient,
    jobs: list[dict],
    uploaded_files: dict[str, object],
) -> list[dict]:
    """Execute analysis in parallel with trace logging."""
    tasks = [
        _analyze_single_job(client, job, uploaded_files.get(job["video_id"]))
        for job in jobs
    ]
    return await asyncio.gather(*tasks)


def _normalize_candidates(
    selection: SceneMatchResponse,
    video_id: str,
    duration: Optional[float],
) -> list[dict]:
    normalized_candidates: list[dict] = []
    for candidate in selection.candidates:
        try:
            start_seconds = _parse_timestamp(candidate.start_timestamp)
            end_seconds = _parse_timestamp(candidate.end_timestamp)
        except ValueError as exc:
            raise ValueError(
                f"Detailed timestamp error: {exc}. "
                "Expected format MM:SS.sss (e.g. 02:23.456)"
            ) from exc
        
        if start_seconds >= end_seconds:
             raise ValueError(
                f"Start time {start_seconds} must be less than end time {end_seconds}"
            )
        if duration and start_seconds > duration:
            pass

        normalized_candidates.append({
            "video_id": video_id,
            "start_timestamp": candidate.start_timestamp,
            "end_timestamp": candidate.end_timestamp,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "description": candidate.description,
        })
    return normalized_candidates


def _process_analysis_results(
    jobs: list[dict],
    analysis_results: list[dict],
    errors: list[dict],
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Process results into structured output."""
    results_by_scene_id: dict[str, dict] = {}
    notes_by_scene_id: dict[str, list[str]] = {}
    
    # Initialize containers
    for job in jobs:
        results_by_scene_id.setdefault(
            job["scene_id"],
            {"scene_id": job["scene_id"], "candidates": []},
        )
        notes_by_scene_id.setdefault(job["scene_id"], [])

    for result in analysis_results:
        scene_id = result.get("scene_id")
        video_id = result.get("video_id")
        
        if result.get("error"):
            errors.append({
                "scene_id": scene_id,
                "video_id": video_id,
                "error": result["error"]
            })
            continue
            
        if "candidates" in result:
            results_by_scene_id[scene_id]["candidates"].extend(result["candidates"])
        
        if result.get("notes"):
             notes_by_scene_id[scene_id].append(f"[{video_id}] {result['notes']}")
            
    return results_by_scene_id, notes_by_scene_id


def _build_tools(
    config: Config,
    storyboard_store: StoryboardStore,
    brief_store: BriefStore,
    event_store: EventStore,
    session_id: str,
    company_id: str,
    user_id: str,
    auto_render_callback: Optional[Callable[[], None]] = None,
):
    def tool_error(name: str):
        def error_fn(ctx, error: Exception):
            return f"{name} failed: {error}, {ctx}\nTraceback: {traceback.format_exc()}"
        return error_fn

    def log_tool(name: str):
        def decorator(fn):
            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def wrapped(*args, **kwargs):
                    event_store.append(session_id, {"type": "tool_start", "name": name}, user_id=user_id)
                    try:
                        result = await fn(*args, **kwargs)
                        event_store.append(session_id, {"type": "tool_end", "name": name, "status": "ok"}, user_id=user_id)
                        return result
                    except Exception as exc:
                        event_store.append(
                            session_id,
                            {"type": "tool_end", "name": name, "status": "error", "error": str(exc)},
                            user_id=user_id,
                        )
                        raise
                return wrapped
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                event_store.append(session_id, {"type": "tool_start", "name": name}, user_id=user_id)
                try:
                    result = fn(*args, **kwargs)
                    event_store.append(session_id, {"type": "tool_end", "name": name, "status": "ok"}, user_id=user_id)
                    return result
                except Exception as exc:
                    event_store.append(
                        session_id,
                        {"type": "tool_end", "name": name, "status": "error", "error": str(exc)},
                        user_id=user_id,
                    )
                    raise
            return wrapped
        return decorator


    @function_tool(
        failure_error_function=tool_error("update_storyboard"),
        strict_mode=True,
    )
    @log_tool("update_storyboard")
    def update_storyboard(
        payload: StoryboardUpdatePayload,
    ) -> str:
        """Replace the current storyboard scenes with the provided full list."""
        old_scenes = storyboard_store.load(session_id, user_id=user_id) or []
        old_scene_map = {scene.scene_id: scene for scene in old_scenes}
        
        new_scenes: list[_StoryboardScene] = []
        for update in payload.scenes:
            # Preserve existing specialized fields if scene exists
            voice_over = None
            matched_scene = None
            if update.scene_id in old_scene_map:
                existing = old_scene_map[update.scene_id]
                voice_over = existing.voice_over
                matched_scene = existing.matched_scene
            
            new_scene = _StoryboardScene(
                scene_id=update.scene_id,
                title=update.title,
                purpose=update.purpose,
                script=update.script,
                use_voice_over=update.use_voice_over,
                order=update.order,
                voice_over=voice_over,
                matched_scene=matched_scene,
            )
            new_scenes.append(new_scene)
            
        storyboard_store.save(session_id, new_scenes, user_id=user_id)
        event_store.append(session_id, {"type": "storyboard_update"}, user_id=user_id)
        return "UI updated successfully"

    @function_tool(
        failure_error_function=tool_error("update_storyboard_scene"),
        strict_mode=True,
    )
    @log_tool("update_storyboard_scene")
    def update_storyboard_scene(
        payload: StoryboardSceneUpdatePayload,
    ) -> str:
        """Replace a single storyboard scene by scene_id."""
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before updating a scene."
        
        updated_scenes: list[_StoryboardScene] = []
        target_found = False
        
        for scene in scenes:
            if scene.scene_id == payload.scene.scene_id:
                # Update but preserve specialized fields
                updated_scene = _StoryboardScene(
                    scene_id=payload.scene.scene_id,
                    title=payload.scene.title,
                    purpose=payload.scene.purpose,
                    script=payload.scene.script,
                    use_voice_over=payload.scene.use_voice_over,
                    order=payload.scene.order,
                    voice_over=scene.voice_over,      # PRESERVE
                    matched_scene=scene.matched_scene # PRESERVE
                )
                updated_scenes.append(updated_scene)
                target_found = True
            else:
                updated_scenes.append(scene)
                
        if not target_found:
            return f"Storyboard scene id not found: {payload.scene.scene_id}"
            
        storyboard_store.save(session_id, updated_scenes, user_id=user_id)
        event_store.append(session_id, {"type": "storyboard_update"}, user_id=user_id)
        return "Storyboard scene updated successfully"

    @function_tool(
        failure_error_function=tool_error("update_matched_scenes"),
        strict_mode=True,
    )
    @log_tool("update_matched_scenes")
    def update_matched_scenes(
        payload: MatchedScenesUpdatePayload,
    ) -> str:
        """Update the matched_scene field for specific storyboard scenes."""
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before updating matched scenes."
        
        scene_map = {scene.scene_id: scene for scene in scenes}
        updated_count = 0
        missing_ids = []

        for item in payload.scenes:
            if item.scene_id in scene_map:
                scene_map[item.scene_id].matched_scene = item.matched_scene
                updated_count += 1
            else:
                missing_ids.append(item.scene_id)
        
        if updated_count > 0:
            storyboard_store.save(session_id, scenes, user_id=user_id)
            event_store.append(session_id, {"type": "storyboard_update"}, user_id=user_id)
        
        msg = f"Updated matched details for {updated_count} scene(s)."
        if missing_ids:
            msg += f" Warning: Scene IDs not found: {', '.join(missing_ids)}"
        return msg

    @function_tool(failure_error_function=tool_error("update_video_brief"), strict_mode=True)
    @log_tool("update_video_brief")
    def update_video_brief(payload: VideoBriefUpdatePayload) -> str:
        """Update/Replace the video brief details (objective, persona, key_messages)."""
        brief_store.save(session_id, payload.brief, user_id=user_id)
        event_store.append(session_id, {"type": "video_brief_update"}, user_id=user_id)
        return "Video brief updated successfully. UI will reflect changes."

    @function_tool(failure_error_function=tool_error("render_storyboard"), strict_mode=False)
    @log_tool("render_storyboard")
    def render_storyboard(output_filename: Optional[str] = None) -> str:
        """Render storyboard scenes to a video file."""
        event_store.append(session_id, {"type": "video_render_start"}, user_id=user_id)
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        result = _render_storyboard_scenes(
            scenes,
            config,
            session_id,
            storyboard_store.base_dir,
            output_filename or "output.mp4",
        )
        if result.success:
            event_store.append(
                session_id,
                {"type": "video_render_complete", "status": "ok", "output": str(result.output_path)}
            )
            return f"Video rendered successfully to {result.output_path}"
        else:
            return f"Render failed: {result.error_message}"

    @function_tool(failure_error_function=tool_error("generate_voice_overs"), strict_mode=False)
    @log_tool("generate_voice_overs")
    async def generate_voice_overs(segment_ids: list[str]) -> str:
        """Generate voice overs for selected storyboard scenes by id and persist them."""
        # Provide early feedback to UI
        event_store.append(session_id, {"type": "video_render_start"}, user_id=user_id)
        
        step_start = time.perf_counter()
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before generating voice overs."
        scene_map = {scene.scene_id: scene for scene in scenes}
        missing_ids = [scene_id for scene_id in segment_ids if scene_id not in scene_map]
        if missing_ids:
            return "Storyboard scene id(s) not found: " + ", ".join(missing_ids)
        non_voice_ids = [
            scene_id for scene_id in segment_ids
            if scene_map[scene_id].use_voice_over is False
        ]
        if non_voice_ids:
            return (
                "Voice over disabled for storyboard scene id(s): "
                + ", ".join(non_voice_ids)
            )
        missing_script_ids = [
            scene_id for scene_id in segment_ids
            if not (scene_map[scene_id].script and scene_map[scene_id].script.strip())
        ]
        if missing_script_ids:
            return "Missing script for storyboard scene id(s): " + ", ".join(missing_script_ids)
        
        # Determine voice to use
        voice = config.tts_voice
        
        # Look up user preference from DB
        if user_id:
            try:
                with connection.get_db_context() as db:
                    user = crud.get_user(db, user_id)
                    if user and user.settings and "tts_voice" in user.settings:
                        voice = user.settings["tts_voice"]
            except Exception as e:
                print(f"[generate_voice_overs] Failed to look up user voice preference: {e}")
        else:
             print("[generate_voice_overs] No user_id provided in context, using default voice.")

        generator = VoiceOverGenerator(config)
        try:
            # Use the store's path resolution to get the correct session directory (including user_id)
            session_dir = storyboard_store._storyboard_path(session_id, user_id=user_id).parent
            voice_dir = session_dir / "voice_overs"
            voice_dir.mkdir(parents=True, exist_ok=True)

            semaphore = asyncio.Semaphore(8)
            async def _run(scene_id: str) -> VoiceOver:
                job_start = time.perf_counter()
                scene = scene_map[scene_id]
                audio_id = uuid4().hex[:8]
                output_path = voice_dir / f"vo_{audio_id}.wav"
                async with semaphore:
                    voice_over = await generator.generate_voice_over_async(
                        scene.script,
                        voice=voice,
                        output_path=output_path,
                    )
                print(
                    "[generate_voice_overs] "
                    f"{scene_id} generated in {time.perf_counter() - job_start:.2f}s"
                )
                if voice_over.audio_id != audio_id:
                    voice_over.audio_id = audio_id
                return voice_over

            results = await asyncio.gather(*[_run(scene_id) for scene_id in segment_ids])
            for scene_id, voice_over in zip(segment_ids, results):
                scene = scene_map[scene_id]
                scene.voice_over = voice_over
            storyboard_store.save(session_id, scenes, user_id=user_id)
            print(
                "[generate_voice_overs] total time: "
                f"{time.perf_counter() - step_start:.2f}s"
            )
            return f"Voice overs generated for {len(segment_ids)} storyboard scene(s)."
        finally:
            generator.cleanup()

    @function_tool(failure_error_function=tool_error("match_scene_to_video"), strict_mode=False)
    @log_tool("match_scene_to_video")
    async def match_scene_to_video(payload: SceneMatchBatchRequest) -> str:
        """Find candidate video clips for one or more storyboard scenes using uploaded video context.

        Each request includes a scene_id and candidate_video_ids (max 5). The tool evaluates each
        candidate video in its own prompt and merges the outputs by scene_id.
        Optional duration_seconds can guide clip length only when no voice over exists for the scene.
        (Refer to system prompt for full details on matching logic).
        """
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before matching scenes."
        if not payload.requests:
            return "No scene match requests provided."

        library = VideoLibrary(config, company_id=company_id)
        library.scan_library()

        # 1. Validation and Job Building
        jobs, errors, warnings_by_scene_id = _validate_and_build_jobs(
            payload.requests, scenes, library
        )
        if not jobs:
             response_payload = {"results": []}
             if errors:
                 response_payload["errors"] = errors
             return json.dumps(response_payload)

        # 2. Upload Videos
        client = GeminiClient(config)
        uploaded_files, failed_uploads = _upload_job_videos(client, jobs)
        
        # Filter jobs if upload failed
        valid_jobs = []
        for job in jobs:
            if job["video_id"] in failed_uploads:
                errors.append({
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": f"Failed to upload video: {failed_uploads[job['video_id']]}",
                })
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
            jobs, analysis_results, errors
        )
        
        response_payload = {
            "results": list(results_by_scene_id.values()),
        }
        if notes_by_scene_id:
            response_payload["notes"] = notes_by_scene_id
        if warnings_by_scene_id:
            # Flatten empty warnings
            final_warnings = {k: v for k, v in warnings_by_scene_id.items() if v}
            if final_warnings:
                response_payload["warnings"] = final_warnings
        if errors:
            response_payload["errors"] = errors
        
        event_store.append(session_id, {"type": "video_render_complete"}, user_id=user_id)

        return (
            f"{json.dumps(response_payload)}\n"
            "Message: Review the candidates and confirm which one meets the requirements. "
            "Then update the story board with your chosen clip using 'update_matched_scenes'. "
            "If no clips match the requirements, update the notes and call this tool again."
        )

    @function_tool(failure_error_function=tool_error("estimate_voice_duration"), strict_mode=False)
    @log_tool("estimate_voice_duration")
    def estimate_voice_duration(
        text: str,
        words_per_minute: float = 150,
    ) -> float:
        """Estimate speech duration for a script."""
        return estimate_speech_duration(text, words_per_minute)

    @function_tool(failure_error_function=tool_error("review_final_render"), strict_mode=False)
    @log_tool("review_final_render")
    async def review_final_render(output_path: Optional[str] = None) -> str:
        """Render (if needed) and review the final video, returning QA notes."""
        step_start = time.perf_counter()
        print("[review] start review_final_render")
        t0 = time.perf_counter()
        scenes = storyboard_store.load(session_id) or []
        print(f"[review] load storyboard in {time.perf_counter() - t0:.2f}s")
        if not scenes:
            print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
            return "No storyboard scenes found. Create a storyboard before rendering."
        scenes_payload = [
            scene.model_dump(
                mode="json",
                exclude_none=True,
            )
            for scene in scenes
        ]
        scenes_context = json.dumps(scenes_payload, indent=2)

        t0 = time.perf_counter()
        storyboard_path = storyboard_store._storyboard_path(session_id, user_id=user_id)
        storyboard_mtime = None
        try:
            if storyboard_path.exists():
                storyboard_mtime = storyboard_path.stat().st_mtime
        except OSError:
            storyboard_mtime = None
        print(f"[review] check storyboard mtime in {time.perf_counter() - t0:.2f}s")

        t0 = time.perf_counter()
        render_path = _resolve_render_target(config, session_id, output_path)
        needs_render = True
        if render_path and render_path.exists() and storyboard_mtime is not None:
            try:
                needs_render = storyboard_mtime > render_path.stat().st_mtime
            except OSError:
                needs_render = True
        elif render_path and render_path.exists():
            needs_render = False
        print(f"[review] resolve render target in {time.perf_counter() - t0:.2f}s")

        if needs_render:
            t0 = time.perf_counter()
            result = _render_storyboard_scenes(
                scenes,
                config,
                session_id,
                storyboard_store.base_dir,
                render_path.name,
            )
            print(f"[review] render storyboard in {time.perf_counter() - t0:.2f}s")
            if not result.success:
                print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
                return f"Render failed: {result.error_message or 'unknown error'}"
            render_path = result.output_path or render_path

        t0 = time.perf_counter()
        client = GeminiClient(config)
        uploaded = client.get_or_upload_file(render_path)
        print(f"[review] upload render in {time.perf_counter() - t0:.2f}s")
        review_prompt = f"""
You are an expert Video Editor and Quality Assurance specialist.
Your task is to watch the attached video and identify technical, visual, and narrative issues.
Use the storyboard JSON to understand the intended sequence, narration, and clip sources.

STORYBOARD SCENES (read-only JSON):
{scenes_context}

You are looking for ANY flaws that lower the quality of the video, including but not limited to:
- Video is static for a long time, which reduces the video attractiveness.
- Audio/Visual Mismatch: A narrator is speaking (Voice Over), but the visual shows a person talking to camera with unsynchronized lips (Bad Lip Reading).
- Repetitive Footage: The same source video clip is used more than once in the same video.
- Unwanted Text: Burnt-in subtitles, watermarks, or text overlays from the source footage that clash with the video.
- Visual Flow: Jump cuts, black frames between clips, or abrupt transitions.
- Narrative Match: The visual B-roll contradicts or doesn't fit what is being said in the Voice Over.
- Language match: One of the scenes are not in the same language.

Take your time to match the scenes to the video frames and the voice, and make sure everything is aligned perfectly.

OUTPUT FORMAT
Return a bulleted list of issues in natural language.
Start every line with the timestamp where the issue occurs.
If the video is perfect, just say "No issues found."

Example:
- [00:12] The narrator is talking about "silence" but the video shows a loud construction site, which feels conflicting.
- [00:34] There are burnt-in Chinese subtitles at the bottom of the screen that shouldn't be there.
- [00:45] The clip of the man typing on the laptop is a duplicate; it was already used previously at 00:05.
- [01:05] The clip cuts to black for a split second before the next scene starts.
"""
        from google.genai import types

        file_uri = getattr(uploaded, "uri", None)
        if file_uri:
            contents = types.Content(
                parts=[
                    types.Part(
                        file_data=types.FileData(file_uri=file_uri),
                        video_metadata=types.VideoMetadata(fps=10),
                    ),
                    types.Part(text=review_prompt),
                ]
            )
        else:
            contents = [uploaded, review_prompt]
        response = await client.client.aio.models.generate_content(
            model=config.gemini_model,
            contents=contents,
            config={
                "max_output_tokens": 3_000,
            },
        )
        review_text = response.text.strip() if response.text else ""
        if not review_text:
            review_text = "No issues found."
        print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
        return review_text

    @function_tool(failure_error_function=tool_error("generate_scene"), strict_mode=False)
    @log_tool("generate_scene")
    async def generate_scene(
        prompt: str,
        scene_id: str,
        duration_seconds: int = 8,
        negative_prompt: Optional[str] = None,
    ) -> str:
        """Generate a video scene using AI (Veo). Use as fallback when match_scene_to_video fails.
        
        Args:
            prompt: Detailed visual description of the scene to generate.
            scene_id: The storyboard scene_id (required).
            duration_seconds: Must be 4, 6, or 8. Pick closest to voice over duration.
            negative_prompt: What to avoid (e.g., "blurry, text, watermarks").
        
        Returns:
            Success message. The scene is automatically updated with the generated video.
        """
        from google import genai
        from videoagent.library import extract_video_metadata
        
        # Use store path resolution for correct directory
        session_dir = storyboard_store._storyboard_path(session_id, user_id=user_id).parent
        generated_dir = session_dir / "generated_videos"
        generated_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate that the scene exists in the storyboard
        scenes = storyboard_store.load(session_id, user_id=user_id) or []
        target_scene = None
        for scene in scenes:
            if scene.scene_id == scene_id:
                target_scene = scene
                break
        
        if not target_scene:
            return json.dumps({
                "success": False,
                "error": f"Scene '{scene_id}' not found in the storyboard. Please check the scene_id.",
            })
        
        # Validate that voice over has been generated for this scene
        if not target_scene.voice_over:
            return json.dumps({
                "success": False,
                "error": (
                    f"No voice over found for scene '{scene_id}'. "
                    "Voice over MUST be generated first using generate_voice_overs before using generate_scene."
                ),
            })
        
        voice_over_duration = target_scene.voice_over.duration
        if voice_over_duration is None:
            return json.dumps({
                "success": False,
                "error": (
                    f"Voice over duration is not set for scene '{scene_id}'. "
                    "Please regenerate the voice over using generate_voice_overs."
                ),
            })
        
        # Validate that voice over is less than 9 seconds
        MAX_VOICE_OVER_DURATION = 9.0
        if voice_over_duration > MAX_VOICE_OVER_DURATION:
            return json.dumps({
                "success": False,
                "error": (
                    f"Voice over duration ({voice_over_duration:.1f}s) is > {MAX_VOICE_OVER_DURATION}s for scene '{scene_id}'. "
                    "AI scene generation only works for voice overs under 9 seconds. "
                    "Either shorten the voice over script and regenerate, or split into multiple scenes."
                ),
            })
        
        # Validate duration parameter
        valid_durations = [4, 6, 8]
        if duration_seconds not in valid_durations:
            return json.dumps({
                "success": False,
                "error": f"Invalid duration_seconds: {duration_seconds}. Must be one of: {valid_durations}",
            })
        
        # Suggest the optimal duration based on voice over length
        suggested_duration = 4 if voice_over_duration <= 5 else (6 if voice_over_duration <= 7 else 8)
        if duration_seconds != suggested_duration:
            print(
                f"[generate_scene] Note: Voice over is {voice_over_duration:.1f}s. "
                f"Suggested duration_seconds={suggested_duration}, but using {duration_seconds}."
            )
        
        event_store.append(session_id, {
            "type": "video_generation_start",
            "prompt": prompt,
            "scene_id": scene_id,
            "negative_prompt": negative_prompt,
            "duration_seconds": duration_seconds,
            "voice_over_duration": voice_over_duration,
        }, user_id=user_id)
        
        # Store generated videos in session-specific directory (NOT main library)
        # This prevents them from appearing in LLM context as source content
        # generated_dir is already defined above including user_id scope
        
        # Generate unique filename
        unique_id = uuid4().hex[:8]
        output_filename = f"generated_{scene_id}_{unique_id}.mp4"
        
        output_path = generated_dir / output_filename
        
        # Use a special video_id format for generated videos: "generated:<session_id>:<filename>"
        # This allows the API to find and serve these videos separately from the main library
        video_id = f"generated:{session_id}:{output_filename}"
        
        try:
            # Initialize the Genai client
            client = genai.Client()
            
            print(f"[generate_scene] Starting video generation ({duration_seconds}s) for prompt: {prompt[:100]}...")
            step_start = time.perf_counter()
            
            # Build generation config
            gen_config = {"duration_seconds": duration_seconds}
            if negative_prompt:
                gen_config["negative_prompt"] = negative_prompt
            
            # Start video generation with specified duration and negative prompt
            operation = client.models.generate_videos(
                model="veo-3.1-generate-preview",
                prompt=prompt,
                config=gen_config,
            )
            
            # Poll the operation status until the video is ready
            poll_count = 0
            while not operation.done:
                poll_count += 1
                print(f"[generate_scene] Waiting for video generation... (poll #{poll_count})")
                await asyncio.sleep(10)
                operation = client.operations.get(operation)
            
            generation_time = time.perf_counter() - step_start
            print(f"[generate_scene] Video generation completed in {generation_time:.2f}s")
            
            # Download and save the generated video
            if not operation.response or not operation.response.generated_videos:
                event_store.append(
                    session_id,
                    {"type": "video_generation_complete", "status": "error", "error": "No video generated"},
                    user_id=user_id,
                )
                return json.dumps({
                    "success": False,
                    "error": "Video generation failed: No video was generated by the model.",
                })
            
            generated_video = operation.response.generated_videos[0]
            client.files.download(file=generated_video.video)
            generated_video.video.save(str(output_path))
            
            print(f"[generate_scene] Generated video saved to {output_path}")
            
            # Extract video metadata
            video_metadata = extract_video_metadata(output_path)
            duration = video_metadata.get("duration", 0.0)
            resolution = video_metadata.get("resolution", (1920, 1080))
            fps = video_metadata.get("fps", 24.0)
            
            event_store.append(
                session_id,
                {
                    "type": "video_generation_complete",
                    "status": "ok",
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "output": str(output_path),
                    "generation_time_seconds": generation_time,
                },
                user_id=user_id,
            )
            
            # Directly update the storyboard scene with the generated video
            from videoagent.story import _MatchedScene
            
            matched_scene = _MatchedScene(
                source_video_id=video_id,
                start_time=0.0,
                end_time=duration,
                description=f"AI-generated: {prompt}",
                keep_original_audio=False,
            )
            
            # Update the target scene
            target_scene.matched_scene = matched_scene
            
            # Save the updated storyboard
            storyboard_store.save(session_id, scenes, user_id=user_id)
            
            # Emit storyboard update event for frontend
            event_store.append(
                session_id,
                {
                    "type": "storyboard_update",
                    "scenes": [s.model_dump(mode="json") for s in scenes],
                },
                user_id=user_id,
            )
            
            return (
                f"Video generated successfully for scene '{scene_id}'. "
                f"Duration: {duration:.1f}s. The scene has been automatically updated with the generated video."
            )
            
        except Exception as exc:
            error_msg = f"Video generation failed: {exc}"
            print(f"[generate_scene] {error_msg}")
            event_store.append(
                session_id,
                {"type": "video_generation_complete", "status": "error", "error": str(exc)},
                user_id=user_id,
            )
            return json.dumps({
                "success": False,
                "error": error_msg,
            })

    return [
        update_storyboard,
        update_storyboard_scene,
        update_matched_scenes,
        update_video_brief,
        match_scene_to_video,
        generate_voice_overs,
        estimate_voice_duration,
        generate_scene,
    ]

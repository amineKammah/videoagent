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

from agents import function_tool

from videoagent.config import Config
from videoagent.gcp import build_vertex_client_kwargs
from videoagent.library import VideoLibrary
from videoagent.models import RenderResult, VoiceOver
from videoagent.storage import get_storage_client
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
)
from .scene_matcher import SceneMatcher
from .storage import (
    EventStore,
    StoryboardStore,
    BriefStore,
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


def _company_scope(company_id: Optional[str]) -> str:
    return company_id or "global"


def _voice_over_blob_key(company_id: Optional[str], session_id: str, filename: str) -> str:
    return f"companies/{_company_scope(company_id)}/generated/voiceovers/{session_id}/{filename}"


def _generated_scene_blob_key(company_id: Optional[str], session_id: str, filename: str) -> str:
    return f"companies/{_company_scope(company_id)}/generated/scenes/{session_id}/{filename}"


def _build_storyboard_voice_over_paths(
    scenes: list[_StoryboardScene],
    session_id: str,
    base_dir: Path,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    storage_client = None
    for scene in scenes:
        voice_over = scene.voice_over
        if not voice_over or not voice_over.audio_id:
            continue
        candidate = _voice_over_path_for_id(session_id, base_dir, voice_over.audio_id)
        if candidate.exists():
            paths[scene.scene_id] = candidate
            continue
        if voice_over.audio_path and voice_over.audio_path.startswith("gs://"):
            if storage_client is None:
                try:
                    storage_client = get_storage_client()
                except Exception:
                    storage_client = None
            if storage_client:
                try:
                    storage_client.download_to_filename(voice_over.audio_path, candidate)
                    paths[scene.scene_id] = candidate
                except Exception:
                    continue
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
    storage_client = get_storage_client(config)
    render_sources_dir = config.output_dir / "render_sources" / session_id
    render_sources_dir.mkdir(parents=True, exist_ok=True)
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
                if company_id:
                    gcs_key = _generated_scene_blob_key(company_id, gen_session_id, filename)
                    if storage_client.exists(gcs_key):
                        cached_generated = render_sources_dir / f"{gen_session_id}_{filename}"
                        try:
                            storage_client.download_to_filename(gcs_key, cached_generated)
                            video_paths[video_id] = cached_generated
                            continue
                        except Exception as exc:
                            return RenderResult(
                                success=False,
                                error_message=f"Failed to download generated video {video_id} from GCS: {exc}",
                            )
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
        source_ref = metadata.path
        if isinstance(source_ref, str) and source_ref.startswith("gs://"):
            local_source = render_sources_dir / f"{video_id}_{metadata.filename}"
            try:
                storage_client.download_to_filename(source_ref, local_source)
            except Exception as exc:
                return RenderResult(
                    success=False,
                    error_message=f"Failed to download source video {video_id} from GCS: {exc}",
                )
            video_paths[video_id] = local_source
        else:
            video_paths[video_id] = Path(str(source_ref))
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

def _check_scene_warnings(scenes: list[_StoryboardScene]) -> str:
    """Check for time overlaps and duration mismatches."""
    from collections import defaultdict
    video_ranges = defaultdict(list)
    warnings = []
    
    # 1. Overlap Check & 2. Duration Check
    for scene in scenes:
        # Duration Check
        if scene.use_voice_over and scene.voice_over and scene.voice_over.duration:
            if scene.matched_scene and scene.matched_scene.start_time is not None and scene.matched_scene.end_time is not None:
                scene_duration = float(scene.matched_scene.end_time) - float(scene.matched_scene.start_time)
                vo_duration = scene.voice_over.duration
                
                # Check for > 10% difference
                if vo_duration > 0:
                    diff_ratio = abs(scene_duration - vo_duration) / vo_duration
                    if diff_ratio > 0.10:
                        warnings.append(
                            f"Warning: Scene '{scene.title}' ({scene.scene_id}) duration ({scene_duration:.1f}s) "
                            f"mismatches voice over duration ({vo_duration:.1f}s) by {diff_ratio*100:.0f}%."
                        )

        # Collect ranges for overlap check
        if not scene.matched_scene or not scene.matched_scene.source_video_id:
            continue
        ms = scene.matched_scene
        if ms.start_time is None or ms.end_time is None:
            continue
        
        video_ranges[ms.source_video_id].append({
            "scene_id": scene.scene_id,
            "start": float(ms.start_time),
            "end": float(ms.end_time),
            "title": scene.title
        })
        
    processed = set()
    
    for vid, items in video_ranges.items():
        # sort by start time
        items.sort(key=lambda x: x["start"])
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                s1 = items[i]
                s2 = items[j]
                
                # Check overlap: max(start1, start2) < min(end1, end2)
                overlap_start = max(s1["start"], s2["start"])
                overlap_end = min(s1["end"], s2["end"])
                
                if overlap_start < overlap_end:
                    overlap_duration = overlap_end - overlap_start
                    # Define "significant" as > 0.5s to avoid float precision noise at boundaries
                    if overlap_duration > 0.5:
                        pair_key = tuple(sorted((s1["scene_id"], s2["scene_id"])))
                        if pair_key not in processed:
                            warnings.append(
                                f"Warning: Scenes '{s1['title']}' ({s1['scene_id']}) and "
                                f"'{s2['title']}' ({s2['scene_id']}) overlap by {overlap_duration:.1f}s "
                                f"on video {vid}."
                            )
                            processed.add(pair_key)
                            
    if warnings:
        return "\n" + "\n".join(warnings)
    return ""


def _build_tools(
    config: Config,
    storyboard_store: StoryboardStore,
    brief_store: BriefStore,
    event_store: EventStore,
    session_id: str,
    company_id: Optional[str],
    user_id: Optional[str],
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

    scene_matcher = SceneMatcher(
        config=config,
        storyboard_store=storyboard_store,
        event_store=event_store,
        session_id=session_id,
        company_id=company_id,
        user_id=user_id,
    )


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
        
        warnings = _check_scene_warnings(new_scenes)
        return "UI updated successfully" + warnings

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
        
        warnings = _check_scene_warnings(updated_scenes)
        return "Storyboard scene updated successfully" + warnings

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
            
        warnings = _check_scene_warnings(scenes)
        return msg + warnings

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
            company_id=company_id,
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
        storage_client = get_storage_client(config)
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
                gcs_key = _voice_over_blob_key(company_id, session_id, output_path.name)
                await asyncio.to_thread(
                    storage_client.upload_from_filename,
                    gcs_key,
                    output_path,
                    "audio/wav",
                )
                voice_over.audio_path = storage_client.to_gs_uri(gcs_key)
                voice_over.audio_url = None
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
        """Find candidate clips for one or more storyboard scenes."""
        return await scene_matcher.match_scene_to_video(payload)

    @function_tool(failure_error_function=tool_error("estimate_voice_duration"), strict_mode=False)
    @log_tool("estimate_voice_duration")
    def estimate_voice_duration(
        text: str,
        words_per_minute: float = 150,
    ) -> float:
        """Estimate speech duration for a script."""
        return estimate_speech_duration(text, words_per_minute)

#     @function_tool(failure_error_function=tool_error("review_final_render"), strict_mode=False)
#     @log_tool("review_final_render")
#     async def review_final_render(output_path: Optional[str] = None) -> str:
#         """Render (if needed) and review the final video, returning QA notes."""
#         step_start = time.perf_counter()
#         print("[review] start review_final_render")
#         t0 = time.perf_counter()
#         scenes = storyboard_store.load(session_id) or []
#         print(f"[review] load storyboard in {time.perf_counter() - t0:.2f}s")
#         if not scenes:
#             print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
#             return "No storyboard scenes found. Create a storyboard before rendering."
#         scenes_payload = [
#             scene.model_dump(
#                 mode="json",
#                 exclude_none=True,
#             )
#             for scene in scenes
#         ]
#         scenes_context = json.dumps(scenes_payload, indent=2)

#         t0 = time.perf_counter()
#         storyboard_path = storyboard_store._storyboard_path(session_id, user_id=user_id)
#         storyboard_mtime = None
#         try:
#             if storyboard_path.exists():
#                 storyboard_mtime = storyboard_path.stat().st_mtime
#         except OSError:
#             storyboard_mtime = None
#         print(f"[review] check storyboard mtime in {time.perf_counter() - t0:.2f}s")

#         t0 = time.perf_counter()
#         render_path = _resolve_render_target(config, session_id, output_path)
#         needs_render = True
#         if render_path and render_path.exists() and storyboard_mtime is not None:
#             try:
#                 needs_render = storyboard_mtime > render_path.stat().st_mtime
#             except OSError:
#                 needs_render = True
#         elif render_path and render_path.exists():
#             needs_render = False
#         print(f"[review] resolve render target in {time.perf_counter() - t0:.2f}s")

#         if needs_render:
#             t0 = time.perf_counter()
#             result = _render_storyboard_scenes(
#                 scenes,
#                 config,
#                 session_id,
#                 storyboard_store.base_dir,
#                 render_path.name,
#                 company_id=company_id,
#             )
#             print(f"[review] render storyboard in {time.perf_counter() - t0:.2f}s")
#             if not result.success:
#                 print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
#                 return f"Render failed: {result.error_message or 'unknown error'}"
#             render_path = result.output_path or render_path

#         t0 = time.perf_counter()
#         client = GeminiClient(config)
#         uploaded = client.get_or_upload_file(render_path)
#         print(f"[review] upload render in {time.perf_counter() - t0:.2f}s")
#         review_prompt = f"""
# You are an expert Video Editor and Quality Assurance specialist.
# Your task is to watch the attached video and identify technical, visual, and narrative issues.
# Use the storyboard JSON to understand the intended sequence, narration, and clip sources.

# STORYBOARD SCENES (read-only JSON):
# {scenes_context}

# You are looking for ANY flaws that lower the quality of the video, including but not limited to:
# - Video is static for a long time, which reduces the video attractiveness.
# - Audio/Visual Mismatch: A narrator is speaking (Voice Over), but the visual shows a person talking to camera with unsynchronized lips (Bad Lip Reading).
# - Repetitive Footage: The same source video clip is used more than once in the same video.
# - Unwanted Text: Burnt-in subtitles, watermarks, or text overlays from the source footage that clash with the video.
# - Visual Flow: Jump cuts, black frames between clips, or abrupt transitions.
# - Narrative Match: The visual B-roll contradicts or doesn't fit what is being said in the Voice Over.
# - Language match: One of the scenes are not in the same language.

# Take your time to match the scenes to the video frames and the voice, and make sure everything is aligned perfectly.

# OUTPUT FORMAT
# Return a bulleted list of issues in natural language.
# Start every line with the timestamp where the issue occurs.
# If the video is perfect, just say "No issues found."

# Example:
# - [00:12] The narrator is talking about "silence" but the video shows a loud construction site, which feels conflicting.
# - [00:34] There are burnt-in Chinese subtitles at the bottom of the screen that shouldn't be there.
# - [00:45] The clip of the man typing on the laptop is a duplicate; it was already used previously at 00:05.
# - [01:05] The clip cuts to black for a split second before the next scene starts.
# """
#         from google.genai import types

#         file_uri = getattr(uploaded, "uri", None)
#         if file_uri:
#             contents = types.Content(
#                 parts=[
#                     types.Part(
#                         file_data=types.FileData(file_uri=file_uri),
#                         video_metadata=types.VideoMetadata(fps=10),
#                     ),
#                     types.Part(text=review_prompt),
#                 ]
#             )
#         else:
#             contents = [uploaded, review_prompt]
#         response = await client.client.aio.models.generate_content(
#             model=config.gemini_model,
#             contents=contents,
#             config={
#                 "max_output_tokens": 3_000,
#             },
#         )
#         review_text = response.text.strip() if response.text else ""
#         if not review_text:
#             review_text = "No issues found."
#         print(f"[review] finish review_final_render in {time.perf_counter() - step_start:.2f}s")
#         return review_text

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
        storage_client = get_storage_client(config)
        
        try:
            # Initialize the Genai client
            client = genai.Client(**build_vertex_client_kwargs(config))
            
            # Use the GCS URI directly for output
            gcs_key = _generated_scene_blob_key(company_id, session_id, output_filename)
            gcs_uri = storage_client.to_gs_uri(gcs_key)

            print(f"[generate_scene] Starting video generation ({duration_seconds}s) for prompt: {prompt[:100]}...")
            print(f"[generate_scene] Outputting directly to: {gcs_uri}")
            step_start = time.perf_counter()
            
            # Build generation config
            from google.genai.types import GenerateVideosConfig
            gen_config = GenerateVideosConfig(duration_seconds=duration_seconds, output_gcs_uri=gcs_uri)
            if negative_prompt:
                gen_config.negative_prompt = negative_prompt
            
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
            
            # Verify success (the video should be in GCS now)
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
            
            # Post-process: Vertex AI output_gcs_uri often creates a directory containing samples
            # We need to flatten this so the file exists at gcs_key
            if not storage_client.exists(gcs_key):
                print(f"[generate_scene] Target file {gcs_key} not found. Checking for nested samples...")
                candidates = list(storage_client.list_files(gcs_key + "/", recursive=True))
                sample_path = next((p for p in candidates if p.endswith(".mp4")), None)
                
                if sample_path:
                    print(f"[generate_scene] Found nested sample: {sample_path}. Moving to target...")
                    # Use internal bucket for rewrite
                    source_blob = storage_client.bucket.blob(sample_path)
                    dest_blob = storage_client.bucket.blob(gcs_key)
                    dest_blob.rewrite(source_blob)
                    print(f"[generate_scene] Move complete.")
                else:
                    print(f"[generate_scene] Warning: No generated video file found at {gcs_key} or nested.")
            
            # We skip downloading/uploading. Metadata is constructed manually since we trust the request params
            # and Veo defaults (1080p, 24fps).
            duration = float(duration_seconds)
            resolution = (1920, 1080)
            fps = 24.0
            
            storage_client.write_json(
                f"{gcs_key}.metadata.json",
                {
                    "video_id": video_id,
                    "duration": duration,
                    "resolution": list(resolution),
                    "fps": fps,
                    "scene_id": scene_id,
                },
            )
            
            event_store.append(
                session_id,
                {
                    "type": "video_generation_complete",
                    "status": "ok",
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "output": gcs_uri,
                    "gcs_path": gcs_uri,
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
        generate_scene,
    ]

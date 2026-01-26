"""
Agent runtime powered by the OpenAI Agents SDK using Gemini via LiteLLM.
"""
from __future__ import annotations

import asyncio
import json
import functools
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Callable, Optional
from uuid import uuid4

from agents import (
    Agent,
    ModelSettings,
    RunConfig,
    Runner,
    SQLiteSession,
    function_tool,
    set_tracing_export_api_key,
)
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from videoagent.config import Config, default_config
from videoagent.editor import VideoEditor
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.models import RenderResult, VoiceOver, VideoBrief
from videoagent.story import PersonalizedStoryGenerator, _StoryboardScene, _MatchedScene
from videoagent.voice import VoiceOverGenerator, estimate_speech_duration


class StoryboardUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[_StoryboardScene]


class StoryboardSceneUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: _StoryboardScene


class MatchedSceneUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    matched_scene: _MatchedScene


class MatchedScenesUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[MatchedSceneUpdateItem]


class VideoBriefUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: VideoBrief


class SceneMatchRequest(BaseModel):
    scene_id: str
    candidate_video_ids: list[str] = Field(
        description=(
            "Video ids from the library catalog for this scene (max 5)."
        )
    )
    notes: Optional[str] = None
    duration_seconds: Optional[float] = None


class SceneMatchBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[SceneMatchRequest] = Field(
        description="List of scene match requests to process in one call."
    )


class SceneMatchCandidate(BaseModel):
    video_id: str
    start_timestamp: str
    end_timestamp: str
    description: str
    rationale: str
    transcript_snippet: Optional[str] = None


class SceneMatchResponse(BaseModel):
    """Response from the scene matching LLM call."""
    candidates: list[SceneMatchCandidate] = Field(default_factory=list)
    notes: Optional[str] = None


class AgentResponse(BaseModel):
    response: str = Field(description="The natural language response to the user.")
    suggested_actions: list[str] = Field(
        description=(
            "A list of 1-3 short, actionable, and context-aware follow-up prompts for the user "
            "to continue the workflow. Examples: 'Match scenes 2 and 3', 'Generate all voice-overs', "
            "'Render the video', 'Change scene 1 title to ...'. "
            "If no obvious next step exists, list can be empty."
        ),
        max_length=3,
    )





def _parse_timestamp(text: str) -> float:
    """Parse MM:SS.sss timestamp format to seconds."""
    text = text.strip()
    if not text:
        raise ValueError("Empty timestamp.")
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected MM:SS.sss format, got '{text}'.")
    minutes, seconds = parts
    try:
        minutes_value = int(minutes)
    except ValueError as exc:
        raise ValueError(f"Invalid minutes value in '{text}'.") from exc
    if "." not in seconds:
        raise ValueError(f"Expected MM:SS.sss format, got '{text}'.")
    seconds_main, millis_text = seconds.split(".", 1)
    if not (seconds_main.isdigit() and len(seconds_main) == 2):
        raise ValueError(f"Invalid seconds value in '{text}'.")
    if not (millis_text.isdigit() and len(millis_text) == 3):
        raise ValueError(f"Invalid milliseconds value in '{text}'.")
    try:
        seconds_value = int(seconds_main) + (int(millis_text) / 1000.0)
    except ValueError as exc:
        raise ValueError(f"Invalid seconds value in '{text}'.") from exc
    if minutes_value < 0 or seconds_value < 0 or seconds_value >= 60:
        raise ValueError(f"Timestamp out of range (MM:SS.sss) in '{text}'.")
    return minutes_value * 60 + seconds_value


@dataclass
class EventStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _events_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.events.jsonl"

    def append(self, session_id: str, event: dict) -> None:
        path = self._events_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(event)
        payload.setdefault("ts", datetime.utcnow().isoformat() + "Z")
        with self._lock, path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")

    def read_since(self, session_id: str, cursor: Optional[int]) -> tuple[list[dict], int]:
        path = self._events_path(session_id)
        if not path.exists():
            return [], 0
        with self._lock, path.open("r", encoding="utf-8") as handle:
            if cursor is None:
                handle.seek(0, os.SEEK_END)
                return [], handle.tell()
            handle.seek(cursor)
            events = []
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return events, handle.tell()

    def clear(self, session_id: str) -> None:
        path = self._events_path(session_id)
        if path.exists():
            path.unlink()

@dataclass
class StoryboardStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _storyboard_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.storyboard.json"

    def load(self, session_id: str) -> Optional[list[_StoryboardScene]]:
        path = self._storyboard_path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [_StoryboardScene.model_validate(item) for item in data]

    def save(self, session_id: str, scenes: list[_StoryboardScene]) -> None:
        path = self._storyboard_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = [scene.model_dump(mode="json") for scene in scenes]
        with self._lock, path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def clear(self, session_id: str) -> None:
        path = self._storyboard_path(session_id)
        if path.exists():
            path.unlink()


@dataclass
class BriefStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _brief_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.brief.json"

    def load(self, session_id: str) -> Optional[VideoBrief]:
        path = self._brief_path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return VideoBrief.model_validate(data)

    def save(self, session_id: str, brief: VideoBrief) -> None:
        path = self._brief_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("w", encoding="utf-8") as handle:
            json.dump(brief.model_dump(mode="json"), handle, indent=2)

    def clear(self, session_id: str) -> None:
        path = self._brief_path(session_id)
        if path.exists():
            path.unlink()


@dataclass
class ChatStore:
    """Persist chat messages for a session."""
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _chat_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.chat.jsonl"

    def append(self, session_id: str, message: dict) -> None:
        """Append a message to the chat history."""
        path = self._chat_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(message)
        payload.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        with self._lock, path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")

    def load(self, session_id: str) -> list[dict]:
        """Load all messages for a session."""
        path = self._chat_path(session_id)
        if not path.exists():
            return []
        messages = []
        with self._lock, path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return messages

    def clear(self, session_id: str) -> None:
        path = self._chat_path(session_id)
        if path.exists():
            path.unlink()

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_env = Path(__file__).resolve().parents[3] / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    else:
        load_dotenv()


def _select_model_name(config: Config) -> str:
    return os.environ.get("AGENT_MODEL") or config.agent_model or f"gemini/{config.gemini_model}"


def _select_api_key(config: Config, model_name: str) -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or config.gemini_api_key


def _build_tools(
    config: Config,
    storyboard_store: StoryboardStore,
    brief_store: BriefStore,
    event_store: EventStore,
    session_id: str,
    auto_render_callback: Optional[Callable[[], None]] = None,
):
    def tool_error(name: str):
        def error_fn(ctx, error):
            return f"{name} failed: {error}, {ctx}"
        return error_fn

    def log_tool(name: str):
        def decorator(fn):
            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def wrapped(*args, **kwargs):
                    event_store.append(session_id, {"type": "tool_start", "name": name})
                    try:
                        result = await fn(*args, **kwargs)
                        event_store.append(session_id, {"type": "tool_end", "name": name, "status": "ok"})
                        return result
                    except Exception as exc:
                        event_store.append(
                            session_id,
                            {"type": "tool_end", "name": name, "status": "error", "error": str(exc)},
                        )
                        raise
                return wrapped
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                event_store.append(session_id, {"type": "tool_start", "name": name})
                try:
                    result = fn(*args, **kwargs)
                    event_store.append(session_id, {"type": "tool_end", "name": name, "status": "ok"})
                    return result
                except Exception as exc:
                    event_store.append(
                        session_id,
                        {"type": "tool_end", "name": name, "status": "error", "error": str(exc)},
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
        storyboard_store.save(session_id, payload.scenes)
        event_store.append(session_id, {"type": "storyboard_update"})
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
        scenes = storyboard_store.load(session_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before updating a scene."
        updated = False
        updated_scenes: list[_StoryboardScene] = []
        for scene in scenes:
            if scene.scene_id == payload.scene.scene_id:
                updated_scenes.append(payload.scene)
                updated = True
            else:
                updated_scenes.append(scene)
        if not updated:
            return f"Storyboard scene id not found: {payload.scene.scene_id}"
        storyboard_store.save(session_id, updated_scenes)
        event_store.append(session_id, {"type": "storyboard_update"})
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
        scenes = storyboard_store.load(session_id) or []
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
            storyboard_store.save(session_id, scenes)
            event_store.append(session_id, {"type": "storyboard_update"})
        
        msg = f"Updated matched details for {updated_count} scene(s)."
        if missing_ids:
            msg += f" Warning: Scene IDs not found: {', '.join(missing_ids)}"
        return msg

    @function_tool(failure_error_function=tool_error("update_video_brief"), strict_mode=True)
    @log_tool("update_video_brief")
    def update_video_brief(payload: VideoBriefUpdatePayload) -> str:
        """Update/Replace the video brief details (objective, persona, key_messages)."""
        brief_store.save(session_id, payload.brief)
        event_store.append(session_id, {"type": "video_brief_update"})
        return "Video brief updated successfully. UI will reflect changes."

    @function_tool(failure_error_function=tool_error("render_storyboard"), strict_mode=False)
    @log_tool("render_storyboard")
    def render_storyboard(output_filename: Optional[str] = None) -> str:
        """Render storyboard scenes to a video file."""
        event_store.append(session_id, {"type": "video_render_start"})
        scenes = storyboard_store.load(session_id) or []
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
        event_store.append(session_id, {"type": "video_render_start"})
        
        step_start = time.perf_counter()
        scenes = storyboard_store.load(session_id) or []
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
        generator = VoiceOverGenerator(config)
        try:
            voice_dir = (storyboard_store.base_dir / session_id / "voice_overs")
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
            storyboard_store.save(session_id, scenes)
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
        If a voice over exists, its duration takes precedence over duration_seconds. When duration_seconds
        is provided with a voice over, the tool still runs and emits a warning in its response.
        """
        step_start = time.perf_counter()
        scenes = storyboard_store.load(session_id) or []
        if not scenes:
            return "No storyboard scenes found. Create a storyboard before matching scenes."
        if not payload.requests:
            return "No scene match requests provided."

        scene_map = {scene.scene_id: scene for scene in scenes}

        library = VideoLibrary(config)
        library.scan_library()

        all_candidate_ids = {
            video_id
            for request in payload.requests
            for video_id in request.candidate_video_ids
        }
        video_map = {
            video_id: library.get_video(video_id)
            for video_id in all_candidate_ids
        }

        results_by_scene_id: dict[str, dict] = {}
        notes_by_scene_id: dict[str, list[str]] = {}
        warnings_by_scene_id: dict[str, list[str]] = {}
        errors: list[dict] = []
        jobs: list[dict] = []

        for request in payload.requests:
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
                video_id for video_id in request.candidate_video_ids
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

            if scene.use_voice_over:
                voice_over = scene.voice_over
                if (
                    not (voice_over and voice_over.duration)
                    and request.duration_seconds is None
                ):
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

            results_by_scene_id.setdefault(
                request.scene_id,
                {"scene_id": request.scene_id, "candidates": []},
            )
            notes_by_scene_id.setdefault(request.scene_id, [])
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
                if not metadata:
                    continue
                jobs.append(
                    {
                        "scene_id": request.scene_id,
                        "scene": scene,
                        "video_id": video_id,
                        "metadata": metadata,
                        "notes": request.notes,
                        "audio_mode_header": audio_mode_header,
                        "visual_constraints": visual_constraints,
                        "duration_section": duration_section,
                        "transcript_text": transcript_text,
                    }
                )

        if not jobs:
            response_payload = {"results": []}
            if errors:
                response_payload["errors"] = errors
            return json.dumps(response_payload)

        client = GeminiClient(config)
        uploaded_files: dict[str, object] = {}
        failed_uploads: dict[str, str] = {}
        upload_durations: dict[str, float] = {}
        for video_id in {job["video_id"] for job in jobs}:
            metadata = video_map.get(video_id)
            if not metadata:
                continue
            upload_started = time.perf_counter()
            try:
                uploaded_files[video_id] = client.get_or_upload_file(metadata.path)
            except Exception as exc:
                failed_uploads[video_id] = str(exc)
            upload_durations[video_id] = time.perf_counter() - upload_started

        if failed_uploads:
            remaining_jobs = []
            for job in jobs:
                if job["video_id"] in failed_uploads:
                    errors.append(
                        {
                            "scene_id": job["scene_id"],
                            "video_id": job["video_id"],
                            "error": (
                                "Failed to upload video: "
                                f"{failed_uploads[job['video_id']]}"
                            ),
                        }
                    )
                    continue
                remaining_jobs.append(job)
            jobs = remaining_jobs

        if not jobs:
            response_payload = {"results": []}
            if errors:
                response_payload["errors"] = errors
            return json.dumps(response_payload)

        def _build_prompt(job: dict) -> str:
            scene = job["scene"]
            scene_text = (
                f"Scene title: {scene.title}\n"
                f"Scene purpose: {scene.purpose}\n"
            )
            notes_text = f"\nNOTES:\n{job['notes']}\n" if job["notes"] else ""
            metadata = job["metadata"]
            return f"""You are an expert video asset manager. This request evaluates a SINGLE candidate video for a specific scene in a personalized video.
The main agent will merge results across videos and update the story, so do not compare across videos. The agent cannot see the video, so your descriptions must be vivid.

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
- Return 0 or 1 candidate clip from the single video above.
- If this video does not fulfill the requirements, return an empty candidates list and include a notes field explaining why.
- For each candidate include start_timestamp, end_timestamp, description, rationale.
- Use MM:SS.sss format for start_timestamp and end_timestamp (milliseconds required).
- **RATIONALE REQUIREMENT:** In your rationale, explicitly state how the clip fits the visual constraints (e.g., "Confirmed: Subject is listening, lips are not moving" or "Confirmed: Subject is speaking to camera").
- Use only the video_id value listed above; copy it exactly.
- Do not reference any other videos.

EXAMPLE OUTPUT:
{{"candidates":[{{"video_id":"abcd1234","start_timestamp":"02:15.000","end_timestamp":"02:24.250","description":"Executive smiling and nodding while looking at a colleague.","rationale":"Perfect B-roll match; subject is engaged but not speaking, fitting the voice-over requirement.","transcript_snippet":"..."}}]}}
"""

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
                        "Timestamp format error. Expected MM:SS.sss. "
                        f"Video {candidate.video_id} returned start={candidate.start_timestamp}, "
                        f"end={candidate.end_timestamp}. Error: {exc}"
                    ) from exc
                if duration is not None:
                    tolerance_seconds = 0.7
                    if start_seconds < 0 and abs(start_seconds) <= tolerance_seconds:
                        start_seconds = 0.0
                    if end_seconds > duration and (end_seconds - duration) <= tolerance_seconds:
                        end_seconds = duration
                    if start_seconds > duration and (start_seconds - duration) <= tolerance_seconds:
                        start_seconds = duration
                if duration is not None:
                    if start_seconds < 0 or end_seconds <= start_seconds:
                        raise ValueError(
                            "Timestamp range error. Start must be >= 00:00 and end must be > start. "
                            f"Video {candidate.video_id} returned "
                            f"{candidate.start_timestamp}-{candidate.end_timestamp}."
                        )
                    if start_seconds >= duration or end_seconds > duration:
                        raise ValueError(
                            "Timestamp duration error. Returned timestamps exceed the video duration. "
                            f"Video {candidate.video_id} duration {duration:.2f}s, "
                            f"returned {candidate.start_timestamp}-{candidate.end_timestamp}."
                        )
                normalized_candidates.append(
                    {
                        "video_id": candidate.video_id,
                        "start_timestamp": start_seconds,
                        "end_timestamp": end_seconds,
                        "description": candidate.description,
                        "rationale": candidate.rationale,
                        "transcript_snippet": candidate.transcript_snippet,
                    }
                )
            return normalized_candidates

        from google.genai import types

        def _print_prompt_log(job: dict, llm_response_time: Optional[float], usage_metadata: Optional[types.UsageMetadata]) -> None:
            if usage_metadata:
                usage_metadata = usage_metadata.model_dump()
            else:
                usage_metadata = {}
            print(
                json.dumps(
                    {
                        "video_id": job["video_id"],
                        "video_length": job["metadata"].duration,
                        "upload_time": upload_durations.get(job["video_id"]),
                        "llm_response_time": llm_response_time,
                        "usage_metadata": usage_metadata,
                    }
                )
            )

        async def _run_job(job: dict) -> dict:
            job_start = time.perf_counter()
            prompt = _build_prompt(job)
            uploaded = uploaded_files.get(job["video_id"])
            if not uploaded:
                _print_prompt_log(job, llm_response_time=None)
                return {
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": "Video file was not uploaded.",
                }
            parts: list[types.Part] = []
            file_uri = getattr(uploaded, "uri", None)
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
                contents = [uploaded, prompt]
            llm_start = time.perf_counter()
            try:
                response = await client.client.aio.models.generate_content(
                    model=config.gemini_model,
                    contents=contents,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": SceneMatchResponse.model_json_schema(),
                        "thinking_config": types.ThinkingConfig(thinking_budget=4096)
                    },
                )
            except Exception as exc:
                _print_prompt_log(job, time.perf_counter() - llm_start, None)
                raise
            llm_response_time = time.perf_counter() - llm_start
            if not response.text:
                _print_prompt_log(job, llm_response_time, response.usage_metadata)
                return {
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": "Model returned an empty response.",
                }
            try:
                selection = SceneMatchResponse.model_validate_json(response.text)
            except ValidationError as exc:
                _print_prompt_log(job, llm_response_time, response.usage_metadata)
                return {
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": f"Model response validation error: {exc}",
                }
            invalid_selected = [
                candidate.video_id
                for candidate in selection.candidates
                if candidate.video_id != job["video_id"]
            ]
            if invalid_selected:
                _print_prompt_log(job, llm_response_time, response.usage_metadata)
                return {
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": (
                        "Model selected video_id(s) outside candidate set: "
                        + ", ".join(invalid_selected)
                    ),
                }
            try:
                normalized_candidates = _normalize_candidates(
                    selection,
                    job["video_id"],
                    job["metadata"].duration,
                )
            except ValueError as exc:
                _print_prompt_log(job, llm_response_time, response.usage_metadata)
                return {
                    "scene_id": job["scene_id"],
                    "video_id": job["video_id"],
                    "error": str(exc),
                }
            _print_prompt_log(job, llm_response_time, response.usage_metadata)
            return {
                "scene_id": job["scene_id"],
                "video_id": job["video_id"],
                "candidates": normalized_candidates,
                "notes": selection.notes,
            }

        semaphore = asyncio.Semaphore(30)

        async def _run_with_limit(job: dict) -> dict:
            async with semaphore:
                return await _run_job(job)

        results = await asyncio.gather(
            *[asyncio.create_task(_run_with_limit(job)) for job in jobs],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                errors.append({"error": str(result)})
                continue
            if result.get("error"):
                errors.append(
                    {
                        "scene_id": result.get("scene_id"),
                        "video_id": result.get("video_id"),
                        "error": result.get("error"),
                    }
                )
                continue
            scene_id = result["scene_id"]
            results_by_scene_id[scene_id]["candidates"].extend(
                result.get("candidates", [])
            )
            if result.get("notes"):
                notes_by_scene_id[scene_id].append(
                    f"{result['video_id']}: {result['notes']}"
                )

        response_results = []
        for scene_id, payload in results_by_scene_id.items():
            entry = {
                "scene_id": scene_id,
                "candidates": payload["candidates"],
            }
            notes = notes_by_scene_id.get(scene_id)
            warnings = warnings_by_scene_id.get(scene_id)
            if notes:
                entry["notes"] = "\n".join(notes)
            if warnings:
                entry["warnings"] = warnings
            response_results.append(entry)

        response_payload = {"results": response_results}
        if errors:
            response_payload["errors"] = errors

        # Signal completion of the video generation/matching phase
        event_store.append(session_id, {"type": "video_render_complete"})

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
        storyboard_path = storyboard_store._storyboard_path(session_id)
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

    return [
        update_storyboard,
        update_storyboard_scene,
        update_matched_scenes,
        update_video_brief,
        match_scene_to_video,
        generate_voice_overs,
        estimate_voice_duration,
    ]


def _sanitize_output_filename(filename: str) -> str:
    if not filename:
        return "output.mp4"
    path = Path(filename)
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        return filename
    return f"{path.stem}.mp4"


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
    library = VideoLibrary(config)
    library.scan_library()
    video_paths: dict[str, Path] = {}
    for scene in scenes:
        matched_scene = scene.matched_scene
        if not matched_scene:
            continue
        if matched_scene.source_video_id in video_paths:
            continue
        metadata = library.get_video(matched_scene.source_video_id)
        if not metadata:
            return RenderResult(
                success=False,
                error_message=(
                    "Video id(s) not found: " + matched_scene.source_video_id
                ),
            )
        video_paths[matched_scene.source_video_id] = metadata.path
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


def _voice_over_path_for_id(
    session_id: str,
    base_dir: Path,
    audio_id: str,
) -> Path:
    return base_dir / session_id / "voice_overs" / f"vo_{audio_id}.wav"


def _find_latest_render_path(
    config: Config,
    session_id: str,
    output_path: Optional[str] = None,
) -> Optional[Path]:
    if output_path:
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = config.output_dir / candidate
        return candidate if candidate.exists() else None

    output_dir = config.output_dir
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
        if session_id in name:
            score += 10
        if name.startswith(f"{session_id}_auto"):
            score += 5
        if name.startswith("output"):
            score += 1
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return score, mtime

    return max(candidates, key=_score)


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
    latest = _find_latest_render_path(config, session_id, output_path=None)
    if latest:
        return latest
    return config.output_dir / f"{session_id}_final.mp4"




class VideoAgentService:
    def __init__(self, config: Optional[Config] = None, base_dir: Optional[Path] = None):
        self.config = config or default_config
        self.base_dir = base_dir or (Path.cwd() / "output" / "agent_sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.storyboard_store = StoryboardStore(self.base_dir)
        self.brief_store = BriefStore(self.base_dir)
        self.event_store = EventStore(self.base_dir)
        self.chat_store = ChatStore(self.base_dir)
        self.session_db_path = self.base_dir / "agent_memory.db"
        self._agents: dict[str, Agent] = {}
        self._agent_lock = Lock()
        self._run_lock = Lock()
        self._render_lock = Lock()
        self._render_executor = ThreadPoolExecutor(max_workers=1)
        self._render_futures: dict[str, object] = {}
        _load_env()
        self._configure_tracing()

        self._base_instructions = """# Collaborative Video Editing Agent System Prompt

## Role & Core Behavior

You are a **Collaborative Video Editing Agent**. Your goal is to help a user iteratively build a personalized video for a customer.

* **Iterative Process:** Propose, ask, and adjust based on user feedback. Do not execute the full pipeline alone.
* **Data Persistence:** Persist all changes to storyboard or customer details using the corresponding update tools before replying.
* **UI Focus:** Use tools to update the user's UI. Keep chat responses concise and let the UI handle the heavy data display.

---

## Stage 0: Video Brief Creation (MANDATORY FIRST STEP)

**Goal:** Define the objective, persona, and key messages for the video.
* **Action:** You must ALWAYS start by creating a Video Brief based on the user's input.
* **Tool:** Use `update_video_brief` to save the brief.
* **Constraint:** You CANNOT proceed to Storyboard Generation until the Video Brief is created and saved.

---

## Stage 1: Storyboard Generation

**Goal:** Create a high-level narrative plan including titles, purposes, scripts, and `use_voice_over` status.
* **Action:** Call `update_storyboard` to save changes. Make sure 'matched_scene' is empty for all scenes at this stage.
* **Constraint:** Once the initial storyboard is created, **IMMEDIATELY** proceed to Stage 2. Do NOT ask for user feedback.
* **Testimony Rule:** Customer testimonies must **NOT** have a voice over. The testimony should always be introduced the in previous scene. Otherwise it might feel abrupt.
* **Introductions:** The scene immediately preceding a testimony must introduce the speaker by name, role, and company if available.

---

## Stage 2: Video Matching & Production

**Goal:** Convert the storyboard into a production plan and render the video.

### 1. Mapping & Voice Over
* **Audio:** Call `generate_voice_overs` for required storyboard scene IDs.

### 2. Scene Matching & Footage Selection
* **Shortlisting:** Scan transcripts and shortlist up to 5 candidate video IDs for each scene.
* **Matching:** Call `match_scene_to_video` with a list of scene requests.
* **Visual Guidelines:**
* **Clarity:** If a voice over is present, avoid scenes with people speaking or visible subtitles.
* **Language:** If the original voice is kept, make sure the selected candidate is in the same language as the final video.
* **Testimony Clips:** Prompt for ~30s for testimonies to ensure they look genuine.
DO NOT use the transcript to match scenes. Always rely on your scene matching tool.
The scene matching is a fairly dynamic process.
You might have to split, merge or completely rewrite a scene to make it a better fit for the user request.
If you change the voice over script, make sure you regenerate the audio to get the new duration. If the new duration does not match the duration of the video, you will need to find a new video to match the new duration.


### 3. Rendering
* **Execution:** The system will automatically render the video when scenes are matched.
---
## Response Format

**IMPORTANT:** You MUST always respond with valid JSON matching this exact schema:
```json
{
  "response": "Your helpful message to the user (markdown supported)",
  "suggested_actions": ["Action 1", "Action 2"]
}
```

**Rules:**
* `response`: Short, helpful message. Markdown is supported. Don't expose internal tool names.
* `suggested_actions`: 1-2 short, actionable follow-up prompts the user can click.
* If no obvious next step exists, use an empty array `[]`.
* **Call to Action:** Always suggest a specific, high-value next step to guide the user.
* Handling errors: If you hit a technical issue, try to rerun the tool a second time. If it's still not working, inform the user that you have hit a technical issue and ask them to try again later.
"""

    def get_video_brief(self, session_id: str) -> Optional[VideoBrief]:
        return self.brief_store.load(session_id)

    def _configure_tracing(self) -> None:
        tracing_key = os.environ.get("OPENAI_API_KEY")
        if tracing_key:
            set_tracing_export_api_key(tracing_key)

    def _build_instructions(self, context_payload: dict) -> str:
        context_block = json.dumps(context_payload, indent=2)
        return (
            f"{self._base_instructions}\n\n"
            "Context for this session (read-only JSON):\n"
            f"{context_block}"
        )

    def _build_context_payload(self, session_id: str, video_transcripts: list[dict]) -> dict:
        storyboard_scenes = self.storyboard_store.load(session_id)
        video_brief = self.brief_store.load(session_id)
        return {
            "video_transcripts": video_transcripts,
            "video_brief": video_brief.model_dump(mode="json") if video_brief else None,
            "storyboard_scenes": [
                scene.model_dump(mode="json")
                for scene in storyboard_scenes
            ] if storyboard_scenes else None,
        }

    def _get_agent(self, session_id: str) -> Agent:
        with self._agent_lock:
            video_transcripts: Optional[list[dict]] = None

            def _dynamic_instructions(run_context, agent) -> str:
                nonlocal video_transcripts
                if video_transcripts is None:
                    video_transcripts = self._build_video_transcripts()
                payload = self._build_context_payload(session_id, video_transcripts)
                return self._build_instructions(payload)

            agent = self._agents.get(session_id)
            if agent:
                agent.instructions = _dynamic_instructions
                return agent

            model_name = _select_model_name(self.config)
            self.model_name = model_name
            api_key = _select_api_key(self.config, model_name)
            model = LitellmModel(model=model_name, api_key=api_key)
            tools = _build_tools(
                self.config,
                self.storyboard_store,
                self.brief_store,
                self.event_store,
                session_id,
                auto_render_callback=lambda: self.schedule_auto_render(session_id),
            )
            agent = Agent(
                name="VideoAgent",
                instructions=_dynamic_instructions,
                tools=tools,
                model=model,
                model_settings=ModelSettings(include_usage=True,)
            )
            self._agents[session_id] = agent
            return agent

    def create_session(self) -> str:
        return uuid4().hex

    def list_sessions(self) -> list[dict]:
        """List all available sessions with their creation timestamps."""
        sessions = []
        if not self.base_dir.exists():
            return sessions
        
        # Find all storyboard files to identify sessions
        for path in self.base_dir.glob("*.storyboard.json"):
            session_id = path.stem.replace(".storyboard", "")
            # Use file modification time as created_at
            mtime = path.stat().st_mtime
            created_at = datetime.fromtimestamp(mtime).isoformat() + "Z"
            sessions.append({
                "session_id": session_id,
                "created_at": created_at,
            })
        
        # Sort by created_at descending (most recent first)
        sessions.sort(key=lambda s: s["created_at"], reverse=True)
        return sessions

    def get_storyboard(self, session_id: str) -> Optional[list[_StoryboardScene]]:
        scenes = self.storyboard_store.load(session_id)
        if not scenes:
            return None
        
        # Populate audio_path for voice overs
        for scene in scenes:
            if scene.voice_over and scene.voice_over.audio_id:
                path = _voice_over_path_for_id(
                    session_id, 
                    self.storyboard_store.base_dir, 
                    scene.voice_over.audio_id
                )
                if path.exists():
                    scene.voice_over.audio_path = str(path)
        
        return scenes

    def save_storyboard(self, session_id: str, scenes: list[_StoryboardScene]) -> None:
        self.storyboard_store.save(session_id, scenes)

    def save_video_brief(self, session_id: str, brief: VideoBrief) -> None:
        self.brief_store.save(session_id, brief)

    def get_chat_history(self, session_id: str) -> list[dict]:
        """Get all chat messages for a session."""
        return self.chat_store.load(session_id)

    def append_chat_message(self, session_id: str, role: str, content: str, suggested_actions: list[str] = None) -> None:
        """Append a chat message to the session history."""
        message = {
            "role": role,
            "content": content,
        }
        if suggested_actions:
            message["suggested_actions"] = suggested_actions
        self.chat_store.append(session_id, message)

    def _build_video_transcripts(self) -> list[dict]:
        library = VideoLibrary(self.config)
        library.scan_library()
        videos = library.list_videos()
        transcript_payload = []
        for video in videos:
            transcript_payload.append({
                "id": video.id,
                "filename": video.filename,
                "duration": video.duration,
                "transcript": video.get_full_transcript(),
            })
        return transcript_payload

    def preupload_library_content(self) -> list[dict]:
        """Upload all videos used by the main agent's transcript context."""
        from tqdm import tqdm

        library = VideoLibrary(self.config)
        library.scan_library()
        videos = library.list_videos()
        client = GeminiClient(self.config)
        uploaded = []
        for video in tqdm(videos, desc="Preuploading videos", unit="video"):
            file_obj = client.get_or_upload_file(video.path)
            file_name = getattr(file_obj, "name", None) or getattr(file_obj, "id", None)
            uploaded.append({
                "video_id": video.id,
                "filename": video.filename,
                "gemini_file_name": file_name,
            })
        return uploaded

    def run_turn(self, session_id: str, user_message: str) -> dict:
        agent = self._get_agent(session_id)

        session = SQLiteSession(session_id, str(self.session_db_path))
        ui_update_tools = {
            "update_storyboard",
            "update_video_brief",
        }
        redacted_args = json.dumps(
            {"note": "REDACTED TO REDUCE TOKEN USAGE; SEE LATEST STATE IN SYSTEM PROMPT"}
        )

        def _scrub_input_item(item):
            if not isinstance(item, dict):
                return item
            if item.get("type") == "function_call" and item.get("name") in ui_update_tools:
                scrubbed = dict(item)
                scrubbed["arguments"] = redacted_args
                return scrubbed
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                scrubbed_calls = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        scrubbed_calls.append(call)
                        continue
                    call_copy = dict(call)
                    func = call_copy.get("function")
                    if isinstance(func, dict):
                        name = func.get("name")
                        if name in ui_update_tools and "arguments" in func:
                            func_copy = dict(func)
                            func_copy["arguments"] = redacted_args
                            call_copy["function"] = func_copy
                    scrubbed_calls.append(call_copy)
                scrubbed = dict(item)
                scrubbed["tool_calls"] = scrubbed_calls
                return scrubbed
            return item

        def _merge_session_input(history, new_input):
            scrubbed_history = [_scrub_input_item(item) for item in history]
            return scrubbed_history + new_input

        run_config = RunConfig(
            workflow_name="VideoAgent chat",
            group_id=session_id,
            session_input_callback=_merge_session_input,
        )
        self.event_store.append(
            session_id,
            {"type": "run_start", "message": user_message},
        )
        
        # Save user message to chat history
        self.append_chat_message(session_id, "user", user_message)
        
        try:
            with self._run_lock:
                result = Runner.run_sync(
                    agent,
                    input=user_message,
                    session=session,
                    max_turns=100,
                    run_config=run_config,
                )
            output = result.final_output
            if not isinstance(output, str):
                output = str(output)
            
            # Try to parse structured JSON response
            response_text = output
            suggested_actions = []
            try:
                # Handle markdown code blocks
                text = output.strip()
                if text.startswith("```"):
                    # Remove markdown code fence
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines)
                
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "response" in parsed:
                    response_text = parsed.get("response", "")
                    suggested_actions = parsed.get("suggested_actions", [])
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Save assistant response to chat history
            self.append_chat_message(session_id, "assistant", response_text, suggested_actions)
            
            return {
                "response": response_text,
                "suggested_actions": suggested_actions,
            }
        finally:
            self.event_store.append(session_id, {"type": "run_end"})

    def get_events(self, session_id: str, cursor: Optional[int]) -> tuple[list[dict], int]:
        return self.event_store.read_since(session_id, cursor)

    def render_segments(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        return self.render_storyboard(session_id, output_filename)

    def render_storyboard(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        scenes = self.storyboard_store.load(session_id) or []
        result = _render_storyboard_scenes(
            scenes,
            self.config,
            session_id,
            self.storyboard_store.base_dir,
            output_filename,
        )
        if not result.success:
            raise ValueError(result.error_message or "Storyboard render failed.")
        return result



    def generate_storyboard(self, session_id: str, brief: str) -> list[_StoryboardScene]:
        """Calls the generator directly for a text-only draft, bypassing TTS and Video matching."""
        generator = PersonalizedStoryGenerator(self.config)
        scenes = generator.plan_storyboard(brief)
        self.storyboard_store.save(session_id, scenes)
        # if brief:
        #     self.brief_store.save(session_id, brief) # Cannot save raw string to BriefStore
        return scenes

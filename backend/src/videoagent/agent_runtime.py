"""
Agent runtime powered by the OpenAI Agents SDK using Gemini via LiteLLM.
"""
from __future__ import annotations

import asyncio
import json
import functools
import os
import shutil
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
from videoagent.models import (
    RenderResult,
    SegmentType,
    StorySegment,
    TranscriptMatch,
    VideoMetadata,
    VideoSegment,
    VoiceOver,
)
from videoagent.story import PersonalizedStoryGenerator, _StoryboardScene
from videoagent.voice import VoiceOverGenerator, estimate_speech_duration


class StoryboardUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[_StoryboardScene]


class VideoSegmentInput(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    source_video_id: Optional[str] = None
    start_time: float
    end_time: float
    description: Optional[str] = None
    keep_original_audio: bool = True


class VoiceOverInput(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    script: str
    audio_id: Optional[str] = None
    duration: Optional[float] = None
    voice: str = "achernar"
    speed: float = 1.0
    volume: float = 1.0
    id: Optional[str] = None


class StorySegmentInput(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    segment_type: SegmentType
    content: VideoSegmentInput
    storyboard_scene_id: Optional[str] = None
    voice_over: Optional[VoiceOverInput] = None
    transcript: Optional[str] = None
    order: int
    id: str


class SegmentUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[StorySegmentInput]


class CustomerDetailsUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    details: str


class SceneMatchRequest(BaseModel):
    segment_id: str
    candidate_video_ids: list[str] = Field(
        description=(
            "Video ids from the library catalog."
        )
    )
    notes: Optional[str] = None
    duration_seconds: Optional[float] = None


class SceneMatchCandidate(BaseModel):
    video_id: str
    start_timestamp: str
    end_timestamp: str
    description: str
    rationale: str
    transcript_snippet: Optional[str] = None


class SceneMatchResponse(BaseModel):
    candidates: list[SceneMatchCandidate]


def _parse_timestamp(text: str) -> float:
    text = text.strip()
    if not text:
        raise ValueError("Empty timestamp.")
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected MM:SS format, got '{text}'.")
    minutes, seconds = parts
    try:
        minutes_value = int(minutes)
    except ValueError as exc:
        raise ValueError(f"Invalid minutes value in '{text}'.") from exc
    try:
        seconds_value = float(seconds)
    except ValueError as exc:
        raise ValueError(f"Invalid seconds value in '{text}'.") from exc
    if minutes_value < 0 or seconds_value < 0 or seconds_value >= 60:
        raise ValueError(f"Timestamp out of range (MM:SS) in '{text}'.")
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
class SegmentStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _segments_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.segments.json"

    def load(self, session_id: str) -> Optional[list[StorySegment]]:
        path = self._segments_path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [StorySegment.model_validate(item) for item in data]

    def save(self, session_id: str, segments: list[StorySegment]) -> None:
        path = self._segments_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = [segment.model_dump(mode="json") for segment in segments]
        with self._lock, path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def clear(self, session_id: str) -> None:
        path = self._segments_path(session_id)
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
class CustomerStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _customer_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.customer.json"

    def load(self, session_id: str) -> Optional[str]:
        path = self._customer_path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, session_id: str, details: str) -> None:
        path = self._customer_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("w", encoding="utf-8") as handle:
            json.dump(details, handle, indent=2)

    def clear(self, session_id: str) -> None:
        path = self._customer_path(session_id)
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
    segment_store: SegmentStore,
    storyboard_store: StoryboardStore,
    customer_store: CustomerStore,
    event_store: EventStore,
    schedule_render: Optional[Callable[[str], None]],
    set_review_context: Optional[Callable[[str, object, Path], None]],
    session_id: str,
):
    def tool_error(name: str):
        def error_fn(ctx, error):
            return f"{name} failed: {error}"
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

    def validate_segments(segments: list[StorySegment]) -> list[str]:
        warnings: list[str] = []
        library = VideoLibrary(config)
        library.scan_library()
        for segment in segments:
            content = segment.content
            if not content.source_video_id:
                continue
            metadata = library.get_video(content.source_video_id)
            if not metadata:
                warnings.append(
                    f"Segment {segment.id}: source_video_id {content.source_video_id} not found."
                )
                continue
            if content.start_time < 0 or content.end_time <= content.start_time:
                warnings.append(
                    f"Segment {segment.id}: invalid time range {content.start_time:.2f}-{content.end_time:.2f}s."
                )
                continue
            if content.start_time >= metadata.duration or content.end_time > metadata.duration:
                warnings.append(
                    f"Segment {segment.id}: range {content.start_time:.2f}-{content.end_time:.2f}s "
                    f"exceeds video duration {metadata.duration:.2f}s."
                )
        return warnings

    @function_tool(failure_error_function=tool_error("scan_library"), strict_mode=False)
    @log_tool("scan_library")
    def scan_library(force_reindex: bool = False) -> list[VideoMetadata]:
        """Scan and list all videos in the library."""
        library = VideoLibrary(config)
        library.scan_library(force_reindex=force_reindex)
        videos = library.list_videos()
        return videos

    @function_tool(failure_error_function=tool_error("list_videos"), strict_mode=False)
    @log_tool("list_videos")
    def list_videos(query: Optional[str] = None) -> list[VideoMetadata]:
        """List all videos in the library (uses existing index)."""
        library = VideoLibrary(config)
        videos = library.list_videos()
        if query:
            query_lower = query.lower()
            videos = [
                video for video in videos
                if query_lower in video.filename.lower()
                or query_lower in video.get_full_transcript().lower()
            ]
        return videos

    @function_tool(failure_error_function=tool_error("get_video"), strict_mode=False)
    @log_tool("get_video")
    def get_video(video_id: str) -> Optional[VideoMetadata]:
        """Fetch a single video by id."""
        library = VideoLibrary(config)
        return library.get_video(video_id)

    @function_tool(failure_error_function=tool_error("search_by_duration"), strict_mode=False)
    @log_tool("search_by_duration")
    def search_by_duration(
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> list[VideoMetadata]:
        """Search videos by duration in seconds."""
        library = VideoLibrary(config)
        return library.search_by_duration(min_duration=min_duration, max_duration=max_duration)

    @function_tool(failure_error_function=tool_error("search_by_transcript_keyword"), strict_mode=False)
    @log_tool("search_by_transcript_keyword")
    def search_by_transcript_keyword(keyword: str) -> list[TranscriptMatch]:
        """Search videos by transcript keyword."""
        library = VideoLibrary(config)
        results = library.search_by_transcript_keyword(keyword)
        return [TranscriptMatch(video=video, segments=segments) for video, segments in results]

    @function_tool(failure_error_function=tool_error("generate_story_segments"), strict_mode=False)
    @log_tool("generate_story_segments")
    def generate_story_segments(
        customer_situation: str,
    ) -> list[StorySegment]:
        """Generate story segments from a customer situation."""
        generator = PersonalizedStoryGenerator(config)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(generator.generate_segments(customer_situation))

        def _runner() -> list[StorySegment]:
            return asyncio.run(generator.generate_segments(customer_situation))

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_runner).result()

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
        return "UI updated successfully"

    @function_tool(failure_error_function=tool_error("update_customer_details"), strict_mode=True)
    @log_tool("update_customer_details")
    def update_customer_details(payload: CustomerDetailsUpdatePayload) -> str:
        """Replace the customer details text for this session (must be full description, not a delta)."""
        customer_store.save(session_id, payload.details)
        return "UI updated successfully"

    @function_tool(failure_error_function=tool_error("get_segments"), strict_mode=False)
    @log_tool("get_segments")
    def get_segments() -> list[StorySegment]:
        """Return the current story segments."""
        segments = segment_store.load(session_id)
        return segments or []

    @function_tool(
        failure_error_function=tool_error("update_story_segments"),
        strict_mode=True,
    )
    @log_tool("update_story_segments")
    def update_story_segments(payload: SegmentUpdatePayload) -> str:
        """Replace current story segments with full list."""
        segments = _input_segments_to_model(payload.segments)
        normalized = _normalize_segments_for_storage(segments)
        segment_store.save(session_id, normalized)
        warnings = validate_segments(normalized)
        if warnings:
            event_store.append(
                session_id,
                {"type": "segment_warning", "message": " | ".join(warnings)},
            )
        if schedule_render:
            schedule_render(session_id)
        if warnings:
            return "UI updated with warnings: " + " | ".join(warnings)
        return "UI updated successfully"

    @function_tool(failure_error_function=tool_error("render_story_segments"), strict_mode=False)
    @log_tool("render_story_segments")
    def render_story_segments(
        segments_json: str,
        output_filename: Optional[str] = None,
    ) -> RenderResult:
        """Render story segments to a video file."""
        library = VideoLibrary(config)
        library.scan_library()
        editor = VideoEditor(config)
        try:
            segments = _parse_json_segments(segments_json)
            hydrated = _hydrate_segments(segments, library)
            return editor.render_segments(
                hydrated,
                output_filename=_sanitize_output_filename(output_filename or "output.mp4"),
                voice_over_paths=_build_voice_over_paths(
                    hydrated,
                    session_id,
                    segment_store.base_dir,
                ),
            )
        finally:
            editor.cleanup()

    @function_tool(failure_error_function=tool_error("generate_voice_overs"), strict_mode=False)
    @log_tool("generate_voice_overs")
    async def generate_voice_overs(segment_ids: list[str]) -> str:
        """Generate voice overs for selected story segments by id and return them."""
        segments = segment_store.load(session_id) or []
        if not segments:
            return "No story segments found. Create story segments before generating voice overs."
        segment_map = {segment.id: segment for segment in segments}
        missing_ids = [segment_id for segment_id in segment_ids if segment_id not in segment_map]
        if missing_ids:
            return "StorySegment id(s) not found: " + ", ".join(missing_ids)
        missing_script_ids = [
            segment_id for segment_id in segment_ids
            if not (segment_map[segment_id].voice_over and segment_map[segment_id].voice_over.script)
        ]
        if missing_script_ids:
            return "Missing voice_over script for segment id(s): " + ", ".join(missing_script_ids)
        generator = VoiceOverGenerator(config)
        try:
            voice_dir = (segment_store.base_dir / session_id / "voice_overs")
            voice_dir.mkdir(parents=True, exist_ok=True)

            semaphore = asyncio.Semaphore(8)

            async def _run(segment_id: str) -> VoiceOver:
                segment = segment_map[segment_id]
                voice = segment.voice_over.voice if segment.voice_over else generator.config.tts_voice
                output_path = voice_dir / f"vo_{segment_id}.wav"
                async with semaphore:
                    return await generator.generate_voice_over_async(
                        segment.voice_over.script,
                        voice=voice,
                        output_path=output_path,
                    )

            results = await asyncio.gather(*[_run(segment_id) for segment_id in segment_ids])
            for segment_id, voice_over in zip(segment_ids, results):
                segment = segment_map[segment_id]
                voice_over.script = segment.voice_over.script
                voice_over.audio_id = segment_id
                segment.voice_over = voice_over
            sanitized_segments = _normalize_segments_for_storage(list(segment_map.values()))
            payload = SegmentUpdatePayload(segments=_segments_to_input(sanitized_segments))
            return (
                f"{payload.model_dump_json()}\n"
                "Message: Call update_story_segments with the full segments payload above."
            )
        finally:
            generator.cleanup()

    @function_tool(failure_error_function=tool_error("match_scene_to_video"), strict_mode=False)
    @log_tool("match_scene_to_video")
    async def match_scene_to_video(payload: SceneMatchRequest) -> str:
        """Find candidate video clips for a story segment using uploaded video context. This tool uses vision capabilities to analyze the candidate videos and produce a list of good matches.

        candidate_video_ids must be video ids from the library catalog; provide up to 5 and
        the model must return only those ids.
        Optional duration_seconds can guide clip length only when no voice over exists for the segment.
        If a voice over exists, its duration takes precedence over duration_seconds. When duration_seconds
        is provided with a voice over, the tool still runs and emits a warning in its response.
        """
        segments = segment_store.load(session_id) or []
        if not segments:
            return "No story segments found. Create story segments before matching scenes."

        segment = next((item for item in segments if item.id == payload.segment_id), None)
        if not segment:
            return f"StorySegment id not found: {payload.segment_id}"
        if not isinstance(segment.content, VideoSegment):
            return f"StorySegment id {payload.segment_id} is not a video_clip. Can only match to a VideoClip."
        if not payload.candidate_video_ids:
            return "No candidate videos provided."
        if len(payload.candidate_video_ids) > 5:
            return "Provide up to 5 candidate video ids."
        if segment.content.keep_original_audio is False:
            if not (segment.voice_over and segment.voice_over.duration) and payload.duration_seconds is None:
                return (
                    "Voice over duration missing for this segment. "
                    "Generate voice overs first for scenes that need them, or provide duration_seconds."
                )

        library = VideoLibrary(config)
        library.scan_library()
        invalid_ids = [
            video_id for video_id in payload.candidate_video_ids
            if not library.get_video(video_id)
        ]
        if invalid_ids:
            return "Video id(s) not found: " + ", ".join(invalid_ids)

        candidate_ids = payload.candidate_video_ids
        client = GeminiClient(config)
        uploaded_files: list[object] = []
        catalog_lines: list[str] = []
        for video_id in candidate_ids:
            metadata = library.get_video(video_id)
            uploaded_files.append(client.get_or_upload_file(metadata.path))
            catalog_lines.append(
                f"- {metadata.id}: {metadata.filename} ({metadata.duration:.1f}s)"
            )

        storyboard_scene = None
        if segment.storyboard_scene_id:
            scenes = storyboard_store.load(session_id) or []
            storyboard_scene = next(
                (scene for scene in scenes if scene.scene_id == segment.storyboard_scene_id),
                None,
            )
        if storyboard_scene and storyboard_scene.use_voice_over:
            if not (segment.voice_over and segment.voice_over.duration) and payload.duration_seconds is None:
                return (
                    "Voice over duration missing for this segment. "
                    "Generate voice overs first for scenes that need them, or provide duration_seconds."
                )

        target_duration = None
        duration_source = None
        if segment.voice_over and segment.voice_over.duration:
            target_duration = segment.voice_over.duration
            duration_source = "voice_over"
        elif payload.duration_seconds is not None:
            target_duration = payload.duration_seconds
            duration_source = "duration_seconds"

        notes_text = f"\nNOTES:\n{payload.notes}\n" if payload.notes else ""
        scene_text = ""
        if storyboard_scene:
            scene_text = (
                f"Scene title: {storyboard_scene.title}\n"
                f"Scene purpose: {storyboard_scene.purpose}\n"
            )
        transcript_text = segment.transcript or "(none)"

        # --- KEY CHANGE: DYNAMIC PROMPT CONSTRUCTION BASED ON AUDIO MODE ---
        if segment.content.keep_original_audio:
            # Case 1: Keeping original audio. We NEED talking heads.
            audio_mode_header = "AUDIO MODE: KEEP ORIGINAL AUDIO"
            visual_constraints = (
                "### VISUAL REQUIREMENT: TALKING HEADS REQUIRED\n"
                "We are keeping the original audio from the video file.\n"
                "1. You MUST select clips where the person is speaking to the camera.\n"
                "2. The lip movements MUST match the transcript provided below.\n"
                "3. Do not select B-roll or wide shots where the speaker is not visible."
            )
        else:
            # Case 2: Voice Over. We MUST AVOID talking heads.
            audio_mode_header = "AUDIO MODE: REPLACE WITH VOICE OVER"
            visual_constraints = (
                "### STRICT VISUAL CONSTRAINT: NO TALKING (B-ROLL ONLY)\n"
                "The original audio will be muted and replaced by a distinct voice-over track.\n"
                "You must strictly AVOID clips where a person is speaking to the camera or where lips are clearly moving.\n"
                "**CRITICAL:** If you select a clip where a person is talking, it will look like a 'bad lip reading' or broken dubbing.\n\n"
                "**PRIORITIZE THESE VISUALS INSTEAD:**\n"
                "1. **Reaction Shots:** People listening, nodding, smiling, or thinking.\n"
                "2. **Action/Body Language:** Gesturing with hands, walking, typing, looking at screens.\n"
                "3. **Wide Shots:** Scenery or groups where individual lip movement is not discernible.\n"
                "4. **Object Shots:** Close-ups of products, screens, or environments.\n"
                "5. **Clean Video:** Ensure there are NO burnt-in subtitles."
            )

        duration_tolerance = "+/- 1s" if target_duration else "+/- 10s"
        duration_section = ""
        if target_duration:
            duration_section = (
                "\nDURATION TARGET:\n"
                f"- Target duration (seconds): {target_duration}\n"
                f"- Source: {duration_source}\n"
                f"- Duration tolerance: {duration_tolerance}\n"
            )

        prompt = f"""You are an expert video asset manager. Your task is to propose a short list of candidate clips for a specific scene in a personalized video.
The main agent will review your candidates and update the story. The agent cannot see the video, so your descriptions must be vivid.

SCENE CONTEXT:
{scene_text}

SEGMENT DETAILS:
- Segment id: {segment.id}
- {audio_mode_header}
- Existing transcript (if any): {transcript_text}
{notes_text}{duration_section}

{visual_constraints}

AVAILABLE CANDIDATE VIDEOS (WITH TRANSCRIPTS):
{chr(10).join(catalog_lines)}

WHAT TO RETURN:
- Return up to 5 candidate clips from the uploaded videos.
- For each candidate include start_timestamp, end_timestamp, description, rationale.
- **RATIONALE REQUIREMENT:** In your rationale, explicitly state how the clip fits the visual constraints (e.g., "Confirmed: Subject is listening, lips are not moving" or "Confirmed: Subject is speaking to camera").
- Use only the video_id values listed in the catalog above; copy them exactly.

EXAMPLE OUTPUT:
{{"candidates":[{{"video_id":"abcd1234","start_timestamp":"02:15","end_timestamp":"02:24","description":"Executive smiling and nodding while looking at a colleague.","rationale":"Perfect B-roll match; subject is engaged but not speaking, fitting the voice-over requirement.","transcript_snippet":"..."}}]}}
"""
        print(prompt)
        # ... (rest of the function remains identical)
        print(SceneMatchResponse.model_json_schema())
        print(config.gemini_model)
        response = await client.client.aio.models.generate_content(
            model=config.gemini_model,
            contents=list(uploaded_files) + [prompt],
            config={
                "response_mime_type": "application/json",
                "response_json_schema": SceneMatchResponse.model_json_schema(),
            },
        )
        print(response.text)
        selection = SceneMatchResponse.model_validate_json(response.text)
        invalid_selected = [
            candidate.video_id
            for candidate in selection.candidates
            if candidate.video_id not in candidate_ids
        ]
        if invalid_selected:
            return "Model selected video_id(s) outside candidate set: " + ", ".join(invalid_selected)
        normalized_candidates = []
        video_durations = {
            metadata.id: metadata.duration
            for metadata in (library.get_video(video_id) for video_id in candidate_ids)
            if metadata
        }
        for candidate in selection.candidates:
            try:
                start_seconds = _parse_timestamp(candidate.start_timestamp)
                end_seconds = _parse_timestamp(candidate.end_timestamp)
            except ValueError as exc:
                return (
                    "Timestamp format error. Expected MM:SS only. "
                    f"Video {candidate.video_id} returned start={candidate.start_timestamp}, "
                    f"end={candidate.end_timestamp}. Error: {exc}"
                )
            duration = video_durations.get(candidate.video_id)
            if duration is not None:
                if start_seconds < 0 or end_seconds <= start_seconds:
                    return (
                        "Timestamp range error. Start must be >= 00:00 and end must be > start. "
                        f"Video {candidate.video_id} returned {candidate.start_timestamp}-{candidate.end_timestamp}."
                    )
                if start_seconds >= duration or end_seconds > duration:
                    return (
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
        response_payload = json.dumps({"candidates": normalized_candidates})
        warning_text = ""
        if payload.duration_seconds is not None and not (segment.voice_over and segment.voice_over.duration):
            warning_text = (
                "Warning: duration_seconds was provided without a voice over; "
                "used it as the target duration for matching.\n"
            )
        return (
            f"{response_payload}\n"
            f"{warning_text}"
            "Message: Review the candidates and confirm which one meets the requirements.Then update the story segment with your chosen clip. "
            "If no clips match the requirements, feel free to update the notes and call this tool again"
        )
    @function_tool(failure_error_function=tool_error("estimate_voice_duration"), strict_mode=False)
    @log_tool("estimate_voice_duration")
    def estimate_voice_duration(
        text: str,
        words_per_minute: float = 150,
    ) -> float:
        """Estimate speech duration for a script."""
        return estimate_speech_duration(text, words_per_minute)

    @function_tool(failure_error_function=tool_error("attach_final_render_for_review"), strict_mode=False)
    @log_tool("attach_final_render_for_review")
    def attach_final_render_for_review(output_path: Optional[str] = None) -> str:
        """Upload the latest final render so the next model turn can review it."""
        step_start = time.perf_counter()
        print("[review] start attach_final_render_for_review")
        if set_review_context is None:
            print(f"[review] finish attach_final_render_for_review in {time.perf_counter() - step_start:.2f}s")
            return "Review attachment is not available in this environment."
        t0 = time.perf_counter()
        segments = segment_store.load(session_id) or []
        print(f"[review] load segments in {time.perf_counter() - t0:.2f}s")
        if not segments:
            print(f"[review] finish attach_final_render_for_review in {time.perf_counter() - step_start:.2f}s")
            return "No story segments found. Create segments before rendering."

        t0 = time.perf_counter()
        segments_path = segment_store._segments_path(session_id)
        segments_mtime = None
        try:
            if segments_path.exists():
                segments_mtime = segments_path.stat().st_mtime
        except OSError:
            segments_mtime = None
        print(f"[review] check segments mtime in {time.perf_counter() - t0:.2f}s")

        t0 = time.perf_counter()
        render_path = _resolve_render_target(config, session_id, output_path)
        needs_render = True
        if render_path and render_path.exists() and segments_mtime is not None:
            try:
                needs_render = segments_mtime > render_path.stat().st_mtime
            except OSError:
                needs_render = True
        elif render_path and render_path.exists():
            needs_render = False
        print(f"[review] resolve render target in {time.perf_counter() - t0:.2f}s")

        if needs_render:
            t0 = time.perf_counter()
            missing_sources = [
                segment.id
                for segment in segments
                if isinstance(segment.content, VideoSegment)
                and not segment.content.source_video_id
            ]
            print(f"[review] check missing sources in {time.perf_counter() - t0:.2f}s")
            if missing_sources:
                print(f"[review] finish attach_final_render_for_review in {time.perf_counter() - step_start:.2f}s")
                return (
                    "Missing source_video_id for segments: "
                    + ", ".join(missing_sources)
                )
            t0 = time.perf_counter()
            library = VideoLibrary(config)
            library.scan_library()
            hydrated = [segment.model_copy(deep=True) for segment in segments]
            hydrated = _hydrate_segments(hydrated, library)
            print(f"[review] hydrate segments in {time.perf_counter() - t0:.2f}s")
            t0 = time.perf_counter()
            editor = VideoEditor(config)
            try:
                result = editor.render_segments(
                    hydrated,
                    output_filename=_sanitize_output_filename(render_path.name),
                    voice_over_paths=_build_voice_over_paths(
                        hydrated,
                        session_id,
                        segment_store.base_dir,
                    ),
                )
                if not result.success:
                    print(f"[review] render failed in {time.perf_counter() - t0:.2f}s")
                    print(f"[review] finish attach_final_render_for_review in {time.perf_counter() - step_start:.2f}s")
                    return f"Render failed: {result.error_message or 'unknown error'}"
                render_path = result.output_path or render_path
            finally:
                editor.cleanup()
            print(f"[review] render segments in {time.perf_counter() - t0:.2f}s")

        t0 = time.perf_counter()
        client = GeminiClient(config)
        uploaded = client.get_or_upload_file(render_path)
        print(f"[review] upload render in {time.perf_counter() - t0:.2f}s")
        t0 = time.perf_counter()
        set_review_context(session_id, uploaded, render_path)
        print(f"[review] set review context in {time.perf_counter() - t0:.2f}s")
        print(f"[review] finish attach_final_render_for_review in {time.perf_counter() - step_start:.2f}s")
        status = "Re-rendered" if needs_render else "Attached"
        return (
            f"{status} {render_path.name} for the next turn. "
            "The rendered video will be available in your context for the next turn for review."
        )

    return [
        update_storyboard,
        update_customer_details,
        update_story_segments,
        match_scene_to_video,
        generate_voice_overs,
        estimate_voice_duration,
        attach_final_render_for_review,
    ]


def _resolve_video_segment(segment: VideoSegment, config: Config) -> VideoSegment:
    if not segment.source_video_id:
        raise ValueError(
            "Video source not provided. Provide source_video_id."
        )
    library = VideoLibrary(config)
    metadata = library.get_video(segment.source_video_id)
    if not metadata:
        raise ValueError(
            "Video path not found for source_video_id "
            f"{segment.source_video_id}. Provide source_video_id or scan library."
        )
    return segment


def _resolve_story_segment(segment: StorySegment, config: Config) -> StorySegment:
    if isinstance(segment.content, VideoSegment):
        segment.content = _resolve_video_segment(segment.content, config)
    return segment


def _parse_json_model(model_type, payload: str):
    try:
        return model_type.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid JSON for {model_type.__name__}: {exc}") from exc


def _parse_json_segments(payload: str) -> list[StorySegment]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for StorySegment list: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of StorySegment objects.")
    return [StorySegment.model_validate(item) for item in data]


def _sanitize_output_filename(filename: str) -> str:
    if not filename:
        return "output.mp4"
    path = Path(filename)
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        return filename
    return f"{path.stem}.mp4"


def _input_segments_to_model(segments: list[StorySegmentInput]) -> list[StorySegment]:
    return [
        StorySegment.model_validate(segment.model_dump(exclude_none=True))
        for segment in segments
    ]


def _segments_to_input(segments: list[StorySegment]) -> list[StorySegmentInput]:
    sanitized: list[StorySegmentInput] = []
    for segment in segments:
        payload = segment.model_dump(
            exclude_none=True,
            exclude={
                "content": {"source_path"},
                "voice_over": {"audio_path"},
            },
        )
        sanitized.append(StorySegmentInput.model_validate(payload))
    return sanitized


def _sanitize_segments_for_prompt(segments: list[StorySegment]) -> list[StorySegment]:
    sanitized: list[StorySegment] = []
    for segment in segments:
        copied = segment.model_copy(deep=True)
        if copied.voice_over:
            pass
        sanitized.append(copied)
    return sanitized


def _normalize_segments_for_storage(segments: list[StorySegment]) -> list[StorySegment]:
    normalized: list[StorySegment] = []
    for segment in segments:
        normalized.append(segment)
    return normalized


def _voice_over_path_for_id(
    session_id: str,
    base_dir: Path,
    audio_id: str,
) -> Path:
    return base_dir / session_id / "voice_overs" / f"vo_{audio_id}.wav"


def _get_voice_over_path(
    segment: StorySegment,
    session_id: str,
    base_dir: Path,
) -> Optional[Path]:
    voice_over = segment.voice_over
    if not voice_over or not voice_over.audio_id:
        return None
    candidate = _voice_over_path_for_id(session_id, base_dir, voice_over.audio_id)
    if candidate.exists():
        return candidate
    return None


def _build_voice_over_paths(
    segments: list[StorySegment],
    session_id: str,
    base_dir: Path,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for segment in segments:
        audio_path = _get_voice_over_path(segment, session_id, base_dir)
        if audio_path:
            paths[segment.id] = audio_path
    return paths


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


def _preview_dir(session_id: str, config: Config) -> Path:
    base = config.output_dir / "streamlit_previews" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def _preview_path_for_segment(
    segment: StorySegment,
    session_id: str,
    config: Config,
    base_dir: Path,
) -> Optional[Path]:
    if segment.segment_type != SegmentType.VIDEO_CLIP:
        return None
    content = segment.content
    token = f"{segment.id}_{int(content.start_time * 1000)}_{int(content.end_time * 1000)}"
    voice_token = ""
    audio_path = _get_voice_over_path(segment, session_id, base_dir)
    if audio_path:
        try:
            voice_token = f"_vo_{int(audio_path.stat().st_mtime)}"
        except (OSError, ValueError):
            voice_token = ""
    return _preview_dir(session_id, config) / f"preview_{token}{voice_token}.mp4"


def _render_segment_previews(
    segments: list[StorySegment],
    session_id: str,
    config: Config,
    base_dir: Path,
) -> None:
    if not segments:
        return
    library = VideoLibrary(config)
    library.scan_library()
    editor = VideoEditor(config)
    try:
        for segment in segments:
            if segment.segment_type != SegmentType.VIDEO_CLIP:
                continue
            content = segment.content
            if not content.source_video_id:
                continue
            metadata = library.get_video(content.source_video_id)
            if not metadata or not metadata.path.exists():
                continue
            output_path = _preview_path_for_segment(segment, session_id, config, base_dir)
            if output_path is None or output_path.exists():
                continue
            try:
                audio_path = _get_voice_over_path(segment, session_id, base_dir)
                if audio_path and audio_path.exists():
                    rendered = editor.render_segment(
                        segment,
                        normalize=False,
                        voice_over_path=audio_path,
                    )
                    shutil.copy(rendered, output_path)
                else:
                    editor.cut_video_segment(content, output_path=output_path)
            except Exception:
                try:
                    if output_path.exists():
                        output_path.unlink()
                except OSError:
                    pass
                continue
    finally:
        editor.cleanup()


def _hydrate_segments(segments: list[StorySegment], library: VideoLibrary) -> list[StorySegment]:
    for segment in segments:
        content = segment.content
        if hasattr(content, "source_video_id") and content.source_video_id:
            metadata = library.get_video(content.source_video_id)
            if not metadata:
                raise ValueError(
                    "Video path not found for source_video_id "
                    f"{content.source_video_id}. Provide source_video_id or scan library."
                )
    return segments


class VideoAgentService:
    def __init__(self, config: Optional[Config] = None, base_dir: Optional[Path] = None):
        self.config = config or default_config
        self.base_dir = base_dir or (Path.cwd() / "output" / "agent_sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.segment_store = SegmentStore(self.base_dir)
        self.storyboard_store = StoryboardStore(self.base_dir)
        self.customer_store = CustomerStore(self.base_dir)
        self.event_store = EventStore(self.base_dir)
        self.session_db_path = self.base_dir / "agent_memory.db"
        self._agents: dict[str, Agent] = {}
        self._agent_lock = Lock()
        self._run_lock = Lock()
        self._render_lock = Lock()
        self._render_executor = ThreadPoolExecutor(max_workers=1)
        self._render_futures: dict[str, object] = {}
        self._review_context: dict[str, dict[str, object]] = {}
        _load_env()
        self._configure_tracing()
        self._base_instructions = """
You are a collaborative video editing agent helping a user iteratively build a personalized
video for a specific customer. Work with the user step by step. You do not execute the full
pipeline alone; you propose, ask, and adjust based on user feedback each turn.

When you change the storyboard, customer details, or segments, persist the full updated data
using the corresponding update tool before replying.

### Workflow and responsibilities
1) Storyboard generation
   - A storyboard is a high-level plan: titles, purposes, scripts, and whether to generate
     voice over (`use_voice_over`).
   - Update with `update_storyboard`.
   - Don't move from this stage until the user is happy with story board.

2) Video matching
   - Story segments are the production plan: each segment is a `video_clip` and must include
     `storyboard_scene_id`. Using existing video clips makes the video pleasant.
   - Create the full StorySegments list and call `update_story_segments`.
   - Do not set `source_path` or `audio_path` in segments. Use `source_video_id` and `audio_id` only.
   - After segments are saved, call `generate_voice_overs` with the list of segment ids
     that need voice over audio. This returns an updated segments payload; call
     `update_story_segments` with it. This determines the clip durations for matching.
   - For `video_clip` segments, scan transcripts to shortlist up to 5 candidate video ids for each segment. Make sure to short list enough candidates to give the tool enough content to find good matching scenes.
     then call `match_scene_to_video` with the segment id, candidate ids, optional notes,
     and optional `duration_seconds` (only used when there is no voice over; ignored if a voice
     over exists). You should rely on `match_scene_to_video` heavily as this tool can view the video scenes and find visually pleasing matches.
     Review the returned candidates and update the segments yourself with the chosen clip. You need to rewrite the entire segments to avoid using previous segments.
     For scenes with voice over, make sure to tell the tool to avoid scenes with people speaking or visible subtitles as this won't look good when there is no lip sync and the existing video subtitles don't match the voice over.
     For customer testimony scenes, make sure to prompt for a long enough duration (30s is a good start). Find a clean clip that has enough content to look genuine and build the connection with the customer. Also make sure to introduce the voice over in previous scene with relevant details about what company you are showing and who is talking
    The user can only see the final clips you use in the updated segments. They cannot see the candidates you selected.
     To make the process more efficient, you can match all the scenes by making multiple tool calls in parallel.
   
3) Review
   - When the plan is ready, the user renders the final video.
   - To review the final render, call `attach_final_render_for_review`.
   - This tool will re-render automatically if the output is stale, then upload the latest video into your context so you can use vision to review it.
   - The uploaded video is only available to you for the very next turn; it is cleared after that.
   - Review voice-over/scene coherence end-to-end; flag any mismatches or visuals that do not fit the narration.
        - common elements you need to watch out for during the review that need to get fixed:
            - A person speaking in the scene when there is a voice over. The person lip movements will be completely off compared to the voice over.
            - A scene that has subtitles from the original video when there is a voice over.The voice over likely does not match those subtitle.
            - The customer testimony video has a voice over making the video sound fake or made up.
            - The customer testimony is abruptly cut at the end or started from an awkward timestamp.
   - If anything looks wrong, tell the user what you want to change and get their approval before updating segments.

Return a short, helpful plain-text response each turn. Always suggest the best next step to the customer.

The user sees a UI with 3 stages: Storyboard (customer details + storyboard), Video Matching
(turn storyboard into story segments with footage), and Rendering (final export). You have
access to everything the user sees on the UI; use your tools to update the UI as you see fit.

Make use of the UI to display elements to the user; avoid spamming the chat with long elements
when the custom UI can present them.
"""

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

    def _get_agent(self, session_id: str, context_payload: dict) -> Agent:
        with self._agent_lock:
            agent = self._agents.get(session_id)
            if agent:
                agent.instructions = self._build_instructions(context_payload)
                return agent

            model_name = _select_model_name(self.config)
            self.model_name = model_name
            api_key = _select_api_key(self.config, model_name)
            model = LitellmModel(model=model_name, api_key=api_key)
            tools = _build_tools(
                self.config,
                self.segment_store,
                self.storyboard_store,
                self.customer_store,
                self.event_store,
                self.schedule_auto_render,
                self._set_review_context,
                session_id,
            )
            agent = Agent(
                name="VideoAgent",
                instructions=self._build_instructions(context_payload),
                tools=tools,
                model=model,
                model_settings=ModelSettings(include_usage=True,)
            )
            self._agents[session_id] = agent
            return agent

    def create_session(self) -> str:
        return uuid4().hex

    def get_segments(self, session_id: str) -> Optional[list[StorySegment]]:
        return self.segment_store.load(session_id)

    def save_segments(self, session_id: str, segments: list[StorySegment]) -> None:
        normalized = _normalize_segments_for_storage(segments)
        self.segment_store.save(session_id, normalized)

    def get_storyboard(self, session_id: str) -> Optional[list[_StoryboardScene]]:
        return self.storyboard_store.load(session_id)

    def save_storyboard(self, session_id: str, scenes: list[_StoryboardScene]) -> None:
        self.storyboard_store.save(session_id, scenes)

    def get_customer_details(self, session_id: str) -> Optional[str]:
        return self.customer_store.load(session_id)

    def save_customer_details(self, session_id: str, details: str) -> None:
        self.customer_store.save(session_id, details)

    def _set_review_context(
        self,
        session_id: str,
        file_obj: object,
        render_path: Path,
    ) -> None:
        self._review_context[session_id] = {
            "file": file_obj,
            "path": render_path,
        }

    def _pop_review_context(self, session_id: str) -> Optional[dict[str, object]]:
        return self._review_context.pop(session_id, None)

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

    def run_turn(self, session_id: str, user_message: str) -> str:
        current_segments = self.segment_store.load(session_id)
        sanitized_segments = None
        if current_segments:
            sanitized_segments = _sanitize_segments_for_prompt(current_segments)
        storyboard_scenes = self.storyboard_store.load(session_id)
        customer_details = self.customer_store.load(session_id)
        payload = {
            "storyboard_scenes": [
                scene.model_dump(mode="json")
                for scene in storyboard_scenes
            ] if storyboard_scenes else None,
            "customer_details": customer_details,
            "video_transcripts": self._build_video_transcripts(),
            "current_segments": [
                segment.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude={
                        "content": {"source_path"},
                        "voice_over": {"audio_path"},
                    },
                )
                for segment in sanitized_segments
            ] if sanitized_segments else None,
        }
        agent = self._get_agent(session_id, payload)

        session = SQLiteSession(session_id, str(self.session_db_path))
        ui_update_tools = {
            "update_story_segments",
            "update_storyboard",
            "update_customer_details",
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
        try:
            review_context = self._pop_review_context(session_id)
            include_video = review_context is not None
            input_payload = user_message
            if include_video:
                review_hint = (
                    "You have access to the final rendered video attached. "
                    "Review it end-to-end and flag any scene/voice mismatches, "
                    "awkward cuts, or visuals that do not match the narrative."
                )
                input_payload = [review_context["file"], review_hint, user_message]
            session_for_run = None if include_video else session
            if session_for_run is None:
                result = Runner.run_sync(
                    agent,
                    input=input_payload,
                    session=None,
                    max_turns=100,
                    run_config=run_config,
                )
            else:
                with self._run_lock:
                    result = Runner.run_sync(
                        agent,
                        input=input_payload,
                        session=session_for_run,
                        max_turns=100,
                        run_config=run_config,
                    )
            output = result.final_output
            if not isinstance(output, str):
                output = str(output)
            return output
        finally:
            self.event_store.append(session_id, {"type": "run_end"})

    def get_events(self, session_id: str, cursor: Optional[int]) -> tuple[list[dict], int]:
        return self.event_store.read_since(session_id, cursor)

    def render_segments(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        current_segments = self.segment_store.load(session_id)
        if not current_segments:
            raise ValueError("No story segments found for this session.")
        library = VideoLibrary(self.config)
        library.scan_library()
        editor = VideoEditor(self.config)
        try:
            hydrated = _hydrate_segments(current_segments, library)
            voice_over_paths = _build_voice_over_paths(
                hydrated,
                session_id,
                self.segment_store.base_dir,
            )
            result = editor.render_segments(
                hydrated,
                output_filename=_sanitize_output_filename(output_filename),
                voice_over_paths=voice_over_paths,
            )
            return result
        finally:
            editor.cleanup()

    def schedule_auto_render(self, session_id: str) -> None:
        with self._render_lock:
            existing = self._render_futures.get(session_id)
            if existing and getattr(existing, "done", lambda: True)() is False:
                return

            output_filename = f"{session_id}_auto.mp4"

            def _run() -> RenderResult:
                self.event_store.append(session_id, {"type": "auto_render_start"})
                try:
                    segments = self.segment_store.load(session_id) or []
                    missing_sources = [
                        segment.id
                        for segment in segments
                        if isinstance(segment.content, VideoSegment)
                        and not segment.content.source_video_id
                    ]
                    if missing_sources:
                        self.event_store.append(
                            session_id,
                            {
                                "type": "auto_render_skipped",
                                "status": "error",
                                "error": "Missing source_video_id for segments: "
                                + ", ".join(missing_sources),
                            },
                        )
                        return RenderResult(
                            success=False,
                            error_message="Missing source for one or more segments.",
                        )
                    library = VideoLibrary(self.config)
                    library.scan_library()
                    hydrated = [segment.model_copy(deep=True) for segment in segments]
                    hydrated = _hydrate_segments(hydrated, library)
                    _render_segment_previews(
                        hydrated,
                        session_id,
                        self.config,
                        self.segment_store.base_dir,
                    )
                    editor = VideoEditor(self.config)
                    try:
                        result = editor.render_segments(
                            hydrated,
                            output_filename=_sanitize_output_filename(output_filename),
                            voice_over_paths=_build_voice_over_paths(
                                hydrated,
                                session_id,
                                self.segment_store.base_dir,
                            ),
                        )
                    finally:
                        editor.cleanup()
                    self.event_store.append(
                        session_id,
                        {"type": "auto_render_end", "status": "ok", "output": str(result.output_path) if result.output_path else None},
                    )
                    return result
                except Exception as exc:
                    self.event_store.append(
                        session_id,
                        {"type": "auto_render_end", "status": "error", "error": str(exc)},
                    )
                    raise

            self._render_futures[session_id] = self._render_executor.submit(_run)

    def generate_storyboard(self, session_id: str, brief: str) -> list[_StoryboardScene]:
        """Calls the generator directly for a text-only draft, bypassing TTS and Video matching."""
        generator = PersonalizedStoryGenerator(self.config)
        scenes = generator.plan_storyboard(brief)
        self.storyboard_store.save(session_id, scenes)
        self.segment_store.clear(session_id)
        if brief:
            self.customer_store.save(session_id, brief)
        return scenes

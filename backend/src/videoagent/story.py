"""
Story Generator - Personalized video creation from customer situation.

Flow:
1. LLM builds a storyboard with voice over scripts grounded in the footage.
2. Generate voice over audio to measure durations.
3. LLM selects timestamped clips that fit the voice over lengths.
4. Assemble StorySegments (video clips only).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from videoagent.config import Config, default_config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.models import (
    SegmentType,
    StorySegment,
    VideoSegment,
    VoiceOver,
)
from videoagent.voice import VoiceOverGenerator


class _MatchedScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_type: SegmentType = Field(
        default=SegmentType.VIDEO_CLIP,
        description="Segment type (defaults to video_clip).",
    )
    source_video_id: str = Field(
        description="12-hex video id for the selected clip.",
    )
    start_time: float = Field(
        description="Clip start time in seconds.",
    )
    end_time: float = Field(
        description="Clip end time in seconds.",
    )
    description: str = Field(
        description="Description for the selected clip.",
    )
    keep_original_audio: bool = Field(
        description="Audio flag for the selected clip.",
    )


class SceneCandidate(BaseModel):
    """A candidate video clip for a storyboard scene."""

    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(
        default_factory=lambda: f"cand_{uuid.uuid4().hex[:8]}",
        description="Unique identifier for this candidate.",
    )
    source_video_id: str = Field(
        description="12-hex video id from the library.",
    )
    start_time: float = Field(
        description="Clip start time in seconds.",
    )
    end_time: float = Field(
        description="Clip end time in seconds.",
    )
    description: str = Field(
        default="",
        description="Visual description of the clip.",
    )
    rationale: str = Field(
        default="",
        description="Why this clip fits the scene.",
    )
    keep_original_audio: bool = Field(
        default=False,
        description="Whether to keep original audio.",
    )
    last_rank: int = Field(
        default=1,
        description="Most recent rank from matching (1 = best).",
    )
    shortlisted: bool = Field(
        default=True,
        description="Whether this candidate is in the active shortlist.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO timestamp when candidate was created.",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO timestamp when candidate was last updated.",
    )


class SelectionHistoryEntry(BaseModel):
    """Record of a candidate selection change."""

    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(
        default_factory=lambda: f"hist_{uuid.uuid4().hex[:8]}",
        description="Unique identifier for this history entry.",
    )
    candidate_id: str = Field(
        description="The candidate that was previously selected.",
    )
    changed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO timestamp when selection changed.",
    )
    changed_by: str = Field(
        default="user",
        description="Who made the change: 'user' or 'agent'.",
    )
    reason: str = Field(
        default="",
        description="Optional reason for the selection change.",
    )


class _StoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:8],
        description="Unique id for mapping voice overs and clips.",
    )
    title: str = Field(min_length=1, description="Short scene title.")
    purpose: str = Field(min_length=1, description="Narrative goal for the scene.")
    script: str = Field(
        min_length=1,
        description="Voice over script grounded in the available content.",
    )
    use_voice_over: bool = Field(
        default=True,
        description=(
            "If true, generate a voice over for this scene. If false, use the original "
            "scene audio and do not generate a voice over."
        ),
    )
    voice_over: Optional[VoiceOver] = Field(
        default=None,
        description="Optional generated voice over metadata before matching.",
    )
    matched_scene: Optional[_MatchedScene] = Field(
        default=None,
        description="Matched clip and audio metadata for this scene.",
    )
    order: Optional[int] = Field(
        default=None,
        description="Optional ordering index for the scene.",
    )
    # Multi-candidate support
    matched_scene_candidates: list[SceneCandidate] = Field(
        default_factory=list,
        description="Ranked list of candidate clips for this scene.",
    )
    selected_candidate_id: Optional[str] = Field(
        default=None,
        description="ID of the currently selected candidate.",
    )
    matched_scene_history: list[SelectionHistoryEntry] = Field(
        default_factory=list,
        description="History of selection changes for this scene.",
    )
    animation: Optional[str] = Field(
        default=None,
        description="Optional HTML/CSS/JS animation code (e.g. GSAP) to overlay on the video.",
    )

    @model_validator(mode="after")
    def _enforce_invariants(self) -> "_StoryboardScene":
        """Enforce shortlist cap, history cap, and matched_scene sync."""
        # Cap shortlist at 5
        shortlisted = [c for c in self.matched_scene_candidates if c.shortlisted]
        if len(shortlisted) > 5:
            shortlisted.sort(key=lambda c: c.last_rank)
            for c in shortlisted[5:]:
                c.shortlisted = False

        # Cap history at 20
        if len(self.matched_scene_history) > 20:
            self.matched_scene_history = self.matched_scene_history[-20:]

        # Sync matched_scene from selected candidate
        if self.selected_candidate_id and self.matched_scene_candidates:
            selected = next(
                (c for c in self.matched_scene_candidates
                 if c.candidate_id == self.selected_candidate_id),
                None
            )
            if selected:
                self.matched_scene = _MatchedScene(
                    source_video_id=selected.source_video_id,
                    start_time=selected.start_time,
                    end_time=selected.end_time,
                    description=selected.description,
                    keep_original_audio=selected.keep_original_audio,
                )

        return self


class _SceneClip(BaseModel):
    scene_id: str = Field(min_length=1)
    video_id: str = Field(
        min_length=1,
        description="12-hex video id from the available videos.",
    )
    start: float = Field(description="Start time in seconds.")
    end: float = Field(description="End time in seconds.")
    description: str = Field(min_length=1, description="Short clip description.")
    rationale: str = Field(min_length=1, description="Why this clip fits.")

    @model_validator(mode="after")
    def _validate_timing(self) -> "_SceneClip":
        if self.end <= self.start:
            raise ValueError("Clip end time must be greater than start time.")
        return self


class _ClipPlan(BaseModel):
    clips: list[_SceneClip] = Field(min_length=1)


class PersonalizedStoryGenerator:
    """
    Generates a personalized video story from a customer situation.

    Output is a list of StorySegments (video clips only) in storyboard order.
    """

    def __init__(self, config: Optional[Config] = None, company_id: Optional[str] = None):
        self.config = config or default_config
        self.company_id = company_id
        self.client = GeminiClient(self.config)
        self.library = VideoLibrary(self.config, company_id=company_id)
        self.voice_generator = VoiceOverGenerator(self.config)

    def _get_videos_transcripts(self, video_ids: Optional[list[str]] = None) -> str:
        """Get a full summary of selected videos and their transcripts."""
        videos = self.library.list_videos()
        if video_ids is not None:
            selected = []
            for video_id in video_ids:
                video = self.library.get_video(video_id)
                if video:
                    selected.append(video)
            videos = selected
        lines = []

        for video in videos:
            preview = video.get_full_transcript()
            if not preview:
                preview = "(no transcript)"
            lines.append(
                f"- {video.id}: {video.filename} ({video.duration:.1f}s) - {preview}"
            )

        return "\n".join(lines)

    def _format_video_catalog(self, video_ids: list[str]) -> str:
        lines = []
        for video_id in video_ids:
            video = self._resolve_video(video_id)
            lines.append(
                f"- {video.id}: {video.filename} ({video.duration:.1f}s)"
            )
        return "\n".join(lines)

    def _validate_clip_plan(self, clip_plan: _ClipPlan, allowed_video_ids: set[str]) -> None:
        invalid_ids = [
            clip.video_id for clip in clip_plan.clips
            if clip.video_id not in allowed_video_ids
        ]
        if invalid_ids:
            raise ValueError(
                "Clip plan returned video ids outside the allowed set: "
                + ", ".join(sorted(set(invalid_ids)))
            )

    def _format_storyboard(self, scenes: list[_StoryboardScene]) -> str:
        lines = []
        for scene in scenes:
            lines.append(
                "- "
                f"{scene.scene_id}: {scene.title}. "
                f"Purpose: {scene.purpose}. "
                f"Voice over: {scene.script}"
            )
        return "\n".join(lines)

    def _format_voice_overs(
        self,
        scenes: list[_StoryboardScene],
        voice_overs: dict[str, VoiceOver],
    ) -> str:
        lines = []
        for scene in scenes:
            voice_over = voice_overs.get(scene.scene_id)
            if not voice_over:
                continue
            lines.append(
                f"- {scene.scene_id}: {voice_over.script}"
            )
        return "\n".join(lines)

    def _plan_storyboard(
        self,
        customer_situation: str,
        videos_transcripts: str,
    ) -> list[_StoryboardScene]:
        """Ask the LLM for a storyboard plan in structured output."""
        prompt = f"""You are a senior video editor creating a short, personalized sales video.
Take a deep breath and think for a long time before answering. 

CUSTOMER SITUATION:
{customer_situation}

AVAILABLE VIDEOS AND DIALOG (TRANSCRIPTS WITH TIMESTAMPS):
{videos_transcripts}

Create an ordered storyboard based only on the available footage and dialog.
Write the voice over scripts now, grounded in the transcripts above.
Do NOT pick specific clips or timestamps yet.
Return a JSON array of storyboard scenes that matches the provided schema.
"""

        schema = TypeAdapter(list[_StoryboardScene]).json_schema()
        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )

        return TypeAdapter(list[_StoryboardScene]).validate_json(response.text)

    async def _generate_voice_overs(self, scripts: list[str]) -> list[VoiceOver]:
        if not scripts:
            return []

        pairs = [(script, self.config.tts_voice) for script in scripts]

        return await self.voice_generator.generate_voice_overs_parallel(
            pairs,
            max_concurrency=min(4, len(pairs)),
        )

    def _select_clips(
        self,
        customer_situation: str,
        scenes: list[_StoryboardScene],
        voice_overs: dict[str, VoiceOver],
        video_catalog: str,
        uploaded_files: list[object],
    ) -> _ClipPlan:
        """Ask the LLM to select timestamped clips for each scene."""
        storyboard_text = self._format_storyboard(scenes)
        voice_over_text = self._format_voice_overs(scenes, voice_overs)

        prompt = f"""You are a senior video editor selecting exact clips from a library.
Take a deep breath and think for a long time before answering. Do not reveal your reasoning.

PREVIOUS CONTEXT:
Customer situation: {customer_situation}
Storyboard with voice overs:
{storyboard_text}

Voice overs with target durations:
{voice_over_text}

NEW USER PROMPT:
Based on the context above and the available videos and dialog, select the best
matching clip for each scene and return the exact timestamps.

PROVIDED VIDEO CATALOG:
{video_catalog}

When referring to moments, use MM:SS (or H:MM:SS) format.
Select one clip per scene using real 12-hex video ids.
Make sure the scene is a great background for the voiceover.
For example, if the scene is about a specific feature, make sure to find a scene representing that feature.
Start/end must be in seconds and within the video duration.
Make each clip duration as close as possible to the voice over duration
(prefer within +/- 1.0s when feasible).
"""

        contents = list(uploaded_files) + [prompt]
        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": _ClipPlan.model_json_schema(),
            },
        )

        return _ClipPlan.model_validate_json(response.text)

    def _normalize_times(
        self,
        video_duration: float,
        start: float,
        end: float,
        max_seconds: Optional[float] = None,
    ) -> tuple[float, float]:
        start = max(0.0, min(start, video_duration))
        if max_seconds is not None:
            end = min(end, start + max_seconds)
        end = min(end, video_duration)
        return start, end

    def plan_storyboard(self, customer_situation: str) -> list[_StoryboardScene]:
        """Just the planning phase: LLM generates scenes and scripts based on transcripts."""
        self.library.scan_library()
        videos_summary = self._get_videos_transcripts()
        return self._plan_storyboard(customer_situation, videos_summary)

    def _resolve_video(self, video_id: Optional[str]):
        video = self.library.get_video(video_id) if video_id else None
        if not video:
            raise ValueError(f"Video not found for id: {video_id}")
        return video

    async def generate_story(self, customer_situation: str) -> list[StorySegment]:
        """Backward-compatible name that returns a list of segments."""
        return await self.generate_segments(customer_situation)
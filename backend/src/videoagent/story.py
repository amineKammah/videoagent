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
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class _StoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(
        min_length=1,
        description="Unique id like 'scene_1' used to map voice overs and clips.",
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


class _StoryboardPlan(BaseModel):
    scenes: list[_StoryboardScene] = Field(min_length=1)
    top_video_ids: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Top video ids to use for scene selection (max 10).",
    )


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

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self.client = GeminiClient(self.config)
        self.library = VideoLibrary(self.config)
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

    def _normalize_top_video_ids(self, video_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for video_id in video_ids:
            if video_id in seen:
                continue
            if self.library.get_video(video_id):
                ordered.append(video_id)
                seen.add(video_id)
            if len(ordered) >= 10:
                break
        if not ordered:
            raise ValueError("No valid top_video_ids returned by storyboard.")
        return ordered

    def _upload_videos(self, video_ids: list[str]) -> list[object]:
        uploads: list[object] = []
        for video_id in video_ids:
            video = self._resolve_video(video_id)
            uploads.append(self.client.get_or_upload_file(video.path))
        return uploads

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
    ) -> _StoryboardPlan:
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
Also return top_video_ids: the 10 most relevant video ids (or fewer if fewer exist),
which will be used for detailed scene selection.
Return a JSON object that matches the provided schema.
"""

        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": _StoryboardPlan.model_json_schema(),
            },
        )

        return _StoryboardPlan.model_validate_json(response.text)

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
        storyboard: _StoryboardPlan,
        voice_overs: dict[str, VoiceOver],
        video_catalog: str,
        uploaded_files: list[object],
    ) -> _ClipPlan:
        """Ask the LLM to select timestamped clips for each scene."""
        storyboard_text = self._format_storyboard(storyboard.scenes)
        voice_over_text = self._format_voice_overs(storyboard.scenes, voice_overs)

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
        plan = self._plan_storyboard(customer_situation, videos_summary)
        return plan.scenes

    def _resolve_video(self, video_id: Optional[str]):
        video = self.library.get_video(video_id) if video_id else None
        if not video:
            raise ValueError(f"Video not found for id: {video_id}")
        return video

    async def generate_segments(self, customer_situation: str) -> list[StorySegment]:
        """Generate a list of StorySegments following the storyboard pipeline."""
        step_start = time.perf_counter()
        print("Story: scanning video library...")
        self.library.scan_library()
        print(f"Story: scan completed in {time.perf_counter() - step_start:.2f}s")

        step_start = time.perf_counter()
        print("Story: collecting transcripts...")
        videos_summary = self._get_videos_transcripts()
        print(f"Story: transcripts collected in {time.perf_counter() - step_start:.2f}s")

        step_start = time.perf_counter()
        print("Story: planning storyboard + voice overs...")
        storyboard = self._plan_storyboard(customer_situation, videos_summary)
        print(f"Story: storyboard planned in {time.perf_counter() - step_start:.2f}s")

        selected_video_ids = self._normalize_top_video_ids(storyboard.top_video_ids)
        print(f"Story: using {len(selected_video_ids)} videos for clip selection")

        scripts: list[str] = []
        for scene in storyboard.scenes:
            script = scene.script or f"{scene.title}. {scene.purpose}"
            scripts.append(script)

        step_start = time.perf_counter()
        print("Story: generating voice over audio...")
        voice_overs_list = await self._generate_voice_overs(scripts)
        print(f"Story: voice overs generated in {time.perf_counter() - step_start:.2f}s")
        voice_overs_by_scene = {
            scene.scene_id: voice_over
            for scene, voice_over in zip(storyboard.scenes, voice_overs_list)
        }

        step_start = time.perf_counter()
        print("Story: uploading selected videos...")
        uploaded_files = self._upload_videos(selected_video_ids)
        print(f"Story: video uploads completed in {time.perf_counter() - step_start:.2f}s")

        step_start = time.perf_counter()
        print("Story: building video catalog...")
        video_catalog = self._format_video_catalog(selected_video_ids)
        print(f"Story: video catalog built in {time.perf_counter() - step_start:.2f}s")

        step_start = time.perf_counter()
        print("Story: selecting clips...")
        clip_plan = self._select_clips(
            customer_situation,
            storyboard,
            voice_overs_by_scene,
            video_catalog,
            uploaded_files,
        )
        self._validate_clip_plan(clip_plan, set(selected_video_ids))
        clip_map = {clip.scene_id: clip for clip in clip_plan.clips}
        print(f"Story: clips selected in {time.perf_counter() - step_start:.2f}s")

        step_start = time.perf_counter()
        print("Story: assembling segments...")
        segments: list[StorySegment] = []
        for index, scene in enumerate(storyboard.scenes):
            voice_over = voice_overs_by_scene.get(scene.scene_id)
            clip = clip_map.get(scene.scene_id)

            target_duration = None
            if voice_over:
                target_duration = voice_over.duration

            if not clip:
                raise ValueError(f"Missing clip selection for scene: {scene.scene_id}")

            video = self._resolve_video(clip.video_id)
            start = clip.start
            end = clip.end
            description = clip.description

            if end <= start:
                raise ValueError(
                    f"Invalid clip timing for scene {scene.scene_id}: {start}-{end}"
                )

            start, end = self._normalize_times(
                video.duration,
                start,
                end,
                max_seconds=target_duration,
            )

            segments.append(
                StorySegment(
                    segment_type=SegmentType.VIDEO_CLIP,
                    content=VideoSegment(
                        source_video_id=video.id,
                        start_time=start,
                        end_time=end,
                        description=description,
                        keep_original_audio=False,
                    ),
                    voice_over=voice_over,
                    order=index,
                )
            )

        print(f"Story: segments assembled in {time.perf_counter() - step_start:.2f}s")
        return segments

    def generate_segments_sync(self, customer_situation: str) -> list[StorySegment]:
        """Sync wrapper for generate_segments (useful in environments with a running loop)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.generate_segments(customer_situation))

        def _runner() -> list[StorySegment]:
            return asyncio.run(self.generate_segments(customer_situation))

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_runner).result()

    async def generate_story(self, customer_situation: str) -> list[StorySegment]:
        """Backward-compatible name that returns a list of segments."""
        return await self.generate_segments(customer_situation)

# Convenience function

async def generate_personalized_video(
    customer_situation: str,
    config: Optional[Config] = None,
) -> list[StorySegment]:
    """Generate personalized story segments from a customer situation."""
    generator = PersonalizedStoryGenerator(config)
    return await generator.generate_segments(customer_situation)

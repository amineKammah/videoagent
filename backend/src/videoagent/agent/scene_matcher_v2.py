"""VO-focused scene matcher v2 using precomputed scene-analysis index."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from videoagent.config import Config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.storage import get_storage_client
from videoagent.story import _StoryboardScene

from .scene_analysis_index import read_scene_index, to_voiceless_path
from .scene_matcher import (
    SceneMatchJob,
    SceneMatchMode,
    _analyze_voice_over_job,
    _duration_section,
)
from .schemas import SceneMatchV2BatchRequest
from .storage import EventStore, StoryboardStore

_SHORTLIST_DURATION_EPSILON_SECONDS = 0.01
_SHORTLIST_END_SOFT_CAP_SECONDS = 0.5


class ShortlistClip(BaseModel):
    video_id: str
    start_time: float
    end_time: float
    reason: str


class ShortlistResponse(BaseModel):
    review_clips: list[ShortlistClip] = Field(default_factory=list)
    notes: Optional[str] = None


class SceneMatcherV2:
    """Isolated v2 matcher for voice-over scenes only."""

    def __init__(
        self,
        config: Config,
        storyboard_store: StoryboardStore,
        event_store: EventStore,
        session_id: str,
        company_id: Optional[str],
        user_id: Optional[str],
        shortlist_model: Optional[str] = None,
        deep_model: Optional[str] = None,
    ) -> None:
        self.config = config
        self.storyboard_store = storyboard_store
        self.event_store = event_store
        self.session_id = session_id
        self.company_id = company_id
        self.user_id = user_id
        self.shortlist_model = shortlist_model or os.getenv(
            "SCENE_MATCHER_V2_SHORTLIST_MODEL",
            "gemini-3-flash-preview",
        )
        self.deep_model = deep_model or os.getenv(
            "SCENE_MATCHER_V2_DEEP_MODEL",
            "gemini-3-flash-preview",
        )
        self._thinking_budget = self._parse_thinking_budget(
            os.getenv("SCENE_MATCHER_V2_THINKING_BUDGET", "-1")
        )

    @staticmethod
    def _parse_thinking_budget(value: str) -> Optional[int]:
        raw = str(value or "").strip().lower()
        if raw in {"", "none", "unlimited", "null"}:
            return None
        try:
            parsed = int(raw)
        except ValueError:
            return -1
        if parsed == -1:
            return -1
        if parsed < -1:
            return -1
        return parsed

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        total = max(0.0, float(seconds))
        minutes = int(total // 60)
        remainder = total - (minutes * 60)
        return f"{minutes:02d}:{remainder:06.3f}"

    @staticmethod
    def _print_issue(category: str, message: str) -> None:
        print(f"[SceneMatcherV2][{category}] {message}")

    @staticmethod
    def _preview_text(value: Any, *, max_chars: int = 280) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _mime_type_for_path(path: str) -> str:
        suffix = Path(path.split("?", 1)[0]).suffix.lower().lstrip(".")
        if not suffix:
            return "video/mp4"
        return f"video/{suffix}"

    @staticmethod
    def _build_response(
        *,
        results: list[dict[str, Any]],
        notes_by_scene_id: dict[str, list[str]],
        warnings_by_scene_id: dict[str, list[str]],
        errors: list[dict[str, Any]],
        shortlist_review_clips_by_scene_id: Optional[dict[str, list[dict[str, Any]]]] = None,
    ) -> str:
        payload: dict[str, Any] = {"results": results}
        if notes_by_scene_id:
            payload["notes"] = notes_by_scene_id
        if warnings_by_scene_id:
            payload["warnings"] = warnings_by_scene_id
        if errors:
            payload["errors"] = errors
        if shortlist_review_clips_by_scene_id:
            payload["shortlist_review_clips"] = shortlist_review_clips_by_scene_id
        return (
            f"{json.dumps(payload)}\n"
            "Message: Review the candidates above. Curate the 2-4 BEST candidates per scene "
            "(ranked from best to worst) and call 'set_scene_candidates' to save them."
        )

    @staticmethod
    def _dedupe_messages(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _filter_short_clips(
        review_clips: list[ShortlistClip],
        *,
        target_duration: float,
    ) -> tuple[list[ShortlistClip], list[str]]:
        kept: list[ShortlistClip] = []
        dropped_messages: list[str] = []
        for clip in review_clips:
            span = clip.end_time - clip.start_time
            if span <= target_duration:
                dropped_messages.append(
                    "Dropped shortlist clip: duration must be strictly longer than target scene duration. "
                    f"video_id={clip.video_id}, start={clip.start_time:.3f}, end={clip.end_time:.3f}, "
                    f"clip_duration={span:.3f}s, target_duration={target_duration:.3f}s"
                )
                continue
            kept.append(clip)
        return kept, dropped_messages

    async def match_scene_to_video_v2(self, payload: SceneMatchV2BatchRequest) -> str:
        if not payload.requests:
            return "No scene match requests provided."
        try:
            scenes = self.storyboard_store.load(self.session_id, user_id=self.user_id) or []
        except ValidationError as exc:
            self._print_issue(
                "storyboard_decode",
                (
                    f"Failed to decode storyboard scene payload for session_id={self.session_id}, "
                    f"user_id={self.user_id}: {exc}"
                ),
            )
            return (
                "Failed to decode storyboard scenes for this session. "
                "Regenerate storyboard scenes, then retry v2 matching."
            )
        except Exception as exc:
            self._print_issue(
                "storyboard_load",
                (
                    f"Unexpected error loading storyboard for session_id={self.session_id}, "
                    f"user_id={self.user_id}: {exc}"
                ),
            )
            return "Failed to load storyboard scenes. Retry v2 matching."
        if not scenes:
            self._print_issue(
                "no_scenes",
                f"Storyboard is empty for session_id={self.session_id}, user_id={self.user_id}.",
            )
            return "No storyboard scenes found. Create a storyboard before matching scenes."

        scene_map = {scene.scene_id: scene for scene in scenes}

        if not self.company_id:
            self._print_issue("missing_company_id", "company_id is required for scene_matcher_v2.")
            return "company_id is required for scene_matcher_v2."

        storage = get_storage_client(self.config)
        index_payload = read_scene_index(storage, self.company_id)
        if not index_payload:
            self._print_issue(
                "missing_index",
                (
                    f"Scene analysis index missing or unreadable for company_id={self.company_id}. "
                    f"Expected key: companies/{self.company_id}/scene_analysis/index_vo_v1.json"
                ),
            )
            return (
                "Scene analysis index not found in GCS. "
                "Run run_scene_analysis_prompt.py with --all-videos --persist-gcs --build-index first."
            )

        library = VideoLibrary(self.config, company_id=self.company_id)
        library.scan_library()
        video_map = {video.id: video for video in library.list_videos()}
        shortlist_index_payload, index_warnings = self._prepare_shortlist_index_payload(
            index_payload=index_payload,
            video_map=video_map,
        )
        for warning in index_warnings:
            self._print_issue("index_warning", warning)

        response_results_by_index: dict[int, dict[str, Any]] = {}
        response_notes: dict[str, list[str]] = {}
        response_warnings: dict[str, list[str]] = {}
        response_errors: list[dict[str, Any]] = []
        response_shortlist_clips: dict[str, list[dict[str, Any]]] = {}
        pending_jobs: list[tuple[int, str, _StoryboardScene, str, float]] = []

        for index, request in enumerate(payload.requests):
            scene_id = request.scene_id
            scene = scene_map.get(scene_id)
            if not scene:
                self._print_issue(
                    "scene_not_found",
                    f"scene_id={scene_id} not found in storyboard for session_id={self.session_id}.",
                )
                response_errors.append(
                    {
                        "scene_id": scene_id,
                        "error": f"Storyboard scene id not found: {scene_id}",
                    }
                )
                response_results_by_index[index] = {"scene_id": scene_id, "candidates": []}
                continue

            if not scene.use_voice_over:
                self._print_issue(
                    "wrong_audio_mode",
                    f"scene_id={scene_id} has use_voice_over=False; v2 is voice-over only.",
                )
                response_errors.append(
                    {
                        "scene_id": scene_id,
                        "error": (
                            f"Scene {scene_id} is configured to keep original audio. "
                            "Use V1 matcher (`match_scene_to_video`) for non-voice-over scenes."
                        ),
                    }
                )
                response_results_by_index[index] = {"scene_id": scene_id, "candidates": []}
                continue

            target_duration = scene.voice_over.duration if scene.voice_over else None
            if target_duration is None or float(target_duration) <= 0:
                self._print_issue(
                    "missing_vo_duration",
                    f"scene_id={scene_id} has invalid voice-over duration: {target_duration}.",
                )
                response_errors.append(
                    {
                        "scene_id": scene_id,
                        "error": (
                            f"Scene {scene_id} is missing voice-over duration. "
                            "Generate voice overs first, then retry v2 matching."
                        ),
                    }
                )
                response_results_by_index[index] = {"scene_id": scene_id, "candidates": []}
                continue

            pending_jobs.append((index, scene_id, scene, request.notes.strip(), float(target_duration)))

        async def _run_pending_job(
            index: int,
            scene_id: str,
            scene: _StoryboardScene,
            notes: str,
            target_duration: float,
        ) -> tuple[int, str, dict[str, Any]]:
            scene_result = await self._match_single_scene_to_video_v2(
                scene=scene,
                notes=notes,
                target_duration=target_duration,
                storage=storage,
                shortlist_index_payload=shortlist_index_payload,
                video_map=video_map,
                index_warnings=index_warnings,
            )
            return index, scene_id, scene_result

        if pending_jobs:
            concurrent_results = await asyncio.gather(
                *[
                    _run_pending_job(index, scene_id, scene, notes, target_duration)
                    for index, scene_id, scene, notes, target_duration in pending_jobs
                ],
                return_exceptions=True,
            )

            for (index, scene_id, _scene, _notes, _duration), result in zip(pending_jobs, concurrent_results):
                if isinstance(result, Exception):
                    self._print_issue("scene_batch_exception", f"Unexpected v2 batch exception: {result}")
                    response_errors.append(
                        {
                            "scene_id": scene_id,
                            "error": f"Unexpected v2 batch exception: {result}",
                        }
                    )
                    response_results_by_index[index] = {"scene_id": scene_id, "candidates": []}
                    continue

                index, scene_id, scene_result = result
                response_results_by_index[index] = {
                    "scene_id": scene_id,
                    "candidates": scene_result["candidates"],
                }
                if scene_result["notes"]:
                    response_notes[scene_id] = scene_result["notes"]
                if scene_result["warnings"]:
                    response_warnings[scene_id] = scene_result["warnings"]
                if scene_result["errors"]:
                    response_errors.extend(scene_result["errors"])
                if scene_result["shortlist_review_clips"] is not None:
                    response_shortlist_clips[scene_id] = scene_result["shortlist_review_clips"]

            self.event_store.append(
                self.session_id,
                {"type": "video_render_complete"},
                user_id=self.user_id,
            )

        ordered_results: list[dict[str, Any]] = []
        for idx in range(len(payload.requests)):
            item = response_results_by_index.get(idx)
            if item:
                ordered_results.append(item)

        return self._build_response(
            results=ordered_results,
            notes_by_scene_id=response_notes,
            warnings_by_scene_id=response_warnings,
            errors=response_errors,
            shortlist_review_clips_by_scene_id=response_shortlist_clips,
        )

    async def _match_single_scene_to_video_v2(
        self,
        *,
        scene: _StoryboardScene,
        notes: str,
        target_duration: float,
        storage: Any,
        shortlist_index_payload: dict[str, Any],
        video_map: dict[str, Any],
        index_warnings: list[str],
    ) -> dict[str, Any]:
        scene_id = scene.scene_id
        errors: list[dict[str, Any]] = []
        warnings: list[str] = list(index_warnings)
        notes_out: list[str] = []

        shortlist_result = await self._shortlist_review_clips(
            scene=scene,
            notes=notes,
            target_duration=target_duration,
            index_payload=shortlist_index_payload,
        )
        if shortlist_result.get("error"):
            self._print_issue(
                "shortlist_error",
                f"scene_id={scene_id}: {shortlist_result['error']}",
            )
            errors.append({"scene_id": scene_id, "error": shortlist_result["error"]})
            return {
                "candidates": [],
                "notes": self._dedupe_messages(notes_out),
                "warnings": self._dedupe_messages(warnings),
                "errors": errors,
                "shortlist_review_clips": None,
            }

        shortlist_clips = shortlist_result["review_clips"]
        if shortlist_result.get("notes"):
            notes_out.append(f"[shortlist] {shortlist_result['notes']}")

        shortlist_clips, dropped_short = self._filter_short_clips(
            shortlist_clips,
            target_duration=target_duration,
        )
        for message in dropped_short:
            self._print_issue("shortlist_filter", message)
            warnings.append(message)

        if not shortlist_clips:
            warning = (
                "Shortlist returned no review clips after post-filtering "
                f"(required: clip duration > {target_duration:.3f}s)."
            )
            self._print_issue("shortlist_empty", warning)
            warnings.append(warning)
            return {
                "candidates": [],
                "notes": self._dedupe_messages(notes_out),
                "warnings": self._dedupe_messages(warnings),
                "errors": errors,
                "shortlist_review_clips": [],
            }

        validation_error = self._validate_shortlist(shortlist_clips, video_map)
        if validation_error:
            self._print_issue("shortlist_validation", validation_error)
            errors.append({"scene_id": scene_id, "error": validation_error})
            return {
                "candidates": [],
                "notes": self._dedupe_messages(notes_out),
                "warnings": self._dedupe_messages(warnings),
                "errors": errors,
                "shortlist_review_clips": [clip.model_dump(mode="json") for clip in shortlist_clips],
            }

        deep_results = await self._run_deep_analysis(
            scene=scene,
            notes=notes,
            shortlist_clips=shortlist_clips,
            video_map=video_map,
            storage=storage,
            target_duration=target_duration,
        )

        candidates: list[dict[str, Any]] = []
        for result in deep_results:
            clip = result["clip"]
            if result.get("error"):
                self._print_issue(
                    "deep_analysis_error",
                    (
                        f"scene_id={scene_id}, video_id={clip.video_id}, "
                        f"window=[{clip.start_time:.3f}, {clip.end_time:.3f}]: {result['error']}"
                    ),
                )
                errors.append(
                    {
                        "scene_id": scene_id,
                        "video_id": clip.video_id,
                        "error": result["error"],
                    }
                )
                continue
            if result.get("notes"):
                notes_out.append(f"[{clip.video_id}] {result['notes']}")
            if result.get("warning"):
                self._print_issue("deep_analysis_warning", result["warning"])
                warnings.append(result["warning"])

            for candidate in result.get("candidates", []):
                candidates.append(candidate)

        return {
            "candidates": candidates,
            "notes": self._dedupe_messages(notes_out),
            "warnings": self._dedupe_messages(warnings),
            "errors": errors,
            "shortlist_review_clips": [clip.model_dump(mode="json") for clip in shortlist_clips],
        }

    @staticmethod
    def _prepare_shortlist_index_payload(
        *,
        index_payload: dict[str, Any],
        video_map: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        payload_videos = index_payload.get("videos")
        if not isinstance(payload_videos, list):
            return {"videos": []}, ["Scene analysis index has invalid or missing 'videos'."]

        videos_out: list[dict[str, Any]] = []
        indexed_video_ids: set[str] = set()

        for raw_video in payload_videos:
            if not isinstance(raw_video, dict):
                continue
            video_id = str(raw_video.get("video_id") or "").strip()
            if not video_id:
                continue
            indexed_video_ids.add(video_id)

            if video_id not in video_map:
                continue

            eligible = raw_video.get("eligible_scenes")
            excluded = raw_video.get("excluded_scenes")
            eligible_scenes = eligible if isinstance(eligible, list) else []
            excluded_scenes_raw = excluded if isinstance(excluded, list) else []
            excluded_scenes = []
            for scene in excluded_scenes_raw:
                if not isinstance(scene, dict):
                    continue
                excluded_scenes.append(
                    {
                        "scene_id": scene.get("scene_id"),
                        "reasons": scene.get("reasons", []),
                    }
                )

            videos_out.append(
                {
                    "video_id": video_id,
                    "filename": raw_video.get("filename"),
                    "video_duration": raw_video.get("video_duration"),
                    "eligible_scenes": eligible_scenes,
                    "excluded_scenes": excluded_scenes,
                }
            )

        library_video_ids = set(video_map.keys())
        missing_from_index = sorted(library_video_ids - indexed_video_ids)
        stale_in_index = sorted(indexed_video_ids - library_video_ids)

        if missing_from_index:
            warnings.append(
                "Skipped "
                f"{len(missing_from_index)} library video(s) missing scene-analysis entries in index."
            )
        if stale_in_index:
            warnings.append(
                "Ignored "
                f"{len(stale_in_index)} index video(s) no longer present in library."
            )
        if not videos_out:
            warnings.append("No usable videos in scene-analysis index after filtering.")

        payload_out = {
            "schema_version": index_payload.get("schema_version"),
            "generated_at": index_payload.get("generated_at"),
            "company_id": index_payload.get("company_id"),
            "videos": videos_out,
        }
        return payload_out, warnings

    def _validate_shortlist(self, review_clips: list[ShortlistClip], video_map: dict[str, Any]) -> Optional[str]:
        if len(review_clips) > 5:
            return "Shortlist rejected: model returned more than 5 clips."

        for idx, clip in enumerate(review_clips, start=1):
            if clip.video_id not in video_map:
                return f"Shortlist rejected: unknown video_id at position {idx}: {clip.video_id}"
            if clip.start_time < 0:
                return f"Shortlist rejected: negative start time at position {idx}."
            video_duration = float(video_map[clip.video_id].duration)
            if clip.end_time > video_duration + _SHORTLIST_DURATION_EPSILON_SECONDS:
                overrun = clip.end_time - video_duration
                if overrun < _SHORTLIST_END_SOFT_CAP_SECONDS:
                    clip.end_time = video_duration
                else:
                    return (
                        "Shortlist rejected: clip end exceeds video duration at "
                        f"position {idx} ({clip.end_time:.3f} > {video_duration:.3f})."
                    )
            if clip.end_time <= clip.start_time:
                return f"Shortlist rejected: invalid timing at position {idx}."
            span = clip.end_time - clip.start_time
            if span > 120.0:
                return f"Shortlist rejected: span > 120s at position {idx}."
        return None

    async def _shortlist_review_clips(
        self,
        *,
        scene: _StoryboardScene,
        notes: str,
        target_duration: float,
        index_payload: dict[str, Any],
    ) -> dict[str, Any]:
        client = GeminiClient(self.config)
        client.use_vertexai = True

        prompt = self._build_shortlist_prompt(
            scene=scene,
            notes=notes,
            target_duration=target_duration,
            index_payload=index_payload,
        )

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": ShortlistResponse.model_json_schema(),
        }
        if self._thinking_budget is not None:
            config["thinking_config"] = types.ThinkingConfig(thinking_budget=self._thinking_budget)

        try:
            response = await client.client.aio.models.generate_content(
                model=self.shortlist_model,
                contents=types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)],
                ),
                config=config,
            )
        except Exception as exc:
            self._print_issue(
                "shortlist_llm_call",
                (
                    f"Shortlist LLM call failed for scene_id={scene.scene_id}, "
                    f"model={self.shortlist_model}: {exc}"
                ),
            )
            return {"error": f"Shortlist LLM call failed: {exc}"}

        if not response.text:
            self._print_issue(
                "shortlist_empty_response",
                f"Shortlist model returned empty response for scene_id={scene.scene_id}.",
            )
            return {"error": "Shortlist LLM returned empty response."}

        try:
            parsed = ShortlistResponse.model_validate_json(response.text)
        except ValidationError as exc:
            response_preview = self._preview_text(response.text, max_chars=320)
            self._print_issue(
                "shortlist_validation",
                (
                    f"Failed to validate shortlist JSON for scene_id={scene.scene_id}: {exc}. "
                    f"response_preview={response_preview}"
                ),
            )
            return {"error": f"Shortlist response validation failed: {exc}"}

        return {
            "review_clips": parsed.review_clips,
            "notes": parsed.notes,
        }

    async def _run_deep_analysis(
        self,
        *,
        scene: _StoryboardScene,
        notes: str,
        shortlist_clips: list[ShortlistClip],
        video_map: dict[str, Any],
        storage: Any,
        target_duration: float,
    ) -> list[dict[str, Any]]:
        client = GeminiClient(self.config)
        client.use_vertexai = True
        upload_cache: dict[str, object] = {}
        skipped_results: list[dict[str, Any]] = []
        runnable_jobs: list[tuple[ShortlistClip, SceneMatchJob, object]] = []

        for clip in shortlist_clips:
            video_metadata = video_map[clip.video_id]
            path = to_voiceless_path(str(video_metadata.path))
            if not storage.exists(path):
                self._print_issue(
                    "deep_source_missing",
                    (
                        f"Voiceless source missing for scene_id={scene.scene_id}, "
                        f"video_id={clip.video_id}, path={path}"
                    ),
                )
                skipped_results.append(
                    {
                        "clip": clip,
                        "error": f"Voiceless source not found for deep analysis: {path}",
                    }
                )
                continue

            uploaded = upload_cache.get(clip.video_id)
            if uploaded is None:
                try:
                    uploaded = client.get_or_upload_file(path)
                except Exception as exc:
                    self._print_issue(
                        "deep_upload_failed",
                        (
                            f"Failed to upload video for deep analysis: scene_id={scene.scene_id}, "
                            f"video_id={clip.video_id}, path={path}, error={exc}"
                        ),
                    )
                    skipped_results.append(
                        {
                            "clip": clip,
                            "error": f"Failed to prepare video file for deep analysis: {exc}",
                        }
                    )
                    continue
                upload_cache[clip.video_id] = uploaded

            job = SceneMatchJob(
                scene_id=scene.scene_id,
                scene=scene,
                video_id=clip.video_id,
                metadata=video_metadata,
                notes=f"{notes}\nShortlist reason: {clip.reason}",
                mode=SceneMatchMode.VOICE_OVER,
                duration_section=_duration_section(target_duration),
                target_duration=target_duration,
                start_offset_seconds=clip.start_time,
                end_offset_seconds=clip.end_time,
            )
            runnable_jobs.append((clip, job, uploaded))

        tasks = [
            _analyze_voice_over_job(client, job, uploaded)
            for _, job, uploaded in runnable_jobs
        ]
        analyzed = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

        merged_results: list[dict[str, Any]] = list(skipped_results)
        for (clip, _, _), result in zip(runnable_jobs, analyzed):
            if isinstance(result, Exception):
                self._print_issue(
                    "deep_analysis_exception",
                    (
                        f"Unexpected deep-analysis exception for scene_id={scene.scene_id}, "
                        f"video_id={clip.video_id}, window=[{clip.start_time:.3f}, {clip.end_time:.3f}]: "
                        f"{result}"
                    ),
                )
                merged_results.append(
                    {
                        "clip": clip,
                        "error": f"Deep analysis failed unexpectedly: {result}",
                    }
                )
                continue
            if result.get("error"):
                self._print_issue(
                    "deep_analysis_model_error",
                    (
                        f"Model deep analysis error for scene_id={scene.scene_id}, "
                        f"video_id={clip.video_id}: {result['error']}"
                    ),
                )
                merged_results.append(
                    {
                        "clip": clip,
                        "error": result["error"],
                    }
                )
                continue
            merged_results.append(
                {
                    "clip": clip,
                    "candidates": result.get("candidates", []),
                    "notes": result.get("notes"),
                    "warning": (
                        None
                        if result.get("candidates")
                        else (
                            f"Deep analysis returned no usable candidates for clip {clip.video_id} "
                            f"[{clip.start_time:.2f}, {clip.end_time:.2f}]"
                        )
                    ),
                }
            )
        return merged_results

    @staticmethod
    def _clean_prompt_text(value: Any, *, max_chars: int = 220) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    @classmethod
    def _render_target_scene_block(
        cls,
        *,
        scene: _StoryboardScene,
        notes: str,
        target_duration: float,
    ) -> str:
        title = cls._clean_prompt_text(scene.title, max_chars=140) or "(untitled)"
        purpose = cls._clean_prompt_text(scene.purpose, max_chars=220) or "(none)"
        script = cls._clean_prompt_text(scene.script, max_chars=800) or "(none)"
        notes_text = cls._clean_prompt_text(notes, max_chars=500) or "(none)"
        return (
            "### TARGET SCENE\n"
            f"- scene_id: `{scene.scene_id}`\n"
            f"- title: {title}\n"
            f"- purpose: {purpose}\n"
            f"- target_duration_seconds: {target_duration:.3f}\n"
            f"- script: {script}\n"
            f"- notes: {notes_text}\n"
        )

    @classmethod
    def _render_video_context_block(cls, index_payload: dict[str, Any]) -> str:
        videos = index_payload.get("videos")
        if not isinstance(videos, list) or not videos:
            return "### VIDEO LIBRARY CONTEXT\nNo videos available.\n"

        lines: list[str] = ["### VIDEO LIBRARY CONTEXT", ""]
        for raw_video in videos:
            if not isinstance(raw_video, dict):
                continue
            video_id = cls._clean_prompt_text(raw_video.get("video_id"), max_chars=80)
            if not video_id:
                continue
            filename = cls._clean_prompt_text(raw_video.get("filename"), max_chars=140) or "(unknown)"
            video_duration = raw_video.get("video_duration")
            try:
                video_duration_text = f"{float(video_duration):.3f}s"
            except (TypeError, ValueError):
                video_duration_text = "unknown"

            eligible_raw = raw_video.get("eligible_scenes")
            excluded_raw = raw_video.get("excluded_scenes")
            eligible_scenes = eligible_raw if isinstance(eligible_raw, list) else []
            excluded_scenes = excluded_raw if isinstance(excluded_raw, list) else []

            lines.append(f"#### VIDEO `{video_id}`")
            lines.append(f"- filename: `{filename}`")
            lines.append(f"- video_duration: `{video_duration_text}`")
            lines.append(f"- eligible_scene_count: `{len(eligible_scenes)}`")
            lines.append(f"- excluded_scene_count: `{len(excluded_scenes)}`")
            lines.append("- eligible_scenes:")
            if eligible_scenes:
                for scene in eligible_scenes:
                    if not isinstance(scene, dict):
                        continue
                    scene_id = cls._clean_prompt_text(scene.get("scene_id"), max_chars=80) or "unknown_scene"
                    start = scene.get("start_time", 0.0)
                    end = scene.get("end_time", 0.0)
                    duration = scene.get("duration", 0.0)
                    try:
                        start_f = float(start)
                        end_f = float(end)
                        duration_f = float(duration)
                    except (TypeError, ValueError):
                        start_f = 0.0
                        end_f = 0.0
                        duration_f = 0.0

                    visual_summary = cls._clean_prompt_text(scene.get("visual_summary"), max_chars=220) or "(none)"
                    semantic = scene.get("semantic_meaning")
                    semantic_map = semantic if isinstance(semantic, dict) else {}
                    purpose = cls._clean_prompt_text(
                        semantic_map.get("narrative_purpose"),
                        max_chars=60,
                    ) or "unknown"
                    feature = cls._clean_prompt_text(
                        semantic_map.get("feature_showcased"),
                        max_chars=80,
                    ) or "none"
                    pain = cls._clean_prompt_text(
                        semantic_map.get("pain_point_depicted"),
                        max_chars=80,
                    ) or "none"
                    tone = cls._clean_prompt_text(
                        semantic_map.get("emotional_tone"),
                        max_chars=60,
                    ) or "neutral"
                    keywords_value = scene.get("searchable_keywords")
                    keywords: list[str] = []
                    if isinstance(keywords_value, list):
                        for item in keywords_value:
                            keyword = cls._clean_prompt_text(item, max_chars=30)
                            if keyword:
                                keywords.append(keyword)
                            if len(keywords) >= 4:
                                break
                    keywords_text = ", ".join(keywords) if keywords else "none"

                    lines.append(
                        "  - "
                        f"`{scene_id}` | {start_f:.3f}-{end_f:.3f}s ({duration_f:.3f}s) "
                        f"| visual: {visual_summary} "
                        f"| purpose: {purpose} "
                        f"| feature: {feature} "
                        f"| pain: {pain} "
                        f"| tone: {tone} "
                        f"| keywords: {keywords_text}"
                    )
            else:
                lines.append("  - (none)")

            lines.append("- excluded_scenes:")
            if excluded_scenes:
                for scene in excluded_scenes:
                    if not isinstance(scene, dict):
                        continue
                    scene_id = cls._clean_prompt_text(scene.get("scene_id"), max_chars=80) or "unknown_scene"
                    reasons_value = scene.get("reasons")
                    reasons: list[str] = []
                    if isinstance(reasons_value, list):
                        for item in reasons_value:
                            reason = cls._clean_prompt_text(item, max_chars=40)
                            if reason:
                                reasons.append(reason)
                    reasons_text = ", ".join(reasons) if reasons else "unspecified"
                    lines.append(f"  - `{scene_id}` | reasons: {reasons_text}")
            else:
                lines.append("  - (none)")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _build_shortlist_prompt(
        *,
        scene: _StoryboardScene,
        notes: str,
        target_duration: float,
        index_payload: dict[str, Any],
    ) -> str:
        target_block = SceneMatcherV2._render_target_scene_block(
            scene=scene,
            notes=notes,
            target_duration=target_duration,
        )
        video_context_block = SceneMatcherV2._render_video_context_block(index_payload)
        return f"""You are an expert Video Editor shortlisting videos for a voice-over scene.

### TASK OVERVIEW
You are helping a two-stage matching pipeline:
1) This call SHORTLISTS broad review clips only.
2) A second deep-analysis step inspects each shortlisted clip and finds the precise final moment(s) inside it.

Your job in this call is to return the best candidate review clips for step (2).
Do not return final clip picks for rendering.

### AUDIO MODE: REPLACE WITH VOICE OVER
The source video audio will be replaced by generated voice-over.
So the shortlisted visuals must work as background for the script.

### MATCHING CONTEXT
Use the formatted context sections below:
- `TARGET SCENE`: exact scene objective and VO script intent.
- `VIDEO LIBRARY CONTEXT`: scene-level cards per video.

For each eligible scene card, only curated high-signal fields are provided:
- `scene_id`, `start/end/duration`
- `visual_summary`
- semantic fields: `narrative_purpose`, `feature_showcased`, `pain_point_depicted`, `emotional_tone`
- top `searchable_keywords`

Excluded scenes are listed only as `scene_id + reasons`.

### STRICT VISUAL RULES (CRITICAL)
Prioritize clips that satisfy all of the following:
- No talking heads speaking to camera.
- No burned-in subtitles.
- No speaking person shown inside a screen region (edge-case speaker in PIP/Zoom/TV/laptop/phone).
- Visually compatible with the script and notes.
- Avoid static visuals that stay unchanged for the entire clip.

### SHORTLISTING MISSION
- Hold a very high bar for the candidates. Only select it if it has HIGH relevant to the scene voice over.
- For example, if a scene script highlights the easy integration with company X. If a scene describes the easy integration with company Y, this is not a good fit and it should NOT be shortlisted.
- The matched candidate needs to highlight ALL the main talking points of the script.


### Output
- Pick at most 5 high-potential review clips.
- Each clip must be within one video and <= 120 seconds.
- Each clip must be STRICTLY longer than the target scene duration.
- Clips may and often should span multiple adjacent eligible scenes when useful.
- Treat each shortlisted clip as a broad review window for the next refinement step.



### OUTPUT SCHEMA
{{
  "review_clips":[
    {{
      "video_id":"...",
      "start_time":12.3,
      "end_time":68.0,
      "reason":"..."
    }}
  ],
  "notes":"optional"
}}

### HARD CONSTRAINTS
- max review_clips: 5
- each clip span: <= 120 seconds
- each clip span: > target_duration_seconds (strictly greater)
- start_time >= 0
- end_time > start_time
- use only `eligible_scenes`
- do not use `excluded_scenes` content

{target_block}
{video_context_block}
"""

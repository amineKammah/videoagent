#!/usr/bin/env python3
# ruff: noqa: E402, I001
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google.genai import types
from pydantic import BaseModel, Field

from videoagent.agent.scene_analysis_index import (
    build_vo_scene_index,
    read_video_scene_analysis,
    to_voiceless_path,
    write_scene_index,
    write_video_scene_analysis,
)
from videoagent.agent.storage import _parse_timestamp
from videoagent.config import default_config
from videoagent.db import connection, crud
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary
from videoagent.storage import get_storage_client

_SOFT_END_CLAMP_SECONDS = 1.0


GEMINI_VIDEO_ANALYSIS_PROMPT = """Analyze this video and return compact scene metadata for VO-safe shortlisting.

Goal:
1) Split into scenes.
2) Keep only essential fields.
3) Return strict JSON.

IMPORTANT:
- Do NOT transcribe speech.
- Do NOT include verbatim transcript text.
- Keep output concise: each `visual_summary` <= 25 words.
- `searchable_keywords`: max 5 per scene.
- Include `semantic_meaning` for each scene and `extracted_insights` at top level.
- Timestamps MUST use `MM:SS.sss` or `HH:MM:SS.sss` format, e.g. `02:23.456` or `00:02:23.456`.

# SCENE SPLIT RULES
Start a new scene on visual cut/transition, clear subject change, framing change, or major on-screen text change.

# TALKING HEAD (SAFETY-CRITICAL)
Set `has_talking_head=true` when a visibly speaking person is a primary visual focus.
Includes:
- Interview/testimonial framing (close or medium shot of speaker).
- Direct-to-camera presenter/webcam/selfie delivery.
- On-camera speech where mouth movement and speaking role are clear.

Set `has_talking_head=false` for:
- Non-speaking b-roll people.
- Wide shots without a focal speaker.
- UI-only, motion graphics, product/object shots.
- VO over non-speaking visuals.

Edge case:
`has_speaking_screen_edge_case=true` if a speaker appears inside another screen region
(Zoom tile/TV/phone/laptop-in-frame/PiP presenter), even if not full-frame.

Conservative rule:
When uncertain, bias toward true for talking-head-related flags and use moderate confidence.

# REQUIRED OUTPUT JSON

{
  "video_metadata": {
    "video_id": "__VIDEO_ID__"
  },
  "scenes": [
    {
      "scene_id": "sc_001",
      "scene_number": 1,
      "start_time": "00:00.000",
      "end_time": "00:05.200",
      "duration": 5.2,
      "visual_summary": "Short concrete visual summary.",
      "semantic_meaning": {
        "narrative_purpose": "problem_statement",
        "pain_point_depicted": null,
        "feature_showcased": null,
        "emotional_tone": ""
      },
      "detection_signals": {
        "has_burned_in_subtitles": false,
        "burned_in_subtitles_confidence": 0.0,
        "subtitle_language": null,
        "has_talking_head": false,
        "talking_head_confidence": 0.0,
        "has_speaking_screen_edge_case": false,
        "speaking_screen_edge_case_confidence": 0.0,
        "is_testimony_like": false,
        "testimony_confidence": 0.0
      },
      "searchable_keywords": []
    }
  ],
  "extracted_insights": {
    "key_pain_points": [],
    "featured_capabilities": [],
    "visual_messaging_patterns": [],
    "emotional_journey": ""
  }
}

Return valid JSON only. No markdown, no extra prose.
"""


class _SceneAnalysisVideoMetadata(BaseModel):
    video_id: str


class _SceneAnalysisSemanticMeaning(BaseModel):
    narrative_purpose: str
    pain_point_depicted: Optional[str] = None
    feature_showcased: Optional[str] = None
    emotional_tone: str = ""


class _SceneAnalysisDetectionSignals(BaseModel):
    has_burned_in_subtitles: bool
    burned_in_subtitles_confidence: float
    subtitle_language: Optional[str] = None
    has_talking_head: bool
    talking_head_confidence: float
    has_speaking_screen_edge_case: bool
    speaking_screen_edge_case_confidence: float
    is_testimony_like: bool
    testimony_confidence: float


class _SceneAnalysisScene(BaseModel):
    scene_id: str
    scene_number: int
    start_time: str
    end_time: str
    duration: float
    visual_summary: str
    semantic_meaning: _SceneAnalysisSemanticMeaning
    detection_signals: _SceneAnalysisDetectionSignals
    searchable_keywords: list[str] = Field(default_factory=list)


class _SceneAnalysisExtractedInsights(BaseModel):
    key_pain_points: list[str] = Field(default_factory=list)
    featured_capabilities: list[str] = Field(default_factory=list)
    visual_messaging_patterns: list[str] = Field(default_factory=list)
    emotional_journey: str = ""


class _SceneAnalysisResponse(BaseModel):
    video_metadata: _SceneAnalysisVideoMetadata
    scenes: list[_SceneAnalysisScene] = Field(default_factory=list)
    extracted_insights: _SceneAnalysisExtractedInsights = Field(
        default_factory=_SceneAnalysisExtractedInsights
    )


def _load_env() -> None:
    if load_dotenv is None:
        return
    repo_env = REPO_ROOT / ".env"
    backend_env = BACKEND_DIR / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    elif backend_env.exists():
        load_dotenv(dotenv_path=backend_env)
    else:
        load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run scene-analysis prompt on one or many company videos. "
            "Supports optional GCS persistence and VO index generation."
        )
    )
    parser.add_argument("--company-name", default="Navan", help="Company name in DB (default: Navan).")
    parser.add_argument(
        "--company-id",
        default=None,
        help="Optional explicit company_id. If set, skips DB name lookup.",
    )
    parser.add_argument(
        "--video-id",
        default=None,
        help="Optional explicit video_id. If omitted, selects one random GCS video unless --all-videos is set.",
    )
    parser.add_argument(
        "--all-videos",
        action="store_true",
        help="Analyze all GCS videos for the company (voiceless variant required).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of videos to analyze (applies after selection).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for deterministic random selection.",
    )
    parser.add_argument("--model", default="gemini-3-pro-preview", help="Gemini model to use.")
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=65535,
        help="Max output tokens for Gemini response (default: 65535).",
    )
    parser.add_argument(
        "--thinking-budget",
        default="10000",
        help=(
            "Gemini thinking budget. Use -1 for unlimited, "
            "or a non-negative integer (default: 10000)."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of videos to process concurrently (default: 10).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "scene_analysis_reviews",
        help="Directory for local artifacts.",
    )
    parser.add_argument(
        "--persist-gcs",
        action="store_true",
        help="Persist successful per-video scene analysis JSON to GCS.",
    )
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="Build VO index from scene analyses; writes to GCS only when --persist-gcs is set.",
    )
    return parser.parse_args()


def _resolve_company_id(company_name: str) -> str:
    with connection.get_db_context() as db:
        company = crud.get_company_by_name(db, company_name)
        if company:
            return company.id

        candidates = crud.list_companies(db, include_test=True, skip=0, limit=1000)
        target = company_name.strip().lower()
        for candidate in candidates:
            name = (candidate.name or "").strip().lower()
            if name == target:
                return candidate.id
        for candidate in candidates:
            name = (candidate.name or "").strip().lower()
            if target in name:
                return candidate.id

    fallback_paths = [
        REPO_ROOT / "videoagent_1.db",
        BACKEND_DIR / "videoagent_1.db",
        REPO_ROOT / "videoagent.db",
        BACKEND_DIR / "videoagent.db",
    ]
    target = company_name.strip().lower()
    for db_path in fallback_paths:
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("SELECT id, name FROM companies").fetchall()
        except Exception:
            continue
        for company_id, name in rows:
            if str(name).strip().lower() == target:
                return str(company_id)
        for company_id, name in rows:
            if target in str(name).strip().lower():
                return str(company_id)

    raise ValueError(f"Company '{company_name}' not found in configured DB or fallback sqlite files.")


def _parse_thinking_budget(raw_value: Any) -> Optional[int]:
    text = str(raw_value).strip().lower()
    if text in {"", "unlimited", "none", "null", "off"}:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(
            f"Invalid --thinking-budget value '{raw_value}'. Use an integer or 'unlimited'."
        ) from exc
    if value == -1:
        return -1
    if value < -1:
        raise ValueError("--thinking-budget must be -1, >= 0, or 'unlimited'.")
    return value


def _all_gcs_videos(library: VideoLibrary) -> list[Any]:
    videos = library.list_videos()
    return [
        video
        for video in videos
        if isinstance(video.path, str) and str(video.path).startswith("gs://")
    ]


def _select_videos(
    *,
    library: VideoLibrary,
    video_id: Optional[str],
    seed: Optional[int],
    all_videos: bool,
    limit: Optional[int],
) -> list[Any]:
    gcs_videos = _all_gcs_videos(library)
    if not gcs_videos:
        raise ValueError("No GCS-backed videos found in library.")

    selected: list[Any]
    if video_id:
        picked = next((video for video in gcs_videos if video.id == video_id), None)
        if not picked:
            raise ValueError(f"Video id '{video_id}' not found among company GCS videos.")
        selected = [picked]
    elif all_videos:
        selected = list(gcs_videos)
    else:
        rng = random.Random(seed)
        selected = [rng.choice(gcs_videos)]

    if limit is not None and limit >= 0:
        selected = selected[:limit]
    return selected


def _parse_json_response(raw_text: str) -> tuple[Optional[Any], Optional[str]]:
    if not raw_text:
        return None, "Model returned empty text."
    try:
        return json.loads(raw_text), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON response: {exc}"


def _format_timestamp_mmss(seconds: float) -> str:
    total = float(seconds)
    if total < 0:
        total = 0.0
    minutes = int(total // 60)
    remainder = total - (minutes * 60)
    return f"{minutes:02d}:{remainder:06.3f}"


def _coerce_scene_timestamp(
    value: Any,
    *,
    fallback_value: Any,
    field_name: str,
    scene_id: str,
) -> tuple[float, str]:
    candidate = value
    if candidate is None:
        candidate = fallback_value

    if isinstance(candidate, (int, float)):
        seconds = float(candidate)
        if seconds < 0:
            raise ValueError(f"{scene_id}: {field_name} must be >= 0.")
        return seconds, _format_timestamp_mmss(seconds)

    if isinstance(candidate, str):
        text = candidate.strip()
        if not text:
            raise ValueError(f"{scene_id}: {field_name} is empty.")
        try:
            seconds = _parse_timestamp(text)
        except ValueError as exc:
            raise ValueError(
                f"{scene_id}: {field_name} must use MM:SS.sss or HH:MM:SS.sss format (got '{candidate}')."
            ) from exc
        return seconds, text

    raise ValueError(f"{scene_id}: {field_name} has invalid type ({type(candidate).__name__}).")


def _normalize_scene_rows(payload: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        return payload, None

    normalized_scenes: list[dict[str, Any]] = []
    for idx, raw_scene in enumerate(scenes, start=1):
        if not isinstance(raw_scene, dict):
            return None, f"Scene #{idx}: scene is not an object."
        scene_id = str(raw_scene.get("scene_id") or f"scene_{idx}")
        try:
            start_seconds, start_timestamp = _coerce_scene_timestamp(
                raw_scene.get("start_time"),
                fallback_value=raw_scene.get("start_timestamp"),
                field_name="start_time",
                scene_id=scene_id,
            )
            end_seconds, end_timestamp = _coerce_scene_timestamp(
                raw_scene.get("end_time"),
                fallback_value=raw_scene.get("end_timestamp"),
                field_name="end_time",
                scene_id=scene_id,
            )
        except ValueError as exc:
            return None, str(exc)

        duration_value = raw_scene.get("duration")
        if isinstance(duration_value, (int, float)):
            duration_seconds = float(duration_value)
        elif isinstance(duration_value, str):
            try:
                duration_seconds = float(duration_value.strip())
            except ValueError:
                duration_seconds = end_seconds - start_seconds
        else:
            duration_seconds = end_seconds - start_seconds

        normalized_scene = dict(raw_scene)
        normalized_scene["scene_id"] = scene_id
        normalized_scene["start_time"] = start_seconds
        normalized_scene["end_time"] = end_seconds
        normalized_scene["start_timestamp"] = start_timestamp
        normalized_scene["end_timestamp"] = end_timestamp
        normalized_scene["duration"] = duration_seconds
        normalized_scenes.append(normalized_scene)

    payload["scenes"] = normalized_scenes
    return payload, None


def _soft_cap_scene_end_times(
    payload: dict[str, Any],
    *,
    video_duration: float,
    cap_threshold_seconds: float = _SOFT_END_CLAMP_SECONDS,
) -> list[str]:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        return []

    warnings: list[str] = []
    for idx, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or f"scene_{idx}")
        start = scene.get("start_time")
        end = scene.get("end_time")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        end_value = float(end)
        overrun = end_value - float(video_duration)
        if overrun <= 0:
            continue
        if overrun <= float(cap_threshold_seconds):
            capped_end = float(video_duration)
            scene["end_time"] = capped_end
            scene["end_timestamp"] = _format_timestamp_mmss(capped_end)
            scene["duration"] = max(0.0, capped_end - float(start))
            warnings.append(
                f"{scene_id}: capped end_time by {overrun:.3f}s to video duration {video_duration:.3f}s."
            )

    return warnings


def _normalize_scene_analysis_payload(payload: Any, video_id: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    normalized: Optional[dict[str, Any]] = None
    if isinstance(payload, dict):
        normalized = payload
        normalized.setdefault("video_metadata", {})
        if not isinstance(normalized.get("video_metadata"), dict):
            normalized["video_metadata"] = {}
        normalized["video_metadata"]["video_id"] = video_id

    # Recovery path: model sometimes wraps the full payload inside a one-item list.
    elif (
        isinstance(payload, list)
        and len(payload) == 1
        and isinstance(payload[0], dict)
        and isinstance(payload[0].get("scenes"), list)
    ):
        wrapped = payload[0]
        wrapped.setdefault("video_metadata", {})
        if not isinstance(wrapped.get("video_metadata"), dict):
            wrapped["video_metadata"] = {}
        wrapped["video_metadata"]["video_id"] = video_id
        normalized = wrapped

    # Recovery path: model sometimes returns a top-level array of scenes.
    elif isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        normalized = {
            "video_metadata": {"video_id": video_id},
            "scenes": payload,
            "extracted_insights": {
                "key_pain_points": [],
                "featured_capabilities": [],
                "visual_messaging_patterns": [],
                "emotional_journey": "",
            },
        }
    else:
        return (
            None,
            "Invalid JSON response: expected top-level object or list[scene], "
            f"got {type(payload).__name__}.",
        )

    return _normalize_scene_rows(normalized)


def _validate_scenes(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        return ["Top-level 'scenes' is missing or not a list."]

    prev_end: Optional[float] = None
    for idx, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            errors.append(f"Scene #{idx}: scene is not an object.")
            continue

        start = scene.get("start_time")
        end = scene.get("end_time")
        duration = scene.get("duration")
        scene_id = scene.get("scene_id", f"scene_{idx}")

        if not isinstance(start, (int, float)):
            errors.append(f"{scene_id}: missing/invalid start_time.")
            continue
        if not isinstance(end, (int, float)):
            errors.append(f"{scene_id}: missing/invalid end_time.")
            continue
        if end <= start:
            errors.append(f"{scene_id}: end_time <= start_time.")

        if isinstance(duration, (int, float)):
            delta = abs((end - start) - duration)
            if delta > 0.3:
                errors.append(f"{scene_id}: duration mismatch ({delta:.3f}s).")
        else:
            errors.append(f"{scene_id}: missing/invalid duration.")

        if prev_end is not None and start + 0.1 < prev_end:
            errors.append(f"{scene_id}: overlaps previous scene ({start:.2f} < {prev_end:.2f}).")
        prev_end = max(prev_end or end, end)

        detection = scene.get("detection_signals")
        if not isinstance(detection, dict):
            errors.append(f"{scene_id}: missing detection_signals.")
            continue

        for key in (
            "has_burned_in_subtitles",
            "has_talking_head",
            "has_speaking_screen_edge_case",
            "is_testimony_like",
        ):
            if not isinstance(detection.get(key), bool):
                errors.append(f"{scene_id}: detection_signals.{key} missing/invalid.")
        for key in (
            "burned_in_subtitles_confidence",
            "talking_head_confidence",
            "speaking_screen_edge_case_confidence",
            "testimony_confidence",
        ):
            value = detection.get(key)
            if not isinstance(value, (int, float)) or value < 0 or value > 1:
                errors.append(f"{scene_id}: detection_signals.{key} must be 0..1.")

    return errors


def _render_review_markdown(
    *,
    video: Any,
    analyzed_video_path: str,
    model: str,
    elapsed_seconds: float,
    payload: Optional[dict[str, Any]],
    parse_error: Optional[str],
    validation_errors: list[str],
    persisted_key: Optional[str],
) -> str:
    lines: list[str] = [
        "# Scene Analysis Review",
        "",
        f"- video_id: `{video.id}`",
        f"- filename: `{video.filename}`",
        f"- selected_path: `{video.path}`",
        f"- analyzed_path: `{analyzed_video_path}`",
        f"- model: `{model}`",
        f"- elapsed_seconds: `{elapsed_seconds:.2f}`",
    ]
    if persisted_key:
        lines.append(f"- gcs_persisted_key: `{persisted_key}`")
    lines.append("")

    if parse_error:
        lines.extend(["## Parse Error", "", f"- {parse_error}", ""])
        return "\n".join(lines)

    assert payload is not None
    scenes = payload.get("scenes", [])

    lines.extend(
        [
            "## High-Level",
            "",
            f"- video_id: `{payload.get('video_metadata', {}).get('video_id')}`",
            f"- actual_scene_count: `{len(scenes) if isinstance(scenes, list) else 'n/a'}`",
            "",
        ]
    )

    if validation_errors:
        lines.extend(["## Validation Findings", ""])
        lines.extend(f"- {err}" for err in validation_errors)
        lines.append("")
    else:
        lines.extend(["## Validation Findings", "", "- No structural validation issues detected.", ""])

    if isinstance(scenes, list) and scenes:
        lines.extend(
            [
                "## Scene Preview",
                "",
                "| # | scene_id | start | end | dur | subtitles | talking_head | testimony | visual_summary |",
                "|---|---|---:|---:|---:|---|---|---|---|",
            ]
        )
        for idx, scene in enumerate(scenes[:12], start=1):
            scene_id = scene.get("scene_id", f"scene_{idx}")
            start = scene.get("start_time", "")
            end = scene.get("end_time", "")
            duration = scene.get("duration", "")
            detection = scene.get("detection_signals", {}) if isinstance(scene.get("detection_signals"), dict) else {}
            subtitles = detection.get("has_burned_in_subtitles", "")
            talking = detection.get("has_talking_head", "")
            testimony = detection.get("is_testimony_like", "")
            visual = str(scene.get("visual_summary", "")).replace("|", " ").strip()[:120]
            lines.append(
                f"| {idx} | {scene_id} | {start} | {end} | {duration} | "
                f"{subtitles} | {talking} | {testimony} | {visual} |"
            )
        lines.append("")

    return "\n".join(lines)


async def _analyze_single_video(
    *,
    client: GeminiClient,
    library: VideoLibrary,
    storage: Any,
    company_id: str,
    model: str,
    max_output_tokens: int,
    thinking_budget: Optional[int],
    video: Any,
    run_dir: Path,
    persist_gcs: bool,
) -> dict[str, Any]:
    selected_video_path = str(video.path)
    analyzed_video_path = to_voiceless_path(selected_video_path)
    started = time.perf_counter()

    if analyzed_video_path == selected_video_path:
        return {
            "status": "skipped",
            "video_id": video.id,
            "filename": video.filename,
            "reason": "Cannot derive voiceless path (no '/videos/' segment).",
        }
    if not library.storage.exists(analyzed_video_path):
        return {
            "status": "skipped",
            "video_id": video.id,
            "filename": video.filename,
            "reason": f"Voiceless video missing: {analyzed_video_path}",
        }

    prompt = GEMINI_VIDEO_ANALYSIS_PROMPT.replace("__VIDEO_ID__", video.id)
    content = types.Content(
        role="user",
        parts=[client.get_or_upload_file(analyzed_video_path), types.Part(text=prompt)],
    )
    config: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": _SceneAnalysisResponse.model_json_schema(),
    }
    if max_output_tokens > 0:
        config["max_output_tokens"] = max_output_tokens
    if thinking_budget is not None:
        config["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

    parse_error: Optional[str] = None
    parsed: Optional[dict[str, Any]] = None
    raw_text = ""
    persisted_key: Optional[str] = None
    validation_errors: list[str] = []
    soft_cap_warnings: list[str] = []

    try:
        response = await client.client.aio.models.generate_content(
            model=model,
            contents=content,
            config=config,
        )
        raw_text = response.text or ""
        parsed, parse_error = _parse_json_response(raw_text)
        if parsed is not None:
            parsed, normalization_error = _normalize_scene_analysis_payload(parsed, video.id)
            if normalization_error:
                parse_error = normalization_error
            if parsed is not None:
                parsed.setdefault("video_metadata", {})
                parsed["video_metadata"]["video_id"] = video.id
                soft_cap_warnings = _soft_cap_scene_end_times(
                    parsed,
                    video_duration=float(video.duration),
                    cap_threshold_seconds=_SOFT_END_CLAMP_SECONDS,
                )
                validation_errors = list(soft_cap_warnings)
                validation_errors.extend(_validate_scenes(parsed))
                if persist_gcs:
                    write_video_scene_analysis(storage, company_id, video.id, parsed)
                    persisted_key = f"companies/{company_id}/scene_analysis/videos/{video.id}.json"
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "status": "failed",
            "video_id": video.id,
            "filename": video.filename,
            "selected_video_path": selected_video_path,
            "analyzed_video_path": analyzed_video_path,
            "elapsed_seconds": elapsed,
            "error": str(exc),
        }

    elapsed = time.perf_counter() - started
    run_dir.mkdir(parents=True, exist_ok=True)
    request_payload = {
        "company_id": company_id,
        "video_id": video.id,
        "video_filename": video.filename,
        "selected_video_path": selected_video_path,
        "analyzed_video_path": analyzed_video_path,
        "model": model,
        "max_output_tokens": max_output_tokens,
        "thinking_budget": "unlimited" if thinking_budget is None else thinking_budget,
    }
    (run_dir / "request.json").write_text(json.dumps(request_payload, indent=2), encoding="utf-8")
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "response_raw.txt").write_text(raw_text, encoding="utf-8")
    if parsed is not None:
        (run_dir / "response.json").write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    review = _render_review_markdown(
        video=video,
        analyzed_video_path=analyzed_video_path,
        model=model,
        elapsed_seconds=elapsed,
        payload=parsed,
        parse_error=parse_error,
        validation_errors=validation_errors,
        persisted_key=persisted_key,
    )
    (run_dir / "review.md").write_text(review, encoding="utf-8")

    status = "success"
    if parse_error:
        status = "parse_error"
    elif validation_errors:
        status = "success_with_validation_warnings"

    return {
        "status": status,
        "video_id": video.id,
        "filename": video.filename,
        "selected_video_path": selected_video_path,
        "analyzed_video_path": analyzed_video_path,
        "elapsed_seconds": elapsed,
        "parse_error": parse_error,
        "validation_errors": validation_errors,
        "persisted_key": persisted_key,
        "run_dir": str(run_dir),
        "parsed_payload": parsed,
    }


def _build_run_report(
    *,
    company_name: str,
    company_id: str,
    model: str,
    all_videos: bool,
    selected_count: int,
    results: list[dict[str, Any]],
    index_payload: Optional[dict[str, Any]],
    index_warnings: list[str],
    index_persisted: bool,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    failed_overview = _build_failed_overview(results)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_name": company_name,
        "company_id": company_id,
        "model": model,
        "mode": "all_videos" if all_videos else "single_video",
        "selected_videos": selected_count,
        "status_counts": status_counts,
        "failed_overview": failed_overview,
        "results": results,
    }
    if index_payload is not None:
        report["index"] = {
            "counts": index_payload.get("counts", {}),
            "warnings": index_warnings,
            "persisted_to_gcs": index_persisted,
        }
    return report


def _build_failed_overview(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    examples_by_reason: dict[str, list[str]] = {}
    affected_videos: list[str] = []

    def _record_reason(reason_text: str, video_id: str) -> None:
        reason = (reason_text or "").strip() or "unknown"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        examples = examples_by_reason.setdefault(reason, [])
        if len(examples) < 5 and video_id not in examples:
            examples.append(video_id)

    for row in results:
        status = str(row.get("status") or "unknown")
        if status in {"success", "success_with_validation_warnings"}:
            continue
        by_status[status] = by_status.get(status, 0) + 1

        video_id = str(row.get("video_id") or "unknown_video")
        if video_id not in affected_videos:
            affected_videos.append(video_id)

        if row.get("error"):
            _record_reason(str(row["error"]), video_id)
        elif row.get("parse_error"):
            _record_reason(str(row["parse_error"]), video_id)
        elif row.get("reason"):
            _record_reason(str(row["reason"]), video_id)
        else:
            _record_reason("unknown", video_id)

    return {
        "total_non_success": sum(by_status.values()),
        "by_status": by_status,
        "by_reason": by_reason,
        "examples_by_reason": examples_by_reason,
        "affected_video_ids": affected_videos,
    }


def _render_run_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scene Analysis Batch Report",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- company: `{report.get('company_name')} ({report.get('company_id')})`",
        f"- model: `{report.get('model')}`",
        f"- mode: `{report.get('mode')}`",
        f"- selected_videos: `{report.get('selected_videos')}`",
        "",
        "## Status Counts",
        "",
    ]
    status_counts = report.get("status_counts", {})
    for key in sorted(status_counts):
        lines.append(f"- {key}: {status_counts[key]}")
    lines.append("")

    failed_overview = report.get("failed_overview", {})
    if isinstance(failed_overview, dict):
        total_non_success = int(failed_overview.get("total_non_success") or 0)
        lines.extend(["## Failed States Overview", "", f"- total_non_success: `{total_non_success}`"])
        by_status = failed_overview.get("by_status", {})
        if isinstance(by_status, dict) and by_status:
            for key in sorted(by_status):
                lines.append(f"- status.{key}: {by_status[key]}")
        by_reason = failed_overview.get("by_reason", {})
        if isinstance(by_reason, dict) and by_reason:
            lines.append("- top_reasons:")
            for reason, count in sorted(by_reason.items(), key=lambda item: item[1], reverse=True)[:10]:
                lines.append(f"  - {count}x {reason}")
        affected = failed_overview.get("affected_video_ids", [])
        if isinstance(affected, list) and affected:
            lines.append(f"- affected_video_ids_count: `{len(affected)}`")
        lines.append("")

    index = report.get("index")
    if isinstance(index, dict):
        lines.extend(["## Index Build", ""])
        counts = index.get("counts", {})
        for key in sorted(counts):
            lines.append(f"- {key}: {counts[key]}")
        lines.append(f"- persisted_to_gcs: `{index.get('persisted_to_gcs')}`")
        warnings = index.get("warnings", [])
        if warnings:
            lines.append("- warnings:")
            for warning in warnings[:30]:
                lines.append(f"  - {warning}")
        lines.append("")

    lines.extend(["## Video Results", ""])
    lines.append("| video_id | status | elapsed_seconds | detail |")
    lines.append("|---|---|---:|---|")
    for result in report.get("results", []):
        detail = (
            result.get("reason")
            or result.get("error")
            or result.get("parse_error")
            or result.get("persisted_key")
            or ""
        )
        detail = str(detail).replace("|", " ")[:120]
        elapsed = result.get("elapsed_seconds")
        elapsed_text = f"{float(elapsed):.2f}" if isinstance(elapsed, (int, float)) else ""
        lines.append(
            f"| {result.get('video_id')} | {result.get('status')} | {elapsed_text} | {detail} |"
        )
    lines.append("")
    return "\n".join(lines)


async def _run() -> int:
    _load_env()
    args = _parse_args()
    if args.all_videos and args.video_id:
        raise ValueError("Use either --video-id or --all-videos, not both.")

    company_id = args.company_id or _resolve_company_id(args.company_name)
    thinking_budget = _parse_thinking_budget(args.thinking_budget)
    concurrency = max(1, int(args.concurrency or 1))

    library = VideoLibrary(default_config, company_id=company_id)
    selected_videos = _select_videos(
        library=library,
        video_id=args.video_id,
        seed=args.seed,
        all_videos=args.all_videos,
        limit=args.limit,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root = args.output_dir / (
        f"{ts}_{company_id}_all" if args.all_videos else f"{ts}_{selected_videos[0].id}"
    )
    run_root.mkdir(parents=True, exist_ok=True)

    client = GeminiClient(default_config)
    client.use_vertexai = True
    storage = get_storage_client(default_config)

    results: list[dict[str, Any]] = []
    parsed_by_video_id: dict[str, dict[str, Any]] = {}

    async def _process_video(idx: int, video: Any, semaphore: asyncio.Semaphore) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
        async with semaphore:
            print(f"[{idx}/{len(selected_videos)}] Analyzing {video.id} ({video.filename})")
            video_dir = run_root / video.id
            result = await _analyze_single_video(
                client=client,
                library=library,
                storage=storage,
                company_id=company_id,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
                thinking_budget=thinking_budget,
                video=video,
                run_dir=video_dir,
                persist_gcs=args.persist_gcs,
            )
            serializable_result = {k: v for k, v in result.items() if k != "parsed_payload"}
            parsed_payload = result.get("parsed_payload") if result.get("parsed_payload") else None
            return serializable_result, parsed_payload

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _process_video(idx, video, semaphore)
        for idx, video in enumerate(selected_videos, start=1)
    ]
    task_results = await asyncio.gather(*tasks)
    for (serializable_result, parsed_payload), video in zip(task_results, selected_videos):
        results.append(serializable_result)
        if parsed_payload:
            parsed_by_video_id[video.id] = parsed_payload

    index_payload: Optional[dict[str, Any]] = None
    index_warnings: list[str] = []
    index_persisted = False

    if args.build_index:
        all_videos = _all_gcs_videos(library)
        analysis_by_video_id: dict[str, dict[str, Any]] = dict(parsed_by_video_id)
        for video in all_videos:
            if video.id in analysis_by_video_id:
                continue
            payload = read_video_scene_analysis(storage, company_id, video.id)
            if payload:
                analysis_by_video_id[video.id] = payload

        index_payload, index_warnings = build_vo_scene_index(
            company_id=company_id,
            videos=all_videos,
            scene_analysis_by_video_id=analysis_by_video_id,
        )
        (run_root / "index_vo_v1.json").write_text(
            json.dumps(index_payload, indent=2),
            encoding="utf-8",
        )
        if index_warnings:
            (run_root / "index_warnings.json").write_text(
                json.dumps(index_warnings, indent=2),
                encoding="utf-8",
            )
        if args.persist_gcs:
            write_scene_index(storage, company_id, index_payload)
            index_persisted = True

    report = _build_run_report(
        company_name=args.company_name,
        company_id=company_id,
        model=args.model,
        all_videos=args.all_videos,
        selected_count=len(selected_videos),
        results=results,
        index_payload=index_payload,
        index_warnings=index_warnings,
        index_persisted=index_persisted,
    )

    (run_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_root / "report.md").write_text(_render_run_report_markdown(report), encoding="utf-8")

    print("")
    print("Scene analysis run complete.")
    print(f"Company: {args.company_name} ({company_id})")
    print(f"Videos selected: {len(selected_videos)}")
    print(f"Concurrency: {concurrency}")
    print(f"Model: {args.model}")
    print(f"Artifacts: {run_root}")
    if args.persist_gcs:
        print("Per-video successful analyses were persisted to GCS.")
    if args.build_index:
        where = "GCS and local" if index_persisted else "local artifacts only"
        print(f"Index built and written to {where}.")
    failed_overview = report.get("failed_overview", {})
    if isinstance(failed_overview, dict):
        total_non_success = int(failed_overview.get("total_non_success") or 0)
        print(f"Non-success videos: {total_non_success}")
        by_status = failed_overview.get("by_status", {})
        if isinstance(by_status, dict) and by_status:
            for key in sorted(by_status):
                print(f"- {key}: {by_status[key]}")
        by_reason = failed_overview.get("by_reason", {})
        if isinstance(by_reason, dict) and by_reason:
            print("Top failure reasons:")
            for reason, count in sorted(by_reason.items(), key=lambda item: item[1], reverse=True)[:5]:
                print(f"- {count}x {reason}")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

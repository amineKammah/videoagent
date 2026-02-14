"""Helpers for scene-analysis persistence and VO shortlist index building."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from videoagent.models import VideoMetadata
from videoagent.storage import GCSStorageClient

SCENE_ANALYSIS_SCHEMA_VERSION = "vo_v1"


def scene_analysis_video_key(company_id: str, video_id: str) -> str:
    return f"companies/{company_id}/scene_analysis/videos/{video_id}.json"


def scene_analysis_index_key(company_id: str) -> str:
    return f"companies/{company_id}/scene_analysis/index_vo_v1.json"


def to_voiceless_path(path: str) -> str:
    if "/videos/" in path:
        return path.replace("/videos/", "/videos_voiceless/", 1)
    return path


def read_video_scene_analysis(
    storage: GCSStorageClient,
    company_id: str,
    video_id: str,
) -> Optional[dict[str, Any]]:
    key = scene_analysis_video_key(company_id, video_id)
    if not storage.exists(key):
        return None
    try:
        return storage.read_json(key)
    except Exception as exc:
        print(
            "[SceneAnalysisIndex][read_video_scene_analysis] "
            f"Failed to read/decode key={key}: {exc}"
        )
        return None


def write_video_scene_analysis(
    storage: GCSStorageClient,
    company_id: str,
    video_id: str,
    payload: dict[str, Any],
) -> None:
    storage.write_json(scene_analysis_video_key(company_id, video_id), payload)


def read_scene_index(
    storage: GCSStorageClient,
    company_id: str,
) -> Optional[dict[str, Any]]:
    key = scene_analysis_index_key(company_id)
    if not storage.exists(key):
        return None
    try:
        return storage.read_json(key)
    except Exception as exc:
        print(
            "[SceneAnalysisIndex][read_scene_index] "
            f"Failed to read/decode key={key}: {exc}"
        )
        return None


def write_scene_index(
    storage: GCSStorageClient,
    company_id: str,
    payload: dict[str, Any],
) -> None:
    storage.write_json(scene_analysis_index_key(company_id), payload)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scene_exclusion_reasons(scene: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    detection = scene.get("detection_signals")
    if not isinstance(detection, dict):
        return ["missing_detection_signals"]

    if detection.get("has_burned_in_subtitles") is True:
        reasons.append("burned_in_subtitles")
    if detection.get("has_talking_head") is True:
        reasons.append("talking_head")
    if detection.get("has_speaking_screen_edge_case") is True:
        reasons.append("speaking_screen_edge_case")
    if detection.get("is_testimony_like") is True:
        reasons.append("testimony_like")

    return reasons


def _normalize_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
        if len(normalized) >= 5:
            break
    return normalized


def _eligible_scene_card(scene: dict[str, Any], scene_id: str, start: float, end: float) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "start_time": start,
        "end_time": end,
        "duration": max(0.0, end - start),
        "visual_summary": str(scene.get("visual_summary") or "").strip(),
        "semantic_meaning": scene.get("semantic_meaning") if isinstance(scene.get("semantic_meaning"), dict) else {},
        "detection_signals": (
            scene.get("detection_signals")
            if isinstance(scene.get("detection_signals"), dict)
            else {}
        ),
        "searchable_keywords": _normalize_keywords(scene.get("searchable_keywords")),
    }


def _excluded_scene_card(scene_id: str, start: float, end: float, reasons: list[str]) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "start_time": start,
        "end_time": end,
        "reasons": reasons,
    }


def build_vo_scene_index(
    *,
    company_id: str,
    videos: Iterable[VideoMetadata],
    scene_analysis_by_video_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    video_entries: list[dict[str, Any]] = []

    total_videos = 0
    indexed_videos = 0
    missing_videos = 0
    invalid_analyses = 0
    eligible_count = 0
    excluded_count = 0

    for video in videos:
        total_videos += 1
        payload = scene_analysis_by_video_id.get(video.id)
        if not isinstance(payload, dict):
            missing_videos += 1
            warnings.append(f"{video.id}: scene analysis missing.")
            continue

        scenes = payload.get("scenes")
        if not isinstance(scenes, list):
            invalid_analyses += 1
            warnings.append(f"{video.id}: scene analysis has invalid 'scenes'.")
            continue

        eligible_scenes: list[dict[str, Any]] = []
        excluded_scenes: list[dict[str, Any]] = []

        for idx, raw_scene in enumerate(scenes, start=1):
            if not isinstance(raw_scene, dict):
                continue
            scene_id = str(raw_scene.get("scene_id") or f"sc_{idx:03d}")
            start = _to_float(raw_scene.get("start_time"))
            end = _to_float(raw_scene.get("end_time"))
            reasons = _scene_exclusion_reasons(raw_scene)
            if end <= start:
                reasons = list(dict.fromkeys([*reasons, "invalid_timing"]))

            if reasons:
                excluded_scenes.append(_excluded_scene_card(scene_id, start, end, reasons))
            else:
                eligible_scenes.append(_eligible_scene_card(raw_scene, scene_id, start, end))

        indexed_videos += 1
        eligible_count += len(eligible_scenes)
        excluded_count += len(excluded_scenes)
        video_entries.append(
            {
                "video_id": video.id,
                "filename": video.filename,
                "video_duration": float(video.duration),
                "eligible_scenes": eligible_scenes,
                "excluded_scenes": excluded_scenes,
            }
        )

    payload = {
        "schema_version": SCENE_ANALYSIS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "videos": video_entries,
        "counts": {
            "videos_total": total_videos,
            "videos_indexed": indexed_videos,
            "videos_missing_analysis": missing_videos,
            "videos_invalid_analysis": invalid_analyses,
            "eligible_scene_count": eligible_count,
            "excluded_scene_count": excluded_count,
        },
    }
    return payload, warnings

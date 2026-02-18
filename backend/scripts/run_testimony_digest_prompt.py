#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from videoagent.testimony_digest_index import (
    TESTIMONY_DIGEST_SCHEMA_VERSION,
    build_testimony_digest_index,
    testimony_digest_video_key,
    write_testimony_digest_index,
    write_testimony_digest_run_summary,
    write_video_testimony_digest,
)
from videoagent.config import default_config
from videoagent.gemini import GeminiClient
from videoagent.storage import get_storage_client


def _load_prompt_template() -> str:
    prompt_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "videoagent"
        / "agent"
        / "testimony_digest_prompt.py"
    )
    spec = importlib.util.spec_from_file_location("testimony_digest_prompt_module", prompt_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load prompt module from {prompt_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompt = getattr(module, "TESTIMONY_DIGEST_PROMPT", None)
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("TESTIMONY_DIGEST_PROMPT is missing or empty.")
    return prompt


def _normalize_name(value: str) -> str:
    text = (value or "").lower()
    text = text.replace("’", "'").replace(":", "_").replace("：", "_").replace("&", "and")
    text = re.sub(r"\.(mp4|webm|mov|mkv)$", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _estimate_tokens(text: str) -> int:
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return int(math.ceil(len(text) / 4))


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _limit_words(value: Any, max_words: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _extract_json(raw: str) -> Optional[dict[str, Any]]:
    candidate = (raw or "").strip()
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = candidate[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def _to_main_agent_payload(raw_digest: Any, fallback_video_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "video_id": fallback_video_id,
        "testimony_cards": [],
    }
    if not isinstance(raw_digest, dict):
        return payload

    video_id = raw_digest.get("video_id")
    if not video_id:
        video_digest = raw_digest.get("video_digest")
        if isinstance(video_digest, dict):
            video_id = video_digest.get("video_id")
    if isinstance(video_id, str) and video_id.strip():
        payload["video_id"] = video_id.strip()

    cards_raw = raw_digest.get("testimony_cards")
    if not isinstance(cards_raw, list):
        return payload

    cards_out: list[dict[str, Any]] = []
    for card in cards_raw[:5]:
        if not isinstance(card, dict):
            continue

        speaker_raw = card.get("speaker")
        speaker = speaker_raw if isinstance(speaker_raw, dict) else {}
        metrics_raw = card.get("metrics")
        metrics_list = metrics_raw if isinstance(metrics_raw, list) else []
        red_flags_raw = card.get("red_flags")
        red_flags_list = red_flags_raw if isinstance(red_flags_raw, list) else []

        metrics: list[dict[str, str]] = []
        for metric in metrics_list[:2]:
            if not isinstance(metric, dict):
                continue
            metric_name = _limit_words(metric.get("metric"), 6)
            metric_value = _limit_words(metric.get("value"), 8)
            if not metric_name and not metric_value:
                continue
            metrics.append({"metric": metric_name, "value": metric_value})

        testimony_card: dict[str, Any] = {
            "speaker": {
                "name": _limit_words(speaker.get("name"), 6) or None,
                "role": _limit_words(speaker.get("role"), 8) or None,
                "company": _limit_words(speaker.get("company"), 8) or None,
            },
            "proof_claim": _limit_words(card.get("proof_claim"), 16),
            "metrics": metrics,
            "intro_seed": _limit_words(card.get("intro_seed"), 14),
            "evidence_snippet": _limit_words(card.get("evidence_snippet"), 12),
            "red_flags": [_limit_words(flag, 3) for flag in red_flags_list[:4]],
        }
        cards_out.append(testimony_card)

    payload["testimony_cards"] = cards_out
    return payload


def _basename_from_gs_uri(uri: str) -> str:
    text = str(uri or "").strip()
    if text.startswith("gs://"):
        without_scheme = text[5:]
        slash = without_scheme.find("/")
        key = without_scheme[slash + 1 :] if slash != -1 else without_scheme
        name = Path(key).name
        if name:
            return name
    return ""


def _normalize_row(
    *,
    raw_row: dict[str, Any],
    run_dir: Path,
    request_payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    video_id = str(raw_row.get("video_id") or "").strip()
    if not video_id and request_payload is not None:
        video_id = str(request_payload.get("video_id") or "").strip()

    filename = str(raw_row.get("filename") or "").strip()
    if not filename and request_payload is not None:
        filename = str(request_payload.get("video_filename") or "").strip()

    selected_video_path = str(raw_row.get("selected_video_path") or "").strip()
    if not selected_video_path and request_payload is not None:
        selected_video_path = str(request_payload.get("selected_video_path") or "").strip()

    analyzed_video_path = raw_row.get("analyzed_video_path")
    if analyzed_video_path is None and request_payload is not None:
        analyzed_video_path = request_payload.get("analyzed_video_path")

    if not filename and selected_video_path:
        filename = _basename_from_gs_uri(selected_video_path)

    response_path = run_dir / video_id / "response.json" if video_id else None
    response_exists = bool(response_path and response_path.exists())

    status = str(raw_row.get("status") or "").strip().lower()
    if not status:
        status = "success" if response_exists else "failed"

    normalized: dict[str, Any] = {
        "status": status,
        "video_id": video_id,
        "filename": filename,
        "selected_video_path": selected_video_path,
        "analyzed_video_path": analyzed_video_path,
        "source_run_dir": str(run_dir),
        "source_run_name": run_dir.name,
        "response_path": str(response_path) if response_path is not None else "",
    }
    return normalized


def _row_rank(row: dict[str, Any]) -> tuple[int, str, int]:
    status_score = 1 if str(row.get("status")) == "success" else 0
    run_name = str(row.get("source_run_name") or "")
    has_filename = 1 if str(row.get("filename") or "").strip() else 0
    return (status_score, run_name, has_filename)


def _response_path_for_row(*, row: dict[str, Any], fallback_run_dir: Path) -> Path:
    explicit = str(row.get("response_path") or "").strip()
    if explicit:
        return Path(explicit)
    source_run_dir = str(row.get("source_run_dir") or "").strip()
    video_id = str(row.get("video_id") or "").strip()
    if source_run_dir and video_id:
        return Path(source_run_dir) / video_id / "response.json"
    return fallback_run_dir / video_id / "response.json"


def _load_rows_from_run_dir(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report_path = run_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        rows = [
            _normalize_row(raw_row=row, run_dir=run_dir)
            for row in report.get("results", [])
            if isinstance(row, dict)
        ]
        metadata = {
            "company_name": report.get("company_name"),
            "company_id": report.get("company_id"),
            "mode": report.get("mode"),
            "source": "report_json",
        }
        return rows, metadata

    rows: list[dict[str, Any]] = []
    company_id: Optional[str] = None
    for request_path in sorted(run_dir.glob("*/request.json")):
        try:
            request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        video_id = str(request_payload.get("video_id") or request_path.parent.name)
        video_filename = str(request_payload.get("video_filename") or "")
        selected_video_path = str(request_payload.get("selected_video_path") or "")
        if not company_id:
            company_id = str(request_payload.get("company_id") or "") or None

        response_exists = (request_path.parent / "response.json").exists()
        rows.append(
            _normalize_row(
                raw_row={
                    "status": "success" if response_exists else "failed",
                    "video_id": video_id,
                    "filename": video_filename,
                    "selected_video_path": selected_video_path,
                    "analyzed_video_path": request_payload.get("analyzed_video_path"),
                },
                run_dir=run_dir,
                request_payload=request_payload,
            )
        )

    metadata = {
        "company_name": None,
        "company_id": company_id,
        "mode": "all_videos",
        "source": "request_scan",
    }
    return rows, metadata


def _load_rows_for_company(
    *,
    scene_analysis_root: Path,
    company_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_video_id: dict[str, dict[str, Any]] = {}
    scanned_request_files = 0
    matched_request_files = 0

    for request_path in sorted(scene_analysis_root.glob("*/*/request.json")):
        scanned_request_files += 1
        run_dir = request_path.parent.parent
        try:
            request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        request_company_id = str(request_payload.get("company_id") or "").strip()
        if request_company_id != company_id:
            continue
        matched_request_files += 1

        normalized = _normalize_row(
            raw_row={},
            run_dir=run_dir,
            request_payload=request_payload,
        )
        video_id = str(normalized.get("video_id") or "").strip()
        if not video_id:
            continue

        previous = rows_by_video_id.get(video_id)
        if previous is None or _row_rank(normalized) > _row_rank(previous):
            rows_by_video_id[video_id] = normalized

    rows = sorted(rows_by_video_id.values(), key=lambda row: str(row.get("video_id") or ""))
    metadata = {
        "company_name": None,
        "company_id": company_id,
        "mode": "company_aggregate_all_runs",
        "source": "request_scan_all_runs",
        "scene_analysis_root": str(scene_analysis_root),
        "scanned_request_files": scanned_request_files,
        "matched_request_files": matched_request_files,
        "deduped_video_ids": len(rows),
    }
    return rows, metadata


def _map_video_to_transcript(
    *,
    report_rows: list[dict[str, Any]],
    transcripts_dir: Path,
) -> dict[str, Path]:
    all_transcripts = list(transcripts_dir.glob("*.json"))
    normalized_to_paths: dict[str, list[Path]] = {}
    for path in all_transcripts:
        normalized_to_paths.setdefault(_normalize_name(path.stem), []).append(path)

    out: dict[str, Path] = {}
    for row in report_rows:
        if row.get("status") != "success":
            continue
        video_id = str(row.get("video_id") or "")
        filename = str(row.get("filename") or "")
        if not video_id or not filename:
            continue

        key = _normalize_name(Path(filename).stem)
        candidates = normalized_to_paths.get(key, [])
        if not candidates:
            candidates = [
                p
                for p in all_transcripts
                if _normalize_name(p.stem).startswith(key)
                or key.startswith(_normalize_name(p.stem))
            ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda p: (abs(len(_normalize_name(p.stem)) - len(key)), len(p.name))
        )
        out[video_id] = candidates[0]
    return out


def _gcs_key_from_uri(uri: str) -> Optional[str]:
    text = str(uri or "").strip()
    if not text.startswith("gs://"):
        return None
    without_scheme = text[5:]
    slash = without_scheme.find("/")
    if slash == -1:
        return None
    return without_scheme[slash + 1 :]


def _transcript_key_from_video_uri(video_uri: str) -> Optional[str]:
    key = _gcs_key_from_uri(video_uri)
    if not key:
        return None
    if "/videos/" not in key:
        return None
    replaced = key.replace("/videos/", "/transcripts/", 1)
    suffix_path = Path(replaced)
    return str(suffix_path.with_suffix(".json").as_posix())


def _load_transcript_payload(
    *,
    row: dict[str, Any],
    local_transcript_path: Optional[Path],
    storage: Optional[Any],
) -> Optional[dict[str, Any]]:
    if local_transcript_path is not None and local_transcript_path.exists():
        try:
            return json.loads(local_transcript_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if storage is None:
        return None

    video_uri = str(row.get("selected_video_path") or "")
    transcript_key = _transcript_key_from_video_uri(video_uri)
    if transcript_key and storage.exists(transcript_key):
        try:
            return storage.read_json(transcript_key)
        except Exception:
            return None
    return None


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_end >= b_start and a_start <= b_end


def _scene_payload_with_transcript(
    *,
    response_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    segments = transcript_payload.get("segments", [])
    transcript_segments: list[tuple[float, float, str]] = []
    for seg in segments:
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        text = str(seg.get("text", "")).strip()
        transcript_segments.append((start, end, text))

    scenes: list[dict[str, Any]] = []
    for scene in response_payload.get("scenes", []):
        try:
            start_time = float(scene.get("start_time", 0.0))
            end_time = float(scene.get("end_time", 0.0))
            duration = float(scene.get("duration", max(0.0, end_time - start_time)))
        except Exception:
            continue

        overlapped_text_parts: list[str] = []
        for seg_start, seg_end, seg_text in transcript_segments:
            if not seg_text:
                continue
            if _overlaps(seg_start, seg_end, start_time, end_time):
                overlapped_text_parts.append(seg_text)
        transcript_text = " ".join(overlapped_text_parts).strip()

        scenes.append(
            {
                "scene_id": scene.get("scene_id"),
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "visual_summary": scene.get("visual_summary"),
                "semantic_meaning": scene.get("semantic_meaning", {}),
                "detection_signals": scene.get("detection_signals", {}),
                "searchable_keywords": scene.get("searchable_keywords", []),
                "transcript_text": transcript_text,
            }
        )
    return scenes


def _pick_default_video_ids(
    *,
    fallback_run_dir: Path,
    report_rows: list[dict[str, Any]],
    video_to_transcript: dict[str, Path],
    sample_count: int,
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for row in report_rows:
        if row.get("status") != "success":
            continue
        video_id = str(row.get("video_id") or "")
        if video_id not in video_to_transcript:
            continue
        response_path = _response_path_for_row(row=row, fallback_run_dir=fallback_run_dir)
        if not response_path.exists():
            continue
        payload = json.loads(response_path.read_text(encoding="utf-8"))
        count = 0
        for scene in payload.get("scenes", []):
            detection = scene.get("detection_signals", {}) or {}
            if detection.get("is_testimony_like") is True:
                count += 1
        if count > 0:
            scored.append((count, video_id))
    scored.sort(reverse=True)
    return [video_id for _, video_id in scored[:sample_count]]


@dataclass
class _RunResult:
    video_id: str
    filename: str
    prompt_tokens_actual: Optional[int]
    output_tokens_actual: Optional[int]
    input_tokens_est: int
    digest_tokens_est: int
    full_transcript_tokens_est: int
    testimony_cards: int
    main_agent_payload: dict[str, Any]


def _to_persisted_digest_payload(
    *,
    company_id: str,
    model: str,
    generated_at: str,
    row: dict[str, Any],
    result: _RunResult,
) -> dict[str, Any]:
    response_path = str(row.get("response_path") or "").strip()
    source_run_name = str(row.get("source_run_name") or "").strip()
    payload: dict[str, Any] = {
        "schema_version": TESTIMONY_DIGEST_SCHEMA_VERSION,
        "generated_at": generated_at,
        "company_id": company_id,
        "video_id": result.video_id,
        "filename": result.filename,
        "model": model,
        "prompt_name": "TESTIMONY_DIGEST_PROMPT",
        "digest_tokens_est": result.digest_tokens_est,
        "testimony_cards": result.main_agent_payload.get("testimony_cards", []),
        "source": {
            "scene_analysis_response_path": response_path or None,
            "scene_analysis_run": source_run_name or None,
            "selected_video_path": str(row.get("selected_video_path") or "").strip() or None,
        },
    }
    return payload


async def _run_one(
    *,
    fallback_run_dir: Path,
    output_dir: Path,
    row: dict[str, Any],
    transcript_payload: dict[str, Any],
    model: str,
) -> _RunResult:
    video_id = str(row["video_id"])
    filename = str(row["filename"])

    response_path = _response_path_for_row(row=row, fallback_run_dir=fallback_run_dir)
    response_payload = json.loads(response_path.read_text(encoding="utf-8"))

    has_testimony_scene = any(
        (scene.get("detection_signals", {}) or {}).get("is_testimony_like") is True
        for scene in response_payload.get("scenes", [])
    )

    full_transcript_text = " ".join(
        str(seg.get("text", "")).strip()
        for seg in transcript_payload.get("segments", [])
        if str(seg.get("text", "")).strip()
    )

    if not has_testimony_scene:
        main_agent_payload = {"video_id": video_id, "testimony_cards": []}
        digest_text = _compact_json(main_agent_payload)
        per_video_dir = output_dir / video_id
        per_video_dir.mkdir(parents=True, exist_ok=True)
        (per_video_dir / "input_payload.json").write_text(
            _compact_json(
                {
                    "video_id": video_id,
                    "filename": filename,
                    "video_duration_seconds": response_payload.get("video_duration"),
                    "scenes": [],
                }
            ),
            encoding="utf-8",
        )
        (per_video_dir / "prompt.txt").write_text(
            "Skipped LLM call: no testimony-like scenes detected in scene analysis.",
            encoding="utf-8",
        )
        (per_video_dir / "response_raw.txt").write_text("", encoding="utf-8")
        (per_video_dir / "digest.json").write_text(
            json.dumps(main_agent_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (per_video_dir / "main_agent_payload.json").write_text(
            json.dumps(main_agent_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (per_video_dir / "main_agent_payload.min.json").write_text(
            digest_text,
            encoding="utf-8",
        )
        return _RunResult(
            video_id=video_id,
            filename=filename,
            prompt_tokens_actual=0,
            output_tokens_actual=0,
            input_tokens_est=0,
            digest_tokens_est=_estimate_tokens(digest_text),
            full_transcript_tokens_est=_estimate_tokens(full_transcript_text),
            testimony_cards=0,
            main_agent_payload=main_agent_payload,
        )

    scenes_payload = _scene_payload_with_transcript(
        response_payload=response_payload,
        transcript_payload=transcript_payload,
    )
    input_payload = {
        "video_id": video_id,
        "filename": filename,
        "video_duration_seconds": response_payload.get("video_duration"),
        "scenes": scenes_payload,
    }
    input_json = json.dumps(input_payload, ensure_ascii=False, indent=2)
    prompt = _load_prompt_template() + "\n" + input_json

    client = GeminiClient(default_config)
    client.use_vertexai = True
    response = None
    last_error: Optional[Exception] = None
    for attempt in range(1, 5):
        try:
            response = await client.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt == 4:
                break
            await asyncio.sleep(float(attempt * 2))

    if response is None:
        raise RuntimeError(f"LLM request failed after retries: {last_error}")

    raw_text = response.text or ""
    digest_json = _extract_json(raw_text)
    if digest_json is None:
        digest_json = {"video_id": video_id, "testimony_cards": []}
    main_agent_payload = _to_main_agent_payload(digest_json, video_id)

    prompt_tokens_actual = None
    output_tokens_actual = None
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens_actual = getattr(usage, "prompt_token_count", None)
        output_tokens_actual = getattr(usage, "candidates_token_count", None)

    digest_text = _compact_json(main_agent_payload)
    testimony_cards = len(main_agent_payload.get("testimony_cards", []))

    per_video_dir = output_dir / video_id
    per_video_dir.mkdir(parents=True, exist_ok=True)
    (per_video_dir / "input_payload.json").write_text(input_json, encoding="utf-8")
    (per_video_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (per_video_dir / "response_raw.txt").write_text(raw_text, encoding="utf-8")
    (per_video_dir / "digest.json").write_text(
        json.dumps(digest_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (per_video_dir / "main_agent_payload.json").write_text(
        json.dumps(main_agent_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (per_video_dir / "main_agent_payload.min.json").write_text(
        digest_text,
        encoding="utf-8",
    )

    return _RunResult(
        video_id=video_id,
        filename=filename,
        prompt_tokens_actual=prompt_tokens_actual,
        output_tokens_actual=output_tokens_actual,
        input_tokens_est=_estimate_tokens(prompt),
        digest_tokens_est=_estimate_tokens(digest_text),
        full_transcript_tokens_est=_estimate_tokens(full_transcript_text),
        testimony_cards=testimony_cards,
        main_agent_payload=main_agent_payload,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run testimony digest prompt on selected videos.")
    parser.add_argument(
        "--run-dir",
        default="output/scene_analysis_reviews/20260213_183633_3f7f5c7a-b113-46de-a73b-5e20a6b9f33e_all",
        help="Scene-analysis run directory containing report.json and per-video response.json files.",
    )
    parser.add_argument(
        "--transcripts-dir",
        default="assets/normalized_transcripts",
        help="Directory containing transcript JSON files.",
    )
    parser.add_argument(
        "--video-ids",
        default="",
        help="Comma-separated list of video IDs to run. If omitted, auto-select by testimony density.",
    )
    parser.add_argument("--sample-count", type=int, default=3, help="Auto-select count when --video-ids is omitted.")
    parser.add_argument(
        "--all-successful",
        action="store_true",
        help="Run all successful videos from the selected run directory.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Maximum number of videos to process concurrently.",
    )
    parser.add_argument(
        "--company-id",
        default="",
        help=(
            "If provided, aggregate scene-analysis artifacts across all run dirs under "
            "--scene-analysis-root and dedupe by video_id."
        ),
    )
    parser.add_argument(
        "--scene-analysis-root",
        default="output/scene_analysis_reviews",
        help="Root directory containing scene-analysis run folders (used with --company-id).",
    )
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model name.")
    parser.add_argument(
        "--output-root",
        default="output/testimony_digest_runs",
        help="Output directory root for prompt run artifacts.",
    )
    parser.add_argument(
        "--persist-gcs",
        action="store_true",
        help="Persist per-video testimony digest JSON to GCS.",
    )
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="Build testimony digest index JSON; writes to GCS only when --persist-gcs is set.",
    )
    args = parser.parse_args()

    transcripts_dir = Path(args.transcripts_dir)
    company_id = str(args.company_id).strip()
    if company_id:
        scene_analysis_root = Path(args.scene_analysis_root)
        report_rows, run_metadata = _load_rows_for_company(
            scene_analysis_root=scene_analysis_root,
            company_id=company_id,
        )
        fallback_run_dir = scene_analysis_root
        run_reference = scene_analysis_root
    else:
        run_dir = Path(args.run_dir)
        report_rows, run_metadata = _load_rows_from_run_dir(run_dir)
        fallback_run_dir = run_dir
        run_reference = run_dir
    resolved_company_id = (
        company_id
        or str(run_metadata.get("company_id") or "").strip()
    )

    video_to_transcript = _map_video_to_transcript(
        report_rows=report_rows,
        transcripts_dir=transcripts_dir,
    )
    storage: Optional[Any] = None
    storage_init_attempted = False
    storage_init_lock = asyncio.Lock()

    explicit_video_ids = [v.strip() for v in str(args.video_ids).split(",") if v.strip()]
    if explicit_video_ids:
        target_video_ids = explicit_video_ids
    elif args.all_successful:
        target_video_ids = [
            str(row.get("video_id"))
            for row in report_rows
            if row.get("status") == "success" and row.get("video_id")
        ]
    else:
        target_video_ids = _pick_default_video_ids(
            fallback_run_dir=fallback_run_dir,
            report_rows=report_rows,
            video_to_transcript=video_to_transcript,
            sample_count=args.sample_count,
        )

    if not target_video_ids:
        raise RuntimeError("No eligible videos selected. Provide --video-ids explicitly.")

    rows_by_video_id: dict[str, dict[str, Any]] = {}
    for row in report_rows:
        if row.get("status") != "success":
            continue
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            continue
        previous = rows_by_video_id.get(video_id)
        if previous is None or _row_rank(row) > _row_rank(previous):
            rows_by_video_id[video_id] = row

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_root) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[_RunResult] = []
    failures: list[dict[str, str]] = []
    max_concurrency = max(1, int(args.max_concurrency))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _get_storage_client_cached() -> Optional[Any]:
        nonlocal storage, storage_init_attempted
        if storage_init_attempted:
            return storage
        async with storage_init_lock:
            if storage_init_attempted:
                return storage
            storage_init_attempted = True
            try:
                storage = get_storage_client(default_config)
            except Exception:
                storage = None
        return storage

    async def _process_video(video_id: str) -> tuple[str, Optional[_RunResult], Optional[dict[str, str]]]:
        row = rows_by_video_id.get(video_id)
        if row is None:
            print(f"SKIP {video_id}: not found in successful rows.")
            return "skip", None, None
        transcript_payload = _load_transcript_payload(
            row=row,
            local_transcript_path=video_to_transcript.get(video_id),
            storage=None,
        )
        if transcript_payload is None:
            storage_client = await _get_storage_client_cached()
            transcript_payload = _load_transcript_payload(
                row=row,
                local_transcript_path=video_to_transcript.get(video_id),
                storage=storage_client,
            )
        if transcript_payload is None:
            print(f"SKIP {video_id}: transcript payload unavailable (local + GCS).")
            return "skip", None, None
        print(f"RUN {video_id} | {row.get('filename')}")
        try:
            result = await _run_one(
                fallback_run_dir=fallback_run_dir,
                output_dir=output_dir,
                row=row,
                transcript_payload=transcript_payload,
                model=args.model,
            )
            return "result", result, None
        except Exception as exc:
            failure = {
                "video_id": video_id,
                "filename": str(row.get("filename") or ""),
                "error": str(exc),
            }
            print(f"FAIL {video_id}: {exc}")
            return "failure", None, failure

    async def _bounded_process(video_id: str) -> tuple[str, Optional[_RunResult], Optional[dict[str, str]]]:
        async with semaphore:
            return await _process_video(video_id)

    tasks = [asyncio.create_task(_bounded_process(video_id)) for video_id in target_video_ids]
    for task in asyncio.as_completed(tasks):
        status, result, failure = await task
        if status == "result" and result is not None:
            results.append(result)
        elif status == "failure" and failure is not None:
            failures.append(failure)

    order_index = {video_id: idx for idx, video_id in enumerate(target_video_ids)}
    results.sort(key=lambda item: order_index.get(item.video_id, len(order_index)))
    failures.sort(key=lambda item: order_index.get(str(item.get("video_id") or ""), len(order_index)))

    summary_rows: list[dict[str, Any]] = []
    for item in results:
        summary_rows.append(
            {
                "video_id": item.video_id,
                "filename": item.filename,
                "testimony_cards": item.testimony_cards,
                "prompt_tokens_actual": item.prompt_tokens_actual,
                "output_tokens_actual": item.output_tokens_actual,
                "input_tokens_est": item.input_tokens_est,
                "digest_tokens_est": item.digest_tokens_est,
                "full_transcript_tokens_est": item.full_transcript_tokens_est,
                "digest_vs_full_transcript_ratio": (
                    round(item.digest_tokens_est / item.full_transcript_tokens_est, 3)
                    if item.full_transcript_tokens_est > 0
                    else None
                ),
            }
        )

    avg_digest_tokens = (
        sum(item.digest_tokens_est for item in results) / len(results)
        if results
        else 0.0
    )
    avg_prompt_tokens = (
        sum(item.prompt_tokens_actual or 0 for item in results) / len(results)
        if results
        else 0.0
    )
    avg_output_tokens = (
        sum(item.output_tokens_actual or 0 for item in results) / len(results)
        if results
        else 0.0
    )

    success_rows = [row for row in report_rows if row.get("status") == "success"]
    testimony_video_count = 0
    for row in success_rows:
        response_path = _response_path_for_row(row=row, fallback_run_dir=fallback_run_dir)
        if not response_path.exists():
            continue
        payload = json.loads(response_path.read_text(encoding="utf-8"))
        has_testimony = any(
            (scene.get("detection_signals", {}) or {}).get("is_testimony_like") is True
            for scene in payload.get("scenes", [])
        )
        if has_testimony:
            testimony_video_count += 1

    extrapolation = {
        "sample_videos_ran": len(results),
        "avg_digest_tokens_est_per_video": round(avg_digest_tokens, 1),
        "avg_prompt_tokens_actual_per_video": round(avg_prompt_tokens, 1),
        "avg_output_tokens_actual_per_video": round(avg_output_tokens, 1),
        "successful_videos_in_run": len(success_rows),
        "videos_with_any_testimony_like_scene": testimony_video_count,
        "estimated_digest_tokens_all_success_videos": round(avg_digest_tokens * len(success_rows)),
        "estimated_digest_tokens_testimony_videos_only": round(avg_digest_tokens * testimony_video_count),
    }

    summary = {
        "run_dir": str(run_reference),
        "transcripts_dir": str(transcripts_dir),
        "model": args.model,
        "run_metadata": run_metadata,
        "selected_video_ids": target_video_ids,
        "results": summary_rows,
        "failures": failures,
        "extrapolation": extrapolation,
    }

    index_payload: Optional[dict[str, Any]] = None
    index_local_path: Optional[str] = None
    if args.build_index and resolved_company_id:
        index_payload = build_testimony_digest_index(
            company_id=resolved_company_id,
            videos=summary_rows,
            model=args.model,
            prompt_name="TESTIMONY_DIGEST_PROMPT",
            generated_at=_iso_now(),
        )
        index_local = output_dir / "index_td_v1.json"
        index_local.write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        index_local_path = str(index_local)
    elif args.build_index:
        print("SKIP index build: company_id unavailable.")

    gcs_persistence: dict[str, Any] = {
        "requested": bool(args.persist_gcs),
        "build_index_requested": bool(args.build_index),
        "enabled": False,
        "company_id": resolved_company_id or None,
        "videos_persisted": 0,
        "video_errors": [],
        "index_persisted": False,
        "index_key": None,
        "run_summary_persisted": False,
        "run_summary_key": None,
    }

    if args.persist_gcs:
        if not resolved_company_id:
            gcs_persistence["reason"] = "missing_company_id"
        else:
            storage_client = await _get_storage_client_cached()
            if storage_client is None:
                gcs_persistence["reason"] = "storage_unavailable"
            else:
                gcs_persistence["enabled"] = True
                generated_at = _iso_now()
                video_errors: list[dict[str, str]] = []
                videos_persisted = 0
                for item in results:
                    row = rows_by_video_id.get(item.video_id, {})
                    digest_payload = _to_persisted_digest_payload(
                        company_id=resolved_company_id,
                        model=args.model,
                        generated_at=generated_at,
                        row=row,
                        result=item,
                    )
                    key = testimony_digest_video_key(resolved_company_id, item.video_id)
                    try:
                        write_video_testimony_digest(
                            storage_client,
                            resolved_company_id,
                            item.video_id,
                            digest_payload,
                        )
                        videos_persisted += 1
                    except Exception as exc:
                        video_errors.append(
                            {
                                "video_id": item.video_id,
                                "key": key,
                                "error": str(exc),
                            }
                        )

                gcs_persistence["videos_persisted"] = videos_persisted
                gcs_persistence["video_errors"] = video_errors

                if args.build_index and index_payload is not None:
                    try:
                        write_testimony_digest_index(
                            storage_client,
                            resolved_company_id,
                            index_payload,
                        )
                        gcs_persistence["index_persisted"] = True
                        gcs_persistence["index_key"] = f"companies/{resolved_company_id}/testimony_digest/index_td_v1.json"
                    except Exception as exc:
                        gcs_persistence["index_error"] = str(exc)

                summary["gcs_persistence"] = gcs_persistence
                if index_local_path:
                    summary["index_local_path"] = index_local_path
                try:
                    write_testimony_digest_run_summary(
                        storage_client,
                        resolved_company_id,
                        output_dir.name,
                        summary,
                    )
                    gcs_persistence["run_summary_persisted"] = True
                    gcs_persistence["run_summary_key"] = (
                        f"companies/{resolved_company_id}/testimony_digest/runs/{output_dir.name}/summary.json"
                    )
                except Exception as exc:
                    gcs_persistence["run_summary_error"] = str(exc)

    if "gcs_persistence" not in summary:
        summary["gcs_persistence"] = gcs_persistence
    if index_local_path:
        summary["index_local_path"] = index_local_path

    combined_payload = [item.main_agent_payload for item in results]
    (output_dir / "main_agent_payloads.json").write_text(
        json.dumps(combined_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "main_agent_payloads.min.json").write_text(
        _compact_json(combined_payload),
        encoding="utf-8",
    )

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Artifacts: {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())

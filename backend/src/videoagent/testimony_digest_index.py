"""Helpers for testimony-digest persistence and index building."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from videoagent.storage import GCSStorageClient

TESTIMONY_DIGEST_SCHEMA_VERSION = "td_v1"


def testimony_digest_video_key(company_id: str, video_id: str) -> str:
    return f"companies/{company_id}/testimony_digest/videos/{video_id}.json"


def testimony_digest_index_key(company_id: str) -> str:
    return f"companies/{company_id}/testimony_digest/index_td_v1.json"


def testimony_digest_run_summary_key(company_id: str, run_id: str) -> str:
    return f"companies/{company_id}/testimony_digest/runs/{run_id}/summary.json"


def read_video_testimony_digest(
    storage: GCSStorageClient,
    company_id: str,
    video_id: str,
) -> Optional[dict[str, Any]]:
    key = testimony_digest_video_key(company_id, video_id)
    if not storage.exists(key):
        return None
    try:
        return storage.read_json(key)
    except Exception as exc:
        print(
            "[TestimonyDigestIndex][read_video_testimony_digest] "
            f"Failed to read/decode key={key}: {exc}"
        )
        return None


def write_video_testimony_digest(
    storage: GCSStorageClient,
    company_id: str,
    video_id: str,
    payload: dict[str, Any],
) -> None:
    storage.write_json(testimony_digest_video_key(company_id, video_id), payload)


def read_testimony_digest_index(
    storage: GCSStorageClient,
    company_id: str,
) -> Optional[dict[str, Any]]:
    key = testimony_digest_index_key(company_id)
    if not storage.exists(key):
        return None
    try:
        return storage.read_json(key)
    except Exception as exc:
        print(
            "[TestimonyDigestIndex][read_testimony_digest_index] "
            f"Failed to read/decode key={key}: {exc}"
        )
        return None


def write_testimony_digest_index(
    storage: GCSStorageClient,
    company_id: str,
    payload: dict[str, Any],
) -> None:
    storage.write_json(testimony_digest_index_key(company_id), payload)


def write_testimony_digest_run_summary(
    storage: GCSStorageClient,
    company_id: str,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    storage.write_json(testimony_digest_run_summary_key(company_id, run_id), payload)


def build_testimony_digest_index(
    *,
    company_id: str,
    videos: list[dict[str, Any]],
    model: Optional[str] = None,
    prompt_name: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    ts = generated_at or datetime.now(timezone.utc).isoformat()
    sorted_videos = sorted(videos, key=lambda row: str(row.get("video_id") or ""))

    total = len(sorted_videos)
    with_cards = 0
    total_cards = 0
    entries: list[dict[str, Any]] = []

    for row in sorted_videos:
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            continue
        cards = int(row.get("testimony_cards") or 0)
        has_cards = cards > 0
        if has_cards:
            with_cards += 1
        total_cards += max(0, cards)

        entries.append(
            {
                "video_id": video_id,
                "digest_key": testimony_digest_video_key(company_id, video_id),
                "has_testimony_cards": has_cards,
                "testimony_cards_count": cards,
                "digest_tokens_est": int(row.get("digest_tokens_est") or 0),
                "generated_at": ts,
            }
        )

    payload: dict[str, Any] = {
        "schema_version": TESTIMONY_DIGEST_SCHEMA_VERSION,
        "generated_at": ts,
        "company_id": company_id,
        "videos": entries,
        "counts": {
            "videos_total": total,
            "videos_with_testimony_cards": with_cards,
            "videos_without_testimony_cards": max(0, total - with_cards),
            "testimony_cards_total": total_cards,
        },
    }
    if model:
        payload["model"] = model
    if prompt_name:
        payload["prompt_name"] = prompt_name
    return payload

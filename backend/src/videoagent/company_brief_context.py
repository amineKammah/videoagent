"""Strict loader for company brief context in GCS."""
from __future__ import annotations

from typing import Any, Optional

from videoagent.storage import GCSStorageClient


def company_brief_primary_key(company_id: str) -> str:
    return f"companies/{company_id}/company_context/brief.json"


def _limit_words(text: str, max_words: int) -> str:
    words = str(text or "").split()
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def read_company_brief_context(
    storage: GCSStorageClient,
    company_id: str,
    *,
    max_words: int = 1200,
) -> Optional[dict[str, Any]]:
    key = company_brief_primary_key(company_id)
    if not storage.exists(key):
        return None

    try:
        payload = storage.read_json(key)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    content = payload.get("content")
    if not isinstance(content, str):
        return None
    normalized = _limit_words(content.strip(), max_words=max_words)
    if not normalized:
        return None

    return {
        "source_key": key,
        "format": "json",
        "content": normalized,
        "word_count": len(normalized.split()),
    }

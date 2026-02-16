"""
Persistence and storage handling for the Video Agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from videoagent.db.connection import get_db_context
from videoagent.db.models import (
    SessionBrief,
    SessionChatMessage,
    SessionEvent,
    SessionStoryboard,
)
from videoagent.models import VideoBrief
from videoagent.story import _StoryboardScene


def _parse_timestamp(text: str) -> float:
    """Parse MM:SS.sss or HH:MM:SS.sss timestamp format to seconds."""
    text = text.strip()
    if not text:
        raise ValueError("Empty timestamp.")
    parts = text.split(":")
    if len(parts) == 2:
        hours_value = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
        if not hours.isdigit():
            raise ValueError(f"Invalid hours value in '{text}'.")
        hours_value = int(hours)
    else:
        raise ValueError(f"Expected MM:SS.sss or HH:MM:SS.sss format, got '{text}'.")
    try:
        minutes_value = int(minutes)
    except ValueError as exc:
        raise ValueError(f"Invalid minutes value in '{text}'.") from exc
    if "." not in seconds:
        raise ValueError(f"Expected MM:SS.sss or HH:MM:SS.sss format, got '{text}'.")
    seconds_main, millis_text = seconds.split(".", 1)
    if not (seconds_main.isdigit() and len(seconds_main) == 2):
        raise ValueError(f"Invalid seconds value in '{text}'.")
    if not (millis_text.isdigit() and len(millis_text) == 3):
        raise ValueError(f"Invalid milliseconds value in '{text}'.")
    try:
        seconds_value = int(seconds_main) + (int(millis_text) / 1000.0)
    except ValueError as exc:
        raise ValueError(f"Invalid seconds value in '{text}'.") from exc
    if (
        hours_value < 0
        or minutes_value < 0
        or minutes_value >= 60 and len(parts) == 3
        or seconds_value < 0
        or seconds_value >= 60
    ):
        raise ValueError(f"Timestamp out of range (MM:SS.sss or HH:MM:SS.sss) in '{text}'.")
    return (hours_value * 3600) + (minutes_value * 60) + seconds_value


@dataclass
class EventStore:
    base_dir: Path
    user_id: Optional[str] = None
    _lock: Lock = field(default_factory=Lock)

    def _session_dir(self, session_id: str, user_id: Optional[str]) -> Path:
        user_scope = user_id or "unknown"
        return self.base_dir / user_scope / session_id

    def _events_path(self, session_id: str, user_id: Optional[str]) -> Path:
        return self._session_dir(session_id, user_id) / "events.jsonl"

    def append(self, session_id: str, event: dict, user_id: Optional[str] = None) -> None:
        payload = dict(event)
        payload.setdefault("ts", datetime.utcnow().isoformat() + "Z")
        event_type = str(payload.get("type") or "event")

        with self._lock, get_db_context() as db:
            db.add(
                SessionEvent(
                    session_id=session_id,
                    user_id=user_id,
                    event_type=event_type,
                    payload=payload,
                    created_at=datetime.utcnow(),
                )
            )

    def read_since(
        self,
        session_id: str,
        cursor: Optional[int],
        user_id: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        cursor_value = int(cursor or 0)

        with self._lock, get_db_context() as db:
            latest_query = db.query(SessionEvent.id).filter(SessionEvent.session_id == session_id)
            if user_id is not None:
                latest_query = latest_query.filter(SessionEvent.user_id == user_id)

            if cursor is None:
                latest_row = latest_query.order_by(SessionEvent.id.desc()).first()
                return [], int(latest_row[0]) if latest_row else 0

            events_query = db.query(SessionEvent).filter(
                SessionEvent.session_id == session_id,
                SessionEvent.id > cursor_value,
            )
            if user_id is not None:
                events_query = events_query.filter(SessionEvent.user_id == user_id)

            rows = events_query.order_by(SessionEvent.id.asc()).all()
            events: list[dict] = []
            next_cursor = cursor_value
            for row in rows:
                payload = dict(row.payload or {})
                if "type" not in payload:
                    payload["type"] = row.event_type
                if "ts" not in payload and row.created_at:
                    payload["ts"] = _to_iso_utc(row.created_at)
                events.append(payload)
                next_cursor = row.id

            return events, next_cursor

    def clear(self, session_id: str, user_id: Optional[str] = None) -> None:
        with self._lock, get_db_context() as db:
            query = db.query(SessionEvent).filter(SessionEvent.session_id == session_id)
            if user_id is not None:
                query = query.filter(SessionEvent.user_id == user_id)
            query.delete(synchronize_session=False)


@dataclass
class StoryboardStore:
    base_dir: Path
    user_id: Optional[str] = None
    _lock: Lock = field(default_factory=Lock)

    def _session_dir(self, session_id: str, user_id: Optional[str]) -> Path:
        user_scope = user_id or "unknown"
        return self.base_dir / user_scope / session_id

    def _storyboard_path(self, session_id: str, user_id: Optional[str]) -> Path:
        # Kept for compatibility with tools that derive session asset directories.
        return self._session_dir(session_id, user_id) / "storyboard.json"

    def load(self, session_id: str, user_id: Optional[str] = None) -> Optional[list[_StoryboardScene]]:
        with self._lock, get_db_context() as db:
            row = db.query(SessionStoryboard).filter(SessionStoryboard.session_id == session_id).first()
            if not row:
                return None
            data = row.scenes or []
        return [_StoryboardScene.model_validate(item) for item in data]

    def save(self, session_id: str, scenes: list[_StoryboardScene], user_id: Optional[str] = None) -> None:
        payload = [scene.model_dump(mode="json") for scene in scenes]
        with self._lock, get_db_context() as db:
            row = db.query(SessionStoryboard).filter(SessionStoryboard.session_id == session_id).first()
            if row:
                row.scenes = payload
                if user_id is not None:
                    row.user_id = user_id
                row.updated_at = datetime.utcnow()
            else:
                db.add(
                    SessionStoryboard(
                        session_id=session_id,
                        user_id=user_id,
                        scenes=payload,
                        updated_at=datetime.utcnow(),
                    )
                )

    def clear(self, session_id: str, user_id: Optional[str] = None) -> None:
        with self._lock, get_db_context() as db:
            db.query(SessionStoryboard).filter(SessionStoryboard.session_id == session_id).delete(
                synchronize_session=False
            )


@dataclass
class BriefStore:
    base_dir: Path
    user_id: Optional[str] = None
    _lock: Lock = field(default_factory=Lock)

    def _session_dir(self, session_id: str, user_id: Optional[str]) -> Path:
        user_scope = user_id or "unknown"
        return self.base_dir / user_scope / session_id

    def _brief_path(self, session_id: str, user_id: Optional[str]) -> Path:
        # Kept for compatibility with tooling that expects a deterministic session directory.
        return self._session_dir(session_id, user_id) / "brief.json"

    def load(self, session_id: str, user_id: Optional[str] = None) -> Optional[VideoBrief]:
        with self._lock, get_db_context() as db:
            row = db.query(SessionBrief).filter(SessionBrief.session_id == session_id).first()
            if not row:
                return None
            data = row.brief or {}
        return VideoBrief.model_validate(data)

    def save(self, session_id: str, brief: VideoBrief, user_id: Optional[str] = None) -> None:
        payload = brief.model_dump(mode="json")
        with self._lock, get_db_context() as db:
            row = db.query(SessionBrief).filter(SessionBrief.session_id == session_id).first()
            if row:
                row.brief = payload
                if user_id is not None:
                    row.user_id = user_id
                row.updated_at = datetime.utcnow()
            else:
                db.add(
                    SessionBrief(
                        session_id=session_id,
                        user_id=user_id,
                        brief=payload,
                        updated_at=datetime.utcnow(),
                    )
                )

    def clear(self, session_id: str, user_id: Optional[str] = None) -> None:
        with self._lock, get_db_context() as db:
            db.query(SessionBrief).filter(SessionBrief.session_id == session_id).delete(
                synchronize_session=False
            )


@dataclass
class ChatStore:
    """Persist chat messages for a session."""
    base_dir: Path
    user_id: Optional[str] = None
    _lock: Lock = field(default_factory=Lock)

    def _session_dir(self, session_id: str, user_id: Optional[str]) -> Path:
        user_scope = user_id or "unknown"
        return self.base_dir / user_scope / session_id

    def _chat_path(self, session_id: str, user_id: Optional[str]) -> Path:
        # Kept for compatibility with tooling that expects a deterministic session directory.
        return self._session_dir(session_id, user_id) / "chat.jsonl"

    def append(self, session_id: str, message: dict, user_id: Optional[str] = None) -> None:
        """Append a message to the chat history."""
        payload = dict(message)
        ts_value = _parse_iso_utc(payload.get("timestamp"))
        role = str(payload.get("role") or "assistant")
        content = str(payload.get("content") or "")
        suggested_actions = payload.get("suggested_actions") or []
        if not isinstance(suggested_actions, list):
            suggested_actions = []

        with self._lock, get_db_context() as db:
            db.add(
                SessionChatMessage(
                    session_id=session_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    suggested_actions=suggested_actions,
                    timestamp=ts_value,
                )
            )

    def load(self, session_id: str, user_id: Optional[str] = None) -> list[dict]:
        """Load all messages for a session."""
        with self._lock, get_db_context() as db:
            query = db.query(SessionChatMessage).filter(SessionChatMessage.session_id == session_id)
            if user_id is not None:
                query = query.filter(SessionChatMessage.user_id == user_id)
            rows = query.order_by(SessionChatMessage.id.asc()).all()
            messages = [
                {
                    "role": row.role,
                    "content": row.content,
                    "timestamp": _to_iso_utc(row.timestamp),
                    "suggested_actions": row.suggested_actions or [],
                }
                for row in rows
            ]
        return messages

    def clear(self, session_id: str, user_id: Optional[str] = None) -> None:
        with self._lock, get_db_context() as db:
            query = db.query(SessionChatMessage).filter(SessionChatMessage.session_id == session_id)
            if user_id is not None:
                query = query.filter(SessionChatMessage.user_id == user_id)
            query.delete(synchronize_session=False)


def _to_iso_utc(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + "Z"


def _parse_iso_utc(value: Optional[str]) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError):
        return datetime.utcnow()

"""
Persistence and storage handling for the Video Agent.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

from videoagent.models import VideoBrief
from videoagent.story import _StoryboardScene


def _parse_timestamp(text: str) -> float:
    """Parse MM:SS.sss timestamp format to seconds."""
    text = text.strip()
    if not text:
        raise ValueError("Empty timestamp.")
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected MM:SS.sss format, got '{text}'.")
    minutes, seconds = parts
    try:
        minutes_value = int(minutes)
    except ValueError as exc:
        raise ValueError(f"Invalid minutes value in '{text}'.") from exc
    if "." not in seconds:
        raise ValueError(f"Expected MM:SS.sss format, got '{text}'.")
    seconds_main, millis_text = seconds.split(".", 1)
    if not (seconds_main.isdigit() and len(seconds_main) == 2):
        raise ValueError(f"Invalid seconds value in '{text}'.")
    if not (millis_text.isdigit() and len(millis_text) == 3):
        raise ValueError(f"Invalid milliseconds value in '{text}'.")
    try:
        seconds_value = int(seconds_main) + (int(millis_text) / 1000.0)
    except ValueError as exc:
        raise ValueError(f"Invalid seconds value in '{text}'.") from exc
    if minutes_value < 0 or seconds_value < 0 or seconds_value >= 60:
        raise ValueError(f"Timestamp out of range (MM:SS.sss) in '{text}'.")
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
class BriefStore:
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _brief_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.brief.json"

    def load(self, session_id: str) -> Optional[VideoBrief]:
        path = self._brief_path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return VideoBrief.model_validate(data)

    def save(self, session_id: str, brief: VideoBrief) -> None:
        path = self._brief_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("w", encoding="utf-8") as handle:
            json.dump(brief.model_dump(mode="json"), handle, indent=2)

    def clear(self, session_id: str) -> None:
        path = self._brief_path(session_id)
        if path.exists():
            path.unlink()


@dataclass
class ChatStore:
    """Persist chat messages for a session."""
    base_dir: Path
    _lock: Lock = field(default_factory=Lock)

    def _chat_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.chat.jsonl"

    def append(self, session_id: str, message: dict) -> None:
        """Append a message to the chat history."""
        path = self._chat_path(session_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(message)
        payload.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        with self._lock, path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")

    def load(self, session_id: str) -> list[dict]:
        """Load all messages for a session."""
        path = self._chat_path(session_id)
        if not path.exists():
            return []
        messages = []
        with self._lock, path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return messages

    def clear(self, session_id: str) -> None:
        path = self._chat_path(session_id)
        if path.exists():
            path.unlink()

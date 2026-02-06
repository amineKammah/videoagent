#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from videoagent.db import Base, engine
from videoagent.db.connection import get_db_context
from videoagent.db.models import (
    Session,
    SessionBrief,
    SessionChatMessage,
    SessionEvent,
    SessionStoryboard,
    User,
)
from videoagent.models import VideoBrief
from videoagent.story import _StoryboardScene


@dataclass
class MigrationStats:
    sessions_seen: int = 0
    sessions_created: int = 0
    sessions_skipped_missing_user: int = 0
    storyboards_migrated: int = 0
    briefs_migrated: int = 0
    events_migrated: int = 0
    chats_migrated: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate session JSON/JSONL state files into SQL tables.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=REPO_ROOT / "output" / "agent_sessions",
        help="Root directory containing <user_id>/<session_id> folders.",
    )
    parser.add_argument(
        "--remove-json",
        action="store_true",
        help="Delete JSON/JSONL files after successful migration.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would migrate without writing to the database.",
    )
    return parser.parse_args()


def _parse_iso_utc(value: str | None) -> datetime:
    if not value:
        return _utcnow_naive()
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return _utcnow_naive()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iter_session_dirs(base_dir: Path) -> list[tuple[str, str, Path]]:
    results: list[tuple[str, str, Path]] = []
    if not base_dir.exists():
        return results

    for user_dir in sorted(base_dir.iterdir()):
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        for session_dir in sorted(user_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            results.append((user_id, session_dir.name, session_dir))
    return results


def _maybe_unlink(path: Path, remove_json: bool) -> None:
    if remove_json and path.exists():
        path.unlink()


def main() -> int:
    args = _parse_args()

    Base.metadata.create_all(bind=engine)

    session_dirs = _iter_session_dirs(args.base_dir)
    stats = MigrationStats()

    print(f"Scanning {args.base_dir} ({len(session_dirs)} session folders)...")

    for user_id, session_id, session_dir in session_dirs:
        stats.sessions_seen += 1

        events_path = session_dir / "events.jsonl"
        chat_path = session_dir / "chat.jsonl"
        storyboard_path = session_dir / "storyboard.json"
        brief_path = session_dir / "brief.json"

        with get_db_context() as db:
            session_row = db.query(Session).filter(Session.id == session_id).first()
            if session_row is None:
                user_row = db.query(User).filter(User.id == user_id).first()
                if user_row is None:
                    stats.sessions_skipped_missing_user += 1
                    continue
                if not args.dry_run:
                    session_row = Session(
                        id=session_id,
                        company_id=user_row.company_id,
                        user_id=user_id,
                        has_activity=False,
                    )
                    db.add(session_row)
                stats.sessions_created += 1

            migrated_activity = False

            if storyboard_path.exists():
                exists = db.query(SessionStoryboard).filter(SessionStoryboard.session_id == session_id).first()
                if exists is None:
                    try:
                        raw = json.loads(storyboard_path.read_text(encoding="utf-8"))
                        scenes = [_StoryboardScene.model_validate(item) for item in raw]
                        payload = [scene.model_dump(mode="json") for scene in scenes]
                        if not args.dry_run:
                            db.add(
                                SessionStoryboard(
                                    session_id=session_id,
                                    user_id=user_id,
                                    scenes=payload,
                                    updated_at=_utcnow_naive(),
                                )
                            )
                            _maybe_unlink(storyboard_path, args.remove_json)
                        stats.storyboards_migrated += 1
                        migrated_activity = True
                    except Exception as exc:
                        print(f"[warn] failed storyboard migration {storyboard_path}: {exc}")
                elif args.remove_json and not args.dry_run:
                    _maybe_unlink(storyboard_path, remove_json=True)

            if brief_path.exists():
                exists = db.query(SessionBrief).filter(SessionBrief.session_id == session_id).first()
                if exists is None:
                    try:
                        raw = json.loads(brief_path.read_text(encoding="utf-8"))
                        brief = VideoBrief.model_validate(raw)
                        if not args.dry_run:
                            db.add(
                                SessionBrief(
                                    session_id=session_id,
                                    user_id=user_id,
                                    brief=brief.model_dump(mode="json"),
                                    updated_at=_utcnow_naive(),
                                )
                            )
                            _maybe_unlink(brief_path, args.remove_json)
                        stats.briefs_migrated += 1
                        migrated_activity = True
                    except Exception as exc:
                        print(f"[warn] failed brief migration {brief_path}: {exc}")
                elif args.remove_json and not args.dry_run:
                    _maybe_unlink(brief_path, remove_json=True)

            if events_path.exists():
                has_events = (
                    db.query(SessionEvent.id)
                    .filter(SessionEvent.session_id == session_id)
                    .first()
                    is not None
                )
                if not has_events:
                    migrated_count = 0
                    try:
                        for line in events_path.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            event = json.loads(line)
                            payload = dict(event)
                            payload.setdefault("ts", _utcnow_naive().isoformat() + "Z")
                            event_type = str(payload.get("type") or "event")
                            if not args.dry_run:
                                db.add(
                                    SessionEvent(
                                        session_id=session_id,
                                        user_id=user_id,
                                        event_type=event_type,
                                        payload=payload,
                                        created_at=_parse_iso_utc(str(payload.get("ts", ""))),
                                    )
                                )
                            migrated_count += 1
                        if migrated_count > 0:
                            stats.events_migrated += migrated_count
                            migrated_activity = True
                            if not args.dry_run:
                                _maybe_unlink(events_path, args.remove_json)
                    except Exception as exc:
                        print(f"[warn] failed events migration {events_path}: {exc}")
                elif args.remove_json and not args.dry_run:
                    _maybe_unlink(events_path, remove_json=True)

            if chat_path.exists():
                has_chat = (
                    db.query(SessionChatMessage.id)
                    .filter(SessionChatMessage.session_id == session_id)
                    .first()
                    is not None
                )
                if not has_chat:
                    migrated_count = 0
                    try:
                        for line in chat_path.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            msg = json.loads(line)
                            suggested_actions = msg.get("suggested_actions") or []
                            if not isinstance(suggested_actions, list):
                                suggested_actions = []
                            if not args.dry_run:
                                db.add(
                                    SessionChatMessage(
                                        session_id=session_id,
                                        user_id=user_id,
                                        role=str(msg.get("role") or "assistant"),
                                        content=str(msg.get("content") or ""),
                                        suggested_actions=suggested_actions,
                                        timestamp=_parse_iso_utc(str(msg.get("timestamp", ""))),
                                    )
                                )
                            migrated_count += 1
                        if migrated_count > 0:
                            stats.chats_migrated += migrated_count
                            migrated_activity = True
                            if not args.dry_run:
                                _maybe_unlink(chat_path, args.remove_json)
                    except Exception as exc:
                        print(f"[warn] failed chat migration {chat_path}: {exc}")
                elif args.remove_json and not args.dry_run:
                    _maybe_unlink(chat_path, remove_json=True)

            if migrated_activity and not args.dry_run and session_row is not None:
                session_row.has_activity = True

    print("Migration summary:")
    print(f"  sessions_seen: {stats.sessions_seen}")
    print(f"  sessions_created: {stats.sessions_created}")
    print(f"  sessions_skipped_missing_user: {stats.sessions_skipped_missing_user}")
    print(f"  storyboards_migrated: {stats.storyboards_migrated}")
    print(f"  briefs_migrated: {stats.briefs_migrated}")
    print(f"  events_migrated: {stats.events_migrated}")
    print(f"  chats_migrated: {stats.chats_migrated}")

    if args.dry_run:
        print("Dry run only: no DB rows were written.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

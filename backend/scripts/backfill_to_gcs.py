#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


@dataclass(frozen=True)
class UploadTask:
    local_path: Path
    blob_path: str
    category: str

    @property
    def size(self) -> int:
        return self.local_path.stat().st_size


def _load_env() -> None:
    if load_dotenv is None:
        return
    repo_env = REPO_ROOT / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    else:
        load_dotenv()


class StorageClient:
    def __init__(self, bucket_name: str, expected_location: str | None = None):
        if gcs_storage is None:
            raise RuntimeError(
                "google-cloud-storage is not installed. Install with: pip install google-cloud-storage"
            )
        self.client = gcs_storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.bucket.reload()
        self.location = (self.bucket.location or "").lower()
        if expected_location:
            expected = expected_location.lower()
            if self.location and self.location != expected:
                raise RuntimeError(
                    f"Bucket '{bucket_name}' is in '{self.bucket.location}', expected '{expected_location}'. "
                    "Use a London bucket (europe-west2) or pass --expected-location to match your bucket."
                )

    def exists(self, blob_path: str) -> bool:
        return self.bucket.blob(blob_path).exists()

    def get_size(self, blob_path: str) -> int:
        blob = self.bucket.get_blob(blob_path)
        if not blob:
            return -1
        return int(blob.size or 0)

    def upload(self, blob_path: str, local_path: Path, content_type: str | None = None) -> None:
        blob = self.bucket.blob(blob_path)
        blob.upload_from_filename(str(local_path), content_type=content_type)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guess_content_type(path: Path) -> str | None:
    content_type, _ = mimetypes.guess_type(path.name)
    if content_type:
        return content_type
    ext = path.suffix.lower()
    if ext == ".json":
        return "application/json"
    if ext == ".wav":
        return "audio/wav"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".mp4":
        return "video/mp4"
    return None


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (p for p in root.rglob("*") if p.is_file())


def _build_company_tasks(companies_root: Path, include_generated: bool) -> list[UploadTask]:
    tasks: list[UploadTask] = []
    if not companies_root.exists():
        return tasks

    for company_dir in sorted(companies_root.iterdir()):
        if not company_dir.is_dir():
            continue
        company_id = company_dir.name

        mappings: list[tuple[str, str]] = [
            ("videos", f"companies/{company_id}/videos"),
            ("transcripts", f"companies/{company_id}/transcripts"),
        ]
        if include_generated:
            mappings.append(("generated", f"companies/{company_id}/generated"))

        for local_subdir, remote_prefix in mappings:
            source_root = company_dir / local_subdir
            for local_path in _iter_files(source_root):
                relative_path = local_path.relative_to(source_root).as_posix()
                blob_path = f"{remote_prefix}/{relative_path}"
                tasks.append(
                    UploadTask(
                        local_path=local_path,
                        blob_path=blob_path,
                        category=f"{company_id}:{local_subdir}",
                    )
                )

    return tasks


def _load_session_company_map(sessions_db_path: Path) -> dict[str, str]:
    session_company: dict[str, str] = {}
    if not sessions_db_path.exists():
        return session_company

    try:
        with sqlite3.connect(sessions_db_path) as conn:
            rows = conn.execute(
                "SELECT id, company_id FROM sessions WHERE id IS NOT NULL AND company_id IS NOT NULL"
            )
            for session_id, company_id in rows:
                if not session_id or not company_id:
                    continue
                session_company[str(session_id)] = str(company_id)
    except sqlite3.Error as exc:
        print(f"Warning: failed reading sessions DB '{sessions_db_path}': {exc}")
    return session_company


def _build_session_generated_tasks(
    generated_sessions_root: Path,
    session_company_map: dict[str, str],
    fallback_company_id: str = "global",
) -> list[UploadTask]:
    tasks: list[UploadTask] = []
    if not generated_sessions_root.exists():
        return tasks

    generated_dirs = sorted(
        p for p in generated_sessions_root.rglob("generated_videos") if p.is_dir()
    )
    fallback = (fallback_company_id or "global").strip() or "global"

    for generated_dir in generated_dirs:
        session_id = generated_dir.parent.name
        company_id = session_company_map.get(session_id, fallback)
        remote_prefix = f"companies/{company_id}/generated/scenes/{session_id}"
        for local_path in sorted(_iter_files(generated_dir), key=lambda p: p.as_posix()):
            relative_path = local_path.relative_to(generated_dir).as_posix()
            blob_path = f"{remote_prefix}/{relative_path}"
            tasks.append(
                UploadTask(
                    local_path=local_path,
                    blob_path=blob_path,
                    category=f"{company_id}:generated_sessions",
                )
            )

    return tasks


def _dedupe_tasks(tasks: list[UploadTask]) -> list[UploadTask]:
    deduped: dict[str, UploadTask] = {}
    for task in tasks:
        deduped.setdefault(task.blob_path, task)
    return list(deduped.values())


def _load_completed_manifest(manifest_path: Path) -> dict[str, str]:
    completed: dict[str, str] = {}
    if not manifest_path.exists():
        return completed

    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        local_path = row.get("local_path")
        status = row.get("status")
        if not local_path or not status:
            continue
        if status in {"uploaded", "skipped_exists"}:
            completed[local_path] = status
    return completed


def _append_manifest_row(manifest_path: Path, row: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _progress_label(current: int, total: int) -> str:
    if total <= 0:
        return f"[{current}]"
    pct = (current / total) * 100
    return f"[{current}/{total} {pct:5.1f}%]"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill local VideoAgent assets into GCS with an idempotent manifest."
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("GCS_BUCKET_NAME"),
        help="GCS bucket name. Defaults to GCS_BUCKET_NAME env var.",
    )
    parser.add_argument(
        "--expected-location",
        default="europe-west2",
        help="Expected GCS bucket location (default: europe-west2 for London).",
    )
    parser.add_argument(
        "--companies-dir",
        type=Path,
        default=REPO_ROOT / "assets" / "companies",
        help="Root directory for company-scoped assets.",
    )
    parser.add_argument(
        "--skip-generated",
        action="store_true",
        help=(
            "Skip uploading generated assets "
            "(both assets/companies/*/generated and output/agent_sessions/**/generated_videos)."
        ),
    )
    parser.add_argument(
        "--generated-sessions-dir",
        type=Path,
        default=REPO_ROOT / "output" / "agent_sessions",
        help="Root directory that contains session generated_videos folders.",
    )
    parser.add_argument(
        "--sessions-db",
        type=Path,
        default=REPO_ROOT / "videoagent.db",
        help="SQLite DB path used to resolve session_id -> company_id mapping.",
    )
    parser.add_argument(
        "--generated-fallback-company",
        default="global",
        help="Fallback company ID when a generated session cannot be resolved from the DB.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "output" / "gcs_backfill_manifest.jsonl",
        help="Manifest path (JSONL).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not upload, only write planned actions to the manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote files even when they already exist.",
    )
    parser.add_argument(
        "--retry-completed",
        action="store_true",
        help="Ignore completed rows in existing manifest and re-process all files.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process at most N files.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero on first failed upload.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file status.",
    )
    return parser


def main() -> int:
    _load_env()
    args = _build_parser().parse_args()
    if not args.bucket:
        print("Error: --bucket is required (or set GCS_BUCKET_NAME).")
        return 2

    try:
        storage = StorageClient(
            bucket_name=args.bucket,
            expected_location=args.expected_location,
        )
    except Exception as exc:
        print(f"Error: {exc}")
        return 2
    include_generated = not args.skip_generated

    tasks = _build_company_tasks(args.companies_dir, include_generated=include_generated)
    if include_generated:
        session_company_map = _load_session_company_map(args.sessions_db)
        session_generated_tasks = _build_session_generated_tasks(
            args.generated_sessions_dir,
            session_company_map=session_company_map,
            fallback_company_id=args.generated_fallback_company,
        )
        tasks.extend(session_generated_tasks)
        if args.verbose:
            print(f"Resolved sessions: {len(session_company_map)} from {args.sessions_db}")
            print(f"Generated session assets: {len(session_generated_tasks)} from {args.generated_sessions_dir}")
    tasks = _dedupe_tasks(tasks)
    tasks.sort(key=lambda t: t.blob_path)

    completed = {}
    if args.manifest.exists() and not args.retry_completed:
        completed = _load_completed_manifest(args.manifest)

    summary = {
        "planned": 0,
        "uploaded": 0,
        "skipped_exists": 0,
        "skipped_manifest": 0,
        "skipped_size_mismatch": 0,
        "failed": 0,
    }

    total_tasks = len(tasks)
    if args.max_files is not None:
        total_tasks = min(total_tasks, args.max_files)

    print(f"Target bucket: {args.bucket}")
    print(f"Bucket location: {storage.bucket.location}")
    print(f"Task count: {total_tasks}")
    if args.dry_run:
        print("Mode: dry-run")

    processed = 0
    for task in tasks:
        if args.max_files is not None and processed >= args.max_files:
            break
        processed += 1
        progress = _progress_label(processed, total_tasks)

        local_path_str = str(task.local_path.resolve())
        base_row = {
            "ts": _now_iso(),
            "local_path": local_path_str,
            "blob_path": task.blob_path,
            "category": task.category,
            "size": task.size,
        }

        if completed.get(local_path_str) and not args.retry_completed:
            summary["skipped_manifest"] += 1
            row = {**base_row, "status": "skipped_manifest"}
            _append_manifest_row(args.manifest, row)
            if args.verbose:
                print(f"{progress} [skip manifest] {task.blob_path}")
            continue

        if args.dry_run:
            summary["planned"] += 1
            row = {**base_row, "status": "planned"}
            _append_manifest_row(args.manifest, row)
            if args.verbose:
                print(f"{progress} [planned] {task.blob_path}")
            elif processed % 25 == 0 or processed == total_tasks:
                print(f"{progress} planning...")
            continue

        try:
            if storage.exists(task.blob_path) and not args.force:
                remote_size = storage.get_size(task.blob_path)
                if remote_size == task.size:
                    summary["skipped_exists"] += 1
                    row = {
                        **base_row,
                        "status": "skipped_exists",
                        "remote_size": remote_size,
                    }
                    _append_manifest_row(args.manifest, row)
                    if args.verbose:
                        print(f"{progress} [skip exists] {task.blob_path}")
                    elif processed % 25 == 0 or processed == total_tasks:
                        print(f"{progress} processing...")
                    continue

                summary["skipped_size_mismatch"] += 1
                row = {
                    **base_row,
                    "status": "skipped_size_mismatch",
                    "remote_size": remote_size,
                    "error": "remote file exists with different size; re-run with --force to overwrite",
                }
                _append_manifest_row(args.manifest, row)
                print(f"{progress} [skip mismatch] {task.blob_path} local={task.size} remote={remote_size}")
                continue

            content_type = _guess_content_type(task.local_path)
            storage.upload(task.blob_path, task.local_path, content_type=content_type)
            summary["uploaded"] += 1
            row = {
                **base_row,
                "status": "uploaded",
                "content_type": content_type,
            }
            _append_manifest_row(args.manifest, row)
            if args.verbose:
                print(f"{progress} [uploaded] {task.blob_path}")
            elif processed % 25 == 0 or processed == total_tasks:
                print(f"{progress} processing...")
        except Exception as exc:
            summary["failed"] += 1
            row = {**base_row, "status": "failed", "error": str(exc)}
            _append_manifest_row(args.manifest, row)
            print(f"{progress} [failed] {task.blob_path} -> {exc}")
            if args.fail_on_error:
                break

    print("Backfill summary:")
    for key in sorted(summary.keys()):
        print(f"- {key}: {summary[key]}")
    print(f"Manifest: {args.manifest}")
    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

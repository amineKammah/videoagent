#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable

from google.cloud import storage

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "videoagent.db"
DEFAULT_MAPPING_ROOT = Path("/Users/amineka/Downloads/merged_data")


def _load_env() -> None:
    if load_dotenv is None:
        return
    repo_env = REPO_ROOT / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    else:
        load_dotenv()


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _load_company_uuid_map(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id, name FROM companies WHERE id IS NOT NULL AND name IS NOT NULL")
        by_name: dict[str, str] = {}
        for company_id, name in rows:
            if not company_id or not name:
                continue
            by_name[_normalize_name(str(name))] = str(company_id)
    return by_name


def _iter_mapping_files(mapping_root: Path, company_filter: set[str] | None) -> Iterable[tuple[str, Path]]:
    if not mapping_root.exists():
        return []
    dirs = [p for p in mapping_root.iterdir() if p.is_dir()]
    result: list[tuple[str, Path]] = []
    for d in sorted(dirs):
        company_key = _normalize_name(d.name)
        if company_filter and company_key not in company_filter:
            continue
        mapping_path = d / "video_to_transcript_mapping.json"
        if mapping_path.exists():
            result.append((company_key, mapping_path))
    return result


def _parse_mapping(path: Path) -> dict[str, int | str]:
    payload = json.loads(path.read_text())
    mapping = payload.get("mapping", {})
    if not isinstance(mapping, dict):
        raise ValueError(f"Invalid mapping payload in {path}: 'mapping' should be an object")
    return mapping


def _rename_for_company(
    client: storage.Client,
    bucket_name: str,
    company_id: str,
    mapping: dict[str, int | str],
    dry_run: bool,
    keep_source: bool,
    overwrite: bool,
) -> dict[str, int]:
    bucket = client.bucket(bucket_name)

    stats = {
        "total": 0,
        "renamed": 0,
        "already_named": 0,
        "missing_source": 0,
        "target_exists": 0,
        "errors": 0,
    }

    for video_filename, transcript_id in mapping.items():
        stats["total"] += 1
        transcript_id_text = str(transcript_id).strip()
        target_name = Path(str(video_filename)).with_suffix(".json").name
        target_blob_name = f"companies/{company_id}/transcripts/{target_name}"

        source_candidates = [
            f"companies/{company_id}/transcripts/{transcript_id_text}_transcript.json",
            f"companies/{company_id}/transcripts/{transcript_id_text}.json",
        ]

        source_blob = None
        source_blob_name = None
        for source_name in source_candidates:
            candidate = bucket.blob(source_name)
            if candidate.exists():
                source_blob = candidate
                source_blob_name = source_name
                break

        if source_blob is None or source_blob_name is None:
            stats["missing_source"] += 1
            continue

        if source_blob_name == target_blob_name:
            stats["already_named"] += 1
            continue

        target_blob = bucket.blob(target_blob_name)
        if target_blob.exists() and not overwrite:
            stats["target_exists"] += 1
            continue

        if dry_run:
            print(f"[DRY-RUN] {source_blob_name} -> {target_blob_name}")
            stats["renamed"] += 1
            continue

        try:
            bucket.copy_blob(source_blob, bucket, target_blob_name)
            if not keep_source:
                source_blob.delete()
            stats["renamed"] += 1
            print(f"[RENAMED] {source_blob_name} -> {target_blob_name}")
        except Exception as exc:  # pragma: no cover
            stats["errors"] += 1
            print(f"[ERROR] {source_blob_name} -> {target_blob_name}: {exc}")

    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rename GCS transcript files using merged_data video->transcript mappings."
    )
    parser.add_argument(
        "--mapping-root",
        type=Path,
        default=DEFAULT_MAPPING_ROOT,
        help=f"Path to merged_data root (default: {DEFAULT_MAPPING_ROOT})",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to app DB for company UUID mapping (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("GCS_BUCKET_NAME"),
        help="GCS bucket name (default: GCS_BUCKET_NAME env var)",
    )
    parser.add_argument(
        "--company",
        action="append",
        help=(
            "Optional company filter by name (e.g. gusto, zendesk). "
            "Can be passed multiple times."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned renames only; do not modify GCS.",
    )
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="Copy to target but keep old source transcript files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite target transcript if it already exists.",
    )
    return parser


def main() -> int:
    _load_env()
    parser = _build_parser()
    args = parser.parse_args()

    if not args.bucket:
        parser.error("--bucket is required (or set GCS_BUCKET_NAME)")

    if not args.db_path.exists():
        parser.error(f"DB not found: {args.db_path}")
    if not args.mapping_root.exists():
        parser.error(f"mapping root not found: {args.mapping_root}")

    company_filter = None
    if args.company:
        company_filter = {_normalize_name(c) for c in args.company}

    company_id_by_name = _load_company_uuid_map(args.db_path)
    mapping_files = list(_iter_mapping_files(args.mapping_root, company_filter))
    if not mapping_files:
        print("No mapping files found for the selected companies.")
        return 0

    client = storage.Client()
    grand_total = {
        "companies": 0,
        "total": 0,
        "renamed": 0,
        "already_named": 0,
        "missing_source": 0,
        "target_exists": 0,
        "errors": 0,
    }

    for company_key, mapping_path in mapping_files:
        if company_key == "navan":
            print("[SKIP] navan (already in expected format)")
            continue

        company_id = company_id_by_name.get(company_key)
        if not company_id:
            print(f"[SKIP] no DB company UUID for mapping '{mapping_path.parent.name}'")
            continue

        mapping = _parse_mapping(mapping_path)
        print(f"\n=== {mapping_path.parent.name} ({company_id}) ===")
        stats = _rename_for_company(
            client=client,
            bucket_name=args.bucket,
            company_id=company_id,
            mapping=mapping,
            dry_run=args.dry_run,
            keep_source=args.keep_source,
            overwrite=args.overwrite,
        )
        print(
            "summary:",
            ", ".join(f"{k}={v}" for k, v in stats.items()),
        )

        grand_total["companies"] += 1
        for key in ("total", "renamed", "already_named", "missing_source", "target_exists", "errors"):
            grand_total[key] += stats[key]

    print("\n=== grand total ===")
    print(", ".join(f"{k}={v}" for k, v in grand_total.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

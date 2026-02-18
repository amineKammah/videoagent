#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videoagent.config import default_config
from videoagent.storage import get_storage_client
from videoagent.testimony_digest_index import (
    TESTIMONY_DIGEST_SCHEMA_VERSION,
    build_testimony_digest_index,
    testimony_digest_video_key,
    write_testimony_digest_index,
    write_testimony_digest_run_summary,
    write_video_testimony_digest,
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        os.environ[key] = value


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_main_agent_payload(run_dir: Path, video_id: str) -> dict[str, Any]:
    min_path = run_dir / video_id / "main_agent_payload.min.json"
    pretty_path = run_dir / video_id / "main_agent_payload.json"
    source_path = min_path if min_path.exists() else pretty_path
    if not source_path.exists():
        raise FileNotFoundError(f"Missing payload file for video_id={video_id}: {source_path}")
    return json.loads(source_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist existing testimony-digest run artifacts to GCS without rerunning LLM.",
    )
    parser.add_argument(
        "--run-output-dir",
        required=True,
        help="Path to an existing output/testimony_digest_runs/*/<timestamp> directory.",
    )
    parser.add_argument(
        "--company-id",
        default="",
        help="Override company_id. If omitted, uses summary.run_metadata.company_id.",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip writing companies/{company_id}/testimony_digest/index_td_v1.json.",
    )
    parser.add_argument(
        "--no-run-summary",
        action="store_true",
        help="Skip writing companies/{company_id}/testimony_digest/runs/{run_id}/summary.json.",
    )
    parser.add_argument(
        "--skip-dotenv",
        action="store_true",
        help="Do not auto-load .env and backend/.env from repo root.",
    )
    args = parser.parse_args()

    run_output_dir = Path(args.run_output_dir).resolve()
    summary_path = run_output_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary.json at {summary_path}")

    repo_root = Path(__file__).resolve().parents[2]
    if not args.skip_dotenv:
        _load_env_file(repo_root / ".env")
        _load_env_file(repo_root / "backend" / ".env")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run_metadata = summary.get("run_metadata", {}) if isinstance(summary.get("run_metadata"), dict) else {}
    company_id = str(args.company_id or run_metadata.get("company_id") or "").strip()
    if not company_id:
        raise RuntimeError("company_id is required. Pass --company-id or ensure summary.run_metadata.company_id exists.")

    results = summary.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError("Invalid summary.json: 'results' must be a list.")

    storage = get_storage_client(default_config)
    generated_at = _iso_now()
    model = str(summary.get("model") or "")

    persisted = 0
    errors: list[dict[str, str]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        video_id = str(row.get("video_id") or "").strip()
        filename = str(row.get("filename") or "").strip()
        if not video_id:
            continue
        try:
            main_agent_payload = _load_main_agent_payload(run_output_dir, video_id)
            payload = {
                "schema_version": TESTIMONY_DIGEST_SCHEMA_VERSION,
                "generated_at": generated_at,
                "company_id": company_id,
                "video_id": video_id,
                "filename": filename,
                "model": model,
                "prompt_name": "TESTIMONY_DIGEST_PROMPT",
                "digest_tokens_est": int(row.get("digest_tokens_est") or 0),
                "testimony_cards": main_agent_payload.get("testimony_cards", []),
                "source": {
                    "local_run_output_dir": str(run_output_dir),
                    "summary_path": str(summary_path),
                },
            }
            write_video_testimony_digest(storage, company_id, video_id, payload)
            persisted += 1
        except Exception as exc:
            errors.append(
                {
                    "video_id": video_id,
                    "key": testimony_digest_video_key(company_id, video_id),
                    "error": str(exc),
                }
            )

    index_written = False
    index_key = ""
    if not args.no_index:
        index_payload = build_testimony_digest_index(
            company_id=company_id,
            videos=[row for row in results if isinstance(row, dict)],
            model=model or None,
            prompt_name="TESTIMONY_DIGEST_PROMPT",
            generated_at=generated_at,
        )
        write_testimony_digest_index(storage, company_id, index_payload)
        index_written = True
        index_key = f"companies/{company_id}/testimony_digest/index_td_v1.json"

    run_summary_written = False
    run_summary_key = ""
    if not args.no_run_summary:
        write_testimony_digest_run_summary(storage, company_id, run_output_dir.name, summary)
        run_summary_written = True
        run_summary_key = f"companies/{company_id}/testimony_digest/runs/{run_output_dir.name}/summary.json"

    report = {
        "run_output_dir": str(run_output_dir),
        "company_id": company_id,
        "videos_in_summary": len(results),
        "videos_persisted": persisted,
        "video_errors": errors,
        "index_written": index_written,
        "index_key": index_key or None,
        "run_summary_written": run_summary_written,
        "run_summary_key": run_summary_key or None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

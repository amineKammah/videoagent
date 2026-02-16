#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google.genai import types
from pydantic import BaseModel, ValidationError

from videoagent.config import default_config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary

PROMPT = """Return JSON only.
Given the video content you are currently seeing:
1) Report the timestamp where the provided clip begins.
2) Report the timestamp where the provided clip ends.
3) Add one short sentence explaining how you interpreted the timeline.

Output schema:
{
  "clip_begin_timestamp": "MM:SS.sss",
  "clip_end_timestamp": "MM:SS.sss",
  "notes": "..."
}

Rules:
- Do NOT pick an event in the middle of the clip.
- Do NOT summarize content.
- Only provide the timeline boundaries of the clip you received.
"""


class OffsetProbeResponse(BaseModel):
    clip_begin_timestamp: str
    clip_end_timestamp: str
    notes: Optional[str] = None


def _load_env() -> None:
    if load_dotenv is None:
        return
    repo_env = REPO_ROOT / ".env"
    backend_env = BACKEND_DIR / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    if backend_env.exists():
        load_dotenv(dotenv_path=backend_env, override=False)


def _parse_timestamp(text: str) -> float:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("timestamp is empty")
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"invalid timestamp format: {raw}")

    if len(parts) == 3:
        hh_text, mm_text, ss_text = parts
        if not (hh_text.isdigit() and mm_text.isdigit()):
            raise ValueError(f"invalid timestamp digits: {raw}")
        hours = int(hh_text)
        minutes = int(mm_text)
    else:
        ss_text = parts[1]
        mm_text = parts[0]
        if not mm_text.isdigit():
            raise ValueError(f"invalid timestamp digits: {raw}")
        hours = 0
        minutes = int(mm_text)

    if "." in ss_text:
        sec_text, frac_text = ss_text.split(".", 1)
        if not (sec_text.isdigit() and frac_text.isdigit()):
            raise ValueError(f"invalid timestamp digits: {raw}")
        seconds = int(sec_text)
        millis = int((frac_text + "000")[:3])
    else:
        if not ss_text.isdigit():
            raise ValueError(f"invalid timestamp digits: {raw}")
        seconds = int(ss_text)
        millis = 0

    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"invalid second/minute value: {raw}")

    total = (hours * 3600.0) + (minutes * 60.0) + seconds + (millis / 1000.0)
    return total


def _classify_behavior(
    *,
    clip_start: float,
    clip_end: float,
    observed_first: float,
    observed_last: float,
) -> str:
    clip_duration = clip_end - clip_start
    rel_distance = abs(observed_first - 0.0) + abs(observed_last - clip_duration)
    abs_distance = abs(observed_first - clip_start) + abs(observed_last - clip_end)

    if rel_distance <= 4.0 and rel_distance + 1.0 < abs_distance:
        return "LIKELY_RELATIVE_TO_CLIP"
    if abs_distance <= 4.0 and abs_distance + 1.0 < rel_distance:
        return "LIKELY_ABSOLUTE_TO_SOURCE_VIDEO"
    return "AMBIGUOUS"


async def _run_probe(
    *,
    model: str,
    video_uri: str,
    clip_start: float,
    clip_end: float,
) -> dict:
    client = GeminiClient(default_config)
    client.use_vertexai = True

    base_part = client.get_or_upload_file(video_uri)
    if not isinstance(base_part, types.Part) or base_part.file_data is None:
        raise RuntimeError("Failed to build Gemini file part for video URI.")

    async def _call(video_part: types.Part) -> OffsetProbeResponse:
        response = await client.client.aio.models.generate_content(
            model=model,
            contents=types.Content(role="user", parts=[video_part, types.Part(text=PROMPT)]),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": OffsetProbeResponse.model_json_schema(),
            },
        )
        if not response.text:
            raise RuntimeError("Gemini returned empty response text.")
        try:
            return OffsetProbeResponse.model_validate_json(response.text)
        except ValidationError as exc:
            raise RuntimeError(
                "Gemini response did not match expected JSON schema. "
                f"raw={response.text}"
            ) from exc

    full = await _call(base_part)
    clipped_part = types.Part(
        file_data=base_part.file_data,
        video_metadata=types.VideoMetadata(
            start_offset=f"{clip_start:.3f}s",
            end_offset=f"{clip_end:.3f}s",
        ),
    )
    clipped = await _call(clipped_part)

    full_first = _parse_timestamp(full.clip_begin_timestamp)
    full_last = _parse_timestamp(full.clip_end_timestamp)
    clip_first = _parse_timestamp(clipped.clip_begin_timestamp)
    clip_last = _parse_timestamp(clipped.clip_end_timestamp)

    return {
        "full_video": {
            "clip_begin_timestamp": full.clip_begin_timestamp,
            "clip_end_timestamp": full.clip_end_timestamp,
            "begin_seconds": round(full_first, 3),
            "end_seconds": round(full_last, 3),
            "notes": full.notes,
        },
        "clipped_video": {
            "start_offset_seconds": round(clip_start, 3),
            "end_offset_seconds": round(clip_end, 3),
            "clip_begin_timestamp": clipped.clip_begin_timestamp,
            "clip_end_timestamp": clipped.clip_end_timestamp,
            "begin_seconds": round(clip_first, 3),
            "end_seconds": round(clip_last, 3),
            "notes": clipped.notes,
        },
        "classification": _classify_behavior(
            clip_start=clip_start,
            clip_end=clip_end,
            observed_first=clip_first,
            observed_last=clip_last,
        ),
    }


def _pick_probe_window(duration: float, requested_start: Optional[float], requested_end: Optional[float]) -> tuple[float, float]:
    if requested_start is not None and requested_end is not None:
        return requested_start, requested_end

    if duration <= 20:
        return 0.0, max(5.0, duration - 0.5)

    start = max(5.0, min(duration * 0.35, duration - 15.0))
    end = min(duration - 0.5, start + 18.0)
    if end <= start:
        end = min(duration, start + 5.0)
    return start, end


def _resolve_video_uri(company_id: str, video_id: Optional[str]) -> tuple[str, str, float]:
    library = VideoLibrary(default_config, company_id=company_id)
    videos = library.list_videos()
    if not videos:
        raise RuntimeError(f"No videos found for company_id={company_id}.")

    selected = None
    if video_id:
        for item in videos:
            if item.id == video_id:
                selected = item
                break
        if selected is None:
            raise RuntimeError(f"video_id={video_id} not found for company_id={company_id}.")
    else:
        selected = max(videos, key=lambda item: float(item.duration or 0.0))

    uri = str(selected.path)
    if not uri.startswith("gs://"):
        raise RuntimeError(f"Selected video path is not a gs:// URI: {uri}")
    return selected.id, uri, float(selected.duration)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Gemini offset timestamp behavior (absolute vs relative)."
    )
    parser.add_argument(
        "--company-id",
        default="10d48e59-6717-40f2-8e97-f10d7ad51ebb",
        help="Company id to load videos from.",
    )
    parser.add_argument(
        "--video-id",
        default=None,
        help="Optional specific video id. If omitted, picks the longest video.",
    )
    parser.add_argument(
        "--model",
        default="gemini-3-flash-preview",
        help="Gemini model to use.",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=None,
        help="Optional clip start offset in seconds.",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="Optional clip end offset in seconds.",
    )
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    _load_env()
    selected_video_id, uri, duration = _resolve_video_uri(args.company_id, args.video_id)
    clip_start, clip_end = _pick_probe_window(duration, args.start, args.end)
    if clip_start < 0 or clip_end <= clip_start or clip_end > duration:
        raise RuntimeError(
            "Invalid probe window. "
            f"duration={duration:.3f}, start={clip_start:.3f}, end={clip_end:.3f}"
        )

    print(
        json.dumps(
            {
                "selected_video_id": selected_video_id,
                "video_uri": uri,
                "video_duration_seconds": round(duration, 3),
                "probe_window": {
                    "start_offset_seconds": round(clip_start, 3),
                    "end_offset_seconds": round(clip_end, 3),
                },
                "model": args.model,
            },
            indent=2,
        )
    )

    result = await _run_probe(
        model=args.model,
        video_uri=uri,
        clip_start=clip_start,
        clip_end=clip_end,
    )
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_main_async(args))
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

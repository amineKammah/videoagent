#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

import litellm
from agents import Agent, ModelSettings, Runner
from agents.extensions.models.litellm_model import LitellmModel
from agents.models.chatcmpl_converter import Converter
from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body

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


_PATCHED = False


def _load_env() -> None:
    if load_dotenv is None:
        return
    repo_env = REPO_ROOT / ".env"
    backend_env = BACKEND_DIR / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    if backend_env.exists():
        load_dotenv(dotenv_path=backend_env, override=False)


def _patch_agents_input_file_passthrough() -> None:
    global _PATCHED
    if _PATCHED:
        return

    original_extract = Converter.extract_all_content

    @classmethod
    def _patched_extract_all_content(
        cls,
        content: str | Iterable[dict[str, Any]],
    ) -> str | list[dict[str, Any]]:
        if isinstance(content, str):
            return content

        out: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "input_file":
                file_data = item.get("file_data")
                if not file_data:
                    raise ValueError(f"input_file is missing file_data: {item}")

                file_obj: dict[str, Any] = {"file_data": file_data}
                filename = item.get("filename")
                if filename:
                    file_obj["filename"] = filename

                file_format = item.get("format")
                if file_format:
                    file_obj["format"] = file_format

                detail = item.get("detail")
                if detail:
                    file_obj["detail"] = detail

                video_metadata = item.get("video_metadata")
                if isinstance(video_metadata, dict) and video_metadata:
                    file_obj["video_metadata"] = video_metadata

                out.append({"type": "file", "file": file_obj})
                continue

            converted = original_extract(content=[item])  # type: ignore[arg-type]
            if isinstance(converted, str):
                out.append({"type": "text", "text": converted})
            else:
                out.extend(converted)

        return out

    Converter.extract_all_content = _patched_extract_all_content
    _PATCHED = True


def _build_three_color_video(path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x180:d=1",
        "-f",
        "lavfi",
        "-i",
        "color=c=green:s=320x180:d=1",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x180:d=1",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p",
        "-c:v",
        "libx264",
        "-g",
        "1",
        "-keyint_min",
        "1",
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:video/mp4;base64,{encoded}"


def _build_agent(model_name: str) -> Agent:
    return Agent(
        name="VideoOffsetSweepProbe",
        instructions=(
            "You are a strict visual verifier. "
            "Look at the first visible frame and output exactly one token: RED, GREEN, or BLUE."
        ),
        model=LitellmModel(model=model_name),
        model_settings=ModelSettings(temperature=0),
    )


def _build_input(
    *,
    prompt: str,
    file_data: str,
    start_offset: str | None,
    end_offset: str | None,
) -> list[dict[str, Any]]:
    input_file: dict[str, Any] = {
        "type": "input_file",
        "file_data": file_data,
        "filename": "probe_rgb.mp4",
        "format": "video/mp4",
    }
    if start_offset is not None and end_offset is not None:
        input_file["video_metadata"] = {
            "fps": 5,
            "start_offset": start_offset,
            "end_offset": end_offset,
        }

    return [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                input_file,
            ],
        }
    ]


def _normalize_color(text: str) -> str:
    upper = text.strip().upper()
    for color in ("RED", "GREEN", "BLUE"):
        if color in upper:
            return color
    return upper


def _is_transient_error(exc: BaseException) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True
    msg = str(exc).lower()
    return (
        "503" in msg
        or "unavailable" in msg
        or "high demand" in msg
        or "429" in msg
        or "rate limit" in msg
        or "timeout" in msg
    )


def _run_case(
    agent: Agent,
    input_items: list[dict[str, Any]],
    *,
    max_retries: int,
) -> tuple[str | None, str | None]:
    attempts = max(1, max_retries)
    for attempt in range(1, attempts + 1):
        try:
            result = Runner.run_sync(agent, input=input_items, max_turns=1)
            return _normalize_color(str(result.final_output)), None
        except Exception as exc:
            if attempt < attempts and _is_transient_error(exc):
                time.sleep(min(2 ** (attempt - 1), 6))
                continue
            return None, str(exc)
    return None, "unknown_error"


def _transformed_request(
    *,
    model_name: str,
    input_items: list[dict[str, Any]],
) -> dict[str, Any]:
    converted = Converter.items_to_messages(input_items, model=model_name)
    _, provider_name, _, _ = litellm.get_llm_provider(model=model_name)
    if provider_name not in {"gemini", "vertex_ai"}:
        raise ValueError(
            f"Unsupported provider '{provider_name}' for model '{model_name}'."
        )
    model_id = model_name.split("/", 1)[1] if "/" in model_name else model_name
    return _transform_request_body(
        messages=converted,
        model=model_id,
        optional_params={},
        custom_llm_provider=provider_name,  # type: ignore[arg-type]
        litellm_params={},
        cached_content=None,
    )


def _format_seconds(value: float) -> str:
    return f"{value:.3f}s"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep multiple clip offsets and verify live model visibility "
            "plus metadata passthrough."
        )
    )
    parser.add_argument(
        "--model",
        default=(os.environ.get("AGENT_MODEL") or "gemini/gemini-3-pro-preview"),
        help="LiteLLM model name.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Retries per live case for transient provider errors.",
    )
    return parser.parse_args()


def main() -> int:
    _load_env()
    _patch_agents_input_file_passthrough()
    args = _parse_args()

    prompt = (
        "Look at the first visible frame of the attached clip. "
        "Return exactly one token: RED, GREEN, or BLUE."
    )

    # Strict checks are far from segment boundaries:
    # 0-1s RED, 1-2s GREEN, 2-3s BLUE.
    strict_cases = [
        {"name": "full_clip", "start": None, "end": None, "expected": "RED"},
        {"name": "red_mid", "start": 0.250, "end": 0.750, "expected": "RED"},
        {"name": "green_early", "start": 1.100, "end": 1.600, "expected": "GREEN"},
        {"name": "green_late", "start": 1.650, "end": 1.950, "expected": "GREEN"},
        {"name": "blue_early", "start": 2.100, "end": 2.500, "expected": "BLUE"},
        {"name": "blue_late", "start": 2.650, "end": 2.950, "expected": "BLUE"},
    ]
    # Diagnostic near-boundary checks (reported, not pass/fail gates).
    diagnostic_cases = [
        {"name": "boundary_1s", "start": 0.980, "end": 1.200},
        {"name": "boundary_2s", "start": 1.980, "end": 2.200},
    ]

    with tempfile.TemporaryDirectory(prefix="video_offset_sweep_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        video_path = tmp_path / "probe_rgb.mp4"
        _build_three_color_video(video_path)
        data_url = _to_data_url(video_path)

        agent = _build_agent(args.model)
        strict_results: list[dict[str, Any]] = []
        for case in strict_cases:
            start = case["start"]
            end = case["end"]
            start_str = _format_seconds(start) if isinstance(start, float) else None
            end_str = _format_seconds(end) if isinstance(end, float) else None
            input_items = _build_input(
                prompt=prompt,
                file_data=data_url,
                start_offset=start_str,
                end_offset=end_str,
            )
            transformed = _transformed_request(model_name=args.model, input_items=input_items)
            observed, error = _run_case(
                agent,
                input_items,
                max_retries=args.max_retries,
            )

            metadata_ok = True
            if start_str and end_str:
                try:
                    part = transformed["contents"][0]["parts"][1]
                    md = part.get("video_metadata") or {}
                    metadata_ok = (
                        md.get("startOffset") == start_str and md.get("endOffset") == end_str
                    )
                except Exception:
                    metadata_ok = False

            strict_results.append(
                {
                    "name": case["name"],
                    "expected": case["expected"],
                    "observed": observed,
                    "error": error,
                    "start_offset": start_str,
                    "end_offset": end_str,
                    "metadata_ok": metadata_ok,
                    "pass": (observed == case["expected"] and metadata_ok and error is None),
                }
            )

        diagnostic_results: list[dict[str, Any]] = []
        for case in diagnostic_cases:
            start_str = _format_seconds(float(case["start"]))
            end_str = _format_seconds(float(case["end"]))
            input_items = _build_input(
                prompt=prompt,
                file_data=data_url,
                start_offset=start_str,
                end_offset=end_str,
            )
            observed, error = _run_case(
                agent,
                input_items,
                max_retries=args.max_retries,
            )
            diagnostic_results.append(
                {
                    "name": case["name"],
                    "start_offset": start_str,
                    "end_offset": end_str,
                    "observed": observed,
                    "error": error,
                }
            )

    strict_pass_count = sum(1 for item in strict_results if item["pass"])
    report = {
        "model": args.model,
        "strict_cases_total": len(strict_results),
        "strict_cases_passed": strict_pass_count,
        "strict_pass": strict_pass_count == len(strict_results),
        "strict_results": strict_results,
        "diagnostic_boundary_results": diagnostic_results,
        "pass": strict_pass_count == len(strict_results),
    }
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

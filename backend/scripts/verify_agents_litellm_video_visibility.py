#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

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

from agents import Agent, ModelSettings, Runner
from agents.extensions.models.litellm_model import LitellmModel
from agents.models.chatcmpl_converter import Converter
import litellm
from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body


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
                # Preserve LiteLLM/Gemini-specific fields
                file_format = item.get("format")
                if file_format:
                    file_obj["format"] = file_format
                video_metadata = item.get("video_metadata")
                if isinstance(video_metadata, dict) and video_metadata:
                    file_obj["video_metadata"] = video_metadata
                detail = item.get("detail")
                if detail:
                    file_obj["detail"] = detail
                out.append({"type": "file", "file": file_obj})
                continue

            # Delegate all non-file parts to stock converter behavior.
            converted = original_extract(content=[item])  # type: ignore[arg-type]
            if isinstance(converted, str):
                out.append({"type": "text", "text": converted})
            else:
                out.extend(converted)

        return out

    Converter.extract_all_content = _patched_extract_all_content
    _PATCHED = True


def _build_test_video(output_path: Path) -> None:
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
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:video/mp4;base64,{encoded}"


def _build_agent(model_name: str) -> Agent:
    return Agent(
        name="VideoVisibilityProbe",
        instructions=(
            "You are a strict visual verifier. "
            "Only output RED or GREEN with no extra text."
        ),
        model=LitellmModel(model=model_name),
        model_settings=ModelSettings(temperature=0),
    )


def _build_transformed_request(input_items: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
    converted = Converter.items_to_messages(input_items, model=model_name)
    _, provider_name, _, _ = litellm.get_llm_provider(model=model_name)
    if provider_name not in {"gemini", "vertex_ai"}:
        raise ValueError(
            f"Unsupported provider '{provider_name}' for model '{model_name}'. "
            "Use gemini/<model> or vertex_ai/<model>."
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


def _build_input(
    *,
    prompt: str,
    file_data: str,
    include_offsets: bool,
) -> list[dict[str, Any]]:
    input_file: dict[str, Any] = {
        "type": "input_file",
        "file_data": file_data,
        "filename": "probe.mp4",
        "format": "video/mp4",
    }
    if include_offsets:
        input_file["video_metadata"] = {
            "fps": 5,
            "start_offset": "1s",
            "end_offset": "2s",
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


def _run_case(agent: Agent, input_items: list[dict[str, Any]]) -> str:
    result = Runner.run_sync(
        agent,
        input=input_items,
        max_turns=1,
    )
    text = str(result.final_output).strip().upper()
    # Keep only expected tokens.
    if "GREEN" in text:
        return "GREEN"
    if "RED" in text:
        return "RED"
    return text


def _has_video_metadata(request_body: dict[str, Any]) -> bool:
    try:
        parts = request_body["contents"][0]["parts"]
    except Exception:
        return False
    for part in parts:
        video_metadata = part.get("video_metadata")
        if isinstance(video_metadata, dict) and video_metadata.get("startOffset") and video_metadata.get("endOffset"):
            return True
    return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify openai-agents + LiteLLM video passthrough and live model visibility "
            "using a synthetic red->green clip."
        )
    )
    parser.add_argument(
        "--model",
        default=(os.environ.get("AGENT_MODEL") or "gemini/gemini-3-pro-preview"),
        help="LiteLLM model name (e.g. gemini/gemini-3-pro-preview).",
    )
    return parser.parse_args()


def main() -> int:
    _load_env()
    _patch_agents_input_file_passthrough()
    args = _parse_args()

    with tempfile.TemporaryDirectory(prefix="video_probe_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        video_path = tmp_path / "probe.mp4"
        _build_test_video(video_path)
        data_url = _to_data_url(video_path)

    agent = _build_agent(args.model)
    prompt = (
        "Look at the first visible frame of the attached clip. "
        "Output RED or GREEN only."
    )

    full_items = _build_input(prompt=prompt, file_data=data_url, include_offsets=False)
    offset_items = _build_input(prompt=prompt, file_data=data_url, include_offsets=True)
    gs_probe_items = _build_input(
        prompt=prompt,
        file_data="gs://example-bucket/probe.mp4",
        include_offsets=True,
    )

    transformed = _build_transformed_request(gs_probe_items, args.model)
    metadata_survives = _has_video_metadata(transformed)

    full_result = _run_case(agent, full_items)
    offset_result = _run_case(agent, offset_items)

    report = {
        "model": args.model,
        "metadata_passthrough_check": {
            "pass": metadata_survives,
            "transformed_request": transformed,
        },
        "visibility_check": {
            "full_clip_expected": "RED",
            "full_clip_observed": full_result,
            "pass": full_result == "RED",
        },
        "offset_diagnostic_inline_base64": {
            "offset_clip_expected_if_offsets_apply": "GREEN",
            "offset_clip_observed": offset_result,
        },
        "full_clip_expected": "RED",
        "offset_clip_expected": "GREEN",
        "full_clip_observed": full_result,
        "offset_clip_observed": offset_result,
        "pass": metadata_survives and full_result == "RED",
    }
    print(json.dumps(report, indent=2))

    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

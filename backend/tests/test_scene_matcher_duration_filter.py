from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from videoagent.agent.scene_matcher import (
    SceneMatchJob,
    SceneMatchMode,
    _analyze_job_with_prompt,
    _clip_duration_matches_target,
)
from videoagent.models import VoiceOver
from videoagent.story import _StoryboardScene


def _make_scene() -> _StoryboardScene:
    return _StoryboardScene(
        scene_id="scene_1",
        title="Scene",
        purpose="Purpose",
        script="Script",
        use_voice_over=True,
        voice_over=VoiceOver(script="VO", duration=10.0),
    )


def _make_job(target_duration: float = 10.0) -> SceneMatchJob:
    return SceneMatchJob(
        scene_id="scene_1",
        scene=_make_scene(),
        video_id="video_1",
        metadata=SimpleNamespace(id="video_1", filename="video.mp4", duration=120.0),
        notes="",
        mode=SceneMatchMode.VOICE_OVER,
        duration_section="",
        target_duration=target_duration,
    )


def test_clip_duration_matches_target_within_ten_percent() -> None:
    assert _clip_duration_matches_target(
        clip_start=0.0,
        clip_end=9.2,
        target_duration=10.0,
    )


def test_clip_duration_matches_target_rejects_over_ten_percent() -> None:
    assert not _clip_duration_matches_target(
        clip_start=0.0,
        clip_end=8.9,
        target_duration=10.0,
    )


def test_analyze_job_filters_voice_over_candidates_by_duration() -> None:
    response_payload = {
        "candidates": [
            {
                "video_id": "video_1",
                "start_timestamp": "00:00.000",
                "end_timestamp": "00:10.000",
                "description": "Good duration",
                "rationale": "Fits",
                "no_talking_heads_confirmed": True,
                "no_subtitles_confirmed": True,
                "no_camera_recording_on_edge_of_frame_confirmed": True,
                "clip_compatible_with_scene_script_confirmed": True,
            },
            {
                "video_id": "video_1",
                "start_timestamp": "00:00.000",
                "end_timestamp": "00:07.000",
                "description": "Too short",
                "rationale": "Should be filtered",
                "no_talking_heads_confirmed": True,
                "no_subtitles_confirmed": True,
                "no_camera_recording_on_edge_of_frame_confirmed": True,
                "clip_compatible_with_scene_script_confirmed": True,
            },
        ]
    }

    class _FakeModels:
        async def generate_content(self, **_kwargs):
            return SimpleNamespace(
                text=json.dumps(response_payload),
                usage_metadata=None,
            )

    fake_client = SimpleNamespace(
        client=SimpleNamespace(
            aio=SimpleNamespace(
                models=_FakeModels(),
            )
        )
    )

    result = asyncio.run(
        _analyze_job_with_prompt(
            client=fake_client,
            job=_make_job(),
            uploaded_file=genai_types.Part(text="uploaded_file_stub"),
            prompt="test",
        )
    )

    assert "error" not in result
    assert "candidates" in result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["end_seconds"] == pytest.approx(10.0)


def test_analyze_job_accepts_hhmmss_timestamps() -> None:
    response_payload = {
        "candidates": [
            {
                "video_id": "video_1",
                "start_timestamp": "00:00:00.000",
                "end_timestamp": "00:00:10.000",
                "description": "Good duration",
                "rationale": "Fits",
                "no_talking_heads_confirmed": True,
                "no_subtitles_confirmed": True,
                "no_camera_recording_on_edge_of_frame_confirmed": True,
                "clip_compatible_with_scene_script_confirmed": True,
            },
        ]
    }

    class _FakeModels:
        async def generate_content(self, **_kwargs):
            return SimpleNamespace(
                text=json.dumps(response_payload),
                usage_metadata=None,
            )

    fake_client = SimpleNamespace(
        client=SimpleNamespace(
            aio=SimpleNamespace(
                models=_FakeModels(),
            )
        )
    )

    result = asyncio.run(
        _analyze_job_with_prompt(
            client=fake_client,
            job=_make_job(),
            uploaded_file=genai_types.Part(text="uploaded_file_stub"),
            prompt="test",
        )
    )

    assert "error" not in result
    assert "candidates" in result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["start_seconds"] == pytest.approx(0.0)
    assert result["candidates"][0]["end_seconds"] == pytest.approx(10.0)

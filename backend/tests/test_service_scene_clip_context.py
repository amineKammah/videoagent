from __future__ import annotations

from pathlib import Path

from agents.models.chatcmpl_converter import Converter

from videoagent.agent import service as service_module
from videoagent.agent.service import (
    VideoAgentService,
    _patch_agents_input_file_passthrough,
    _select_model_name,
)
from videoagent.config import Config, default_config
from videoagent.story import _MatchedScene, _StoryboardScene


def test_agents_file_patch_preserves_video_metadata() -> None:
    _patch_agents_input_file_passthrough()
    items = [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "analyze"},
                {
                    "type": "input_file",
                    "file_data": "gs://bucket/sample.mp4",
                    "filename": "sample.mp4",
                    "format": "video/mp4",
                    "video_metadata": {
                        "fps": 5,
                        "start_offset": "10s",
                        "end_offset": "20s",
                    },
                },
            ],
        }
    ]

    messages = Converter.items_to_messages(items, model="gemini/gemini-3-pro-preview")
    file_part = messages[0]["content"][1]["file"]  # type: ignore[index]
    assert file_part["format"] == "video/mp4"
    assert file_part["video_metadata"]["start_offset"] == "10s"
    assert file_part["video_metadata"]["end_offset"] == "20s"


def test_scene_clip_context_routes_voiceless_and_voice(monkeypatch, tmp_path: Path) -> None:
    service = VideoAgentService(base_dir=tmp_path / "agent_sessions")

    scene_vo = _StoryboardScene(
        scene_id="scene_vo",
        title="VO scene",
        purpose="Voice over scene",
        script="This is voice over.",
        use_voice_over=True,
        matched_scene=_MatchedScene(
            source_video_id="vid_vo",
            start_time=12.5,
            end_time=18.75,
            description="vo clip",
            keep_original_audio=False,
        ),
    )
    scene_testimony = _StoryboardScene(
        scene_id="scene_testimony",
        title="Testimony scene",
        purpose="Original-audio testimony scene",
        script="This is testimony.",
        use_voice_over=False,
        matched_scene=_MatchedScene(
            source_video_id="vid_testimony",
            start_time=3.0,
            end_time=9.0,
            description="testimony clip",
            keep_original_audio=True,
        ),
    )

    class _FakeMetadata:
        def __init__(self, path: str, filename: str) -> None:
            self.path = path
            self.filename = filename

    class _FakeVideoLibrary:
        def __init__(self, *args, **kwargs) -> None:
            self._map = {
                "vid_vo": _FakeMetadata("gs://bucket/videos/vo.mp4", "vo.mp4"),
                "vid_testimony": _FakeMetadata("gs://bucket/videos/testimony.mp4", "testimony.mp4"),
            }

        def scan_library(self) -> None:
            return None

        def get_video(self, video_id: str):
            return self._map.get(video_id)

    monkeypatch.setattr(service_module, "VideoLibrary", _FakeVideoLibrary)
    monkeypatch.setattr(
        service,
        "_resolve_session_owner",
        lambda session_id: ("user_1", "company_1"),
    )
    monkeypatch.setattr(
        service.storyboard_store,
        "load",
        lambda session_id, user_id=None: [scene_vo, scene_testimony],
    )

    run_input = service._build_scene_clip_context_content("sess_1", "hello")
    assert isinstance(run_input, list)
    content = run_input[0]["content"]
    files = [part for part in content if isinstance(part, dict) and part.get("type") == "input_file"]
    assert len(files) == 2

    # VO scene -> voiceless path.
    assert files[0]["file_data"] == "gs://bucket/videos_voiceless/vo.mp4"
    assert files[0]["video_metadata"]["start_offset"] == "12.500s"
    assert files[0]["video_metadata"]["end_offset"] == "18.750s"

    # Testimony/original-audio scene -> original voice path.
    assert files[1]["file_data"] == "gs://bucket/videos/testimony.mp4"
    assert files[1]["video_metadata"]["start_offset"] == "3.000s"
    assert files[1]["video_metadata"]["end_offset"] == "9.000s"


def test_select_model_name_defaults_to_gemini(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    config = Config(
        output_dir=tmp_path,
        agent_model="gemini-3-pro-preview",
        gemini_model="gemini-3-pro-preview",
    )
    model = _select_model_name(config)
    assert model == "gemini/gemini-3-pro-preview"


def test_select_model_name_keeps_explicit_provider(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL", "vertex_ai/gemini-2.5-flash")
    assert _select_model_name(default_config) == "vertex_ai/gemini-2.5-flash"

    monkeypatch.setenv("AGENT_MODEL", "gemini/gemini-3-pro-preview")
    assert _select_model_name(default_config) == "gemini/gemini-3-pro-preview"

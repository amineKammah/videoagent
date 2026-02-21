from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from videoagent import api as api_module
from videoagent.models import VoiceOver
from videoagent.story import _StoryboardScene


def _make_scene(*, scene_id: str = "scene-1", audio_path: str | None = None) -> _StoryboardScene:
    return _StoryboardScene(
        scene_id=scene_id,
        title="Title",
        purpose="Purpose",
        script="Script",
        use_voice_over=True,
        voice_over=VoiceOver(script="VO", audio_path=audio_path),
    )


def test_generated_scene_blob_key_uses_company_scope_or_global():
    assert (
        api_module._generated_scene_blob_key("company-1", "session-1", "clip.mp4")
        == "companies/company-1/generated/scenes/session-1/clip.mp4"
    )
    assert (
        api_module._generated_scene_blob_key(None, "session-1", "clip.mp4")
        == "companies/global/generated/scenes/session-1/clip.mp4"
    )


def test_sign_if_gcs_signs_gs_uri_and_passthrough_http(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class FakeStorage:
        def get_url(self, path: str) -> str:
            calls.append(path)
            return f"https://signed.example/{path.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(api_module, "get_storage_client", lambda _config: FakeStorage())

    assert api_module._sign_if_gcs("https://cdn.example/video.mp4") == "https://cdn.example/video.mp4"
    assert api_module._sign_if_gcs("http://cdn.example/video.mp4") == "http://cdn.example/video.mp4"
    assert api_module._sign_if_gcs("gs://bink_video_storage_alpha/companies/c1/videos/clip.mp4") == "https://signed.example/clip.mp4"
    assert api_module._sign_if_gcs("/tmp/local.mp4") is None
    assert calls == ["gs://bink_video_storage_alpha/companies/c1/videos/clip.mp4"]


def test_hydrate_scene_media_urls_signs_voice_over_without_mutating_input(monkeypatch: pytest.MonkeyPatch):
    scene = _make_scene(audio_path="gs://bink_video_storage_alpha/companies/c1/generated/audio.wav")
    scene_without_audio = _make_scene(scene_id="scene-2", audio_path=None)

    monkeypatch.setattr(
        api_module,
        "_sign_if_gcs",
        lambda path: "https://signed.example/audio.wav" if path and path.startswith("gs://") else None,
    )

    hydrated = api_module._hydrate_scene_media_urls([scene, scene_without_audio])

    assert hydrated is not None
    assert hydrated[0].voice_over is not None
    assert hydrated[0].voice_over.audio_url == "https://signed.example/audio.wav"
    assert hydrated[1].voice_over is not None
    assert hydrated[1].voice_over.audio_url is None
    # Original scene remains unchanged.
    assert scene.voice_over is not None
    assert scene.voice_over.audio_url is None


def test_get_video_metadata_for_generated_video_reads_sidecar_and_signs(monkeypatch: pytest.MonkeyPatch):
    gcs_key = "companies/company-1/generated/scenes/session-1/clip.mp4"
    sidecar_key = f"{gcs_key}.metadata.json"

    class FakeStorage:
        def exists(self, path: str) -> bool:
            return path in {gcs_key, sidecar_key}

        def read_json(self, path: str):
            assert path == sidecar_key
            return {
                "duration": 8.5,
                "resolution": [1280, 720],
                "fps": 29.97,
            }

        def to_gs_uri(self, path: str) -> str:
            return f"gs://bink_video_storage_alpha/{path}"

        def get_url(self, path: str) -> str:
            return f"https://signed.example/{path}"

    monkeypatch.setattr(api_module, "get_storage_client", lambda _config: FakeStorage())
    monkeypatch.setattr(api_module, "get_user", lambda _db, _user_id: SimpleNamespace(id="user-1", company_id="company-1"))

    response = api_module.get_video_metadata(
        video_id="generated:session-1:clip.mp4",
        x_user_id="user-1",
        db=object(),
    )

    assert response.id == "generated:session-1:clip.mp4"
    assert response.path == "gs://bink_video_storage_alpha/companies/company-1/generated/scenes/session-1/clip.mp4"
    assert response.url == "https://signed.example/companies/company-1/generated/scenes/session-1/clip.mp4"
    assert response.filename == "clip.mp4"
    assert response.duration == pytest.approx(8.5)
    assert response.resolution == (1280, 720)
    assert response.fps == pytest.approx(29.97)


def test_get_video_metadata_for_generated_video_rejects_bad_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_module, "get_storage_client", lambda _config: object())
    monkeypatch.setattr(api_module, "get_user", lambda _db, _user_id: SimpleNamespace(id="user-1", company_id="company-1"))

    with pytest.raises(HTTPException) as exc:
        api_module.get_video_metadata(
            video_id="generated:missing-filename",
            x_user_id="user-1",
            db=object(),
        )
    assert exc.value.status_code == 400


def test_get_video_metadata_for_library_video_uses_signed_url(monkeypatch: pytest.MonkeyPatch):
    captured_company_id: dict[str, str | None] = {"value": None}

    class FakeLibrary:
        def __init__(self, _config, company_id: str | None = None):
            captured_company_id["value"] = company_id

        def get_video(self, video_id: str):
            return SimpleNamespace(
                id=video_id,
                path="gs://bink_video_storage_alpha/companies/company-1/videos/clip.mp4",
                filename="clip.mp4",
                duration=6.0,
                resolution=(1920, 1080),
                fps=24.0,
            )

    class FakeStorage:
        def get_url(self, path: str) -> str:
            return f"https://signed.example/{path.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(api_module, "VideoLibrary", FakeLibrary)
    monkeypatch.setattr(api_module, "get_storage_client", lambda _config: FakeStorage())
    monkeypatch.setattr(api_module, "get_user", lambda _db, _user_id: SimpleNamespace(id="user-1", company_id="company-1"))

    response = api_module.get_video_metadata(
        video_id="video-abc",
        x_user_id="user-1",
        db=object(),
    )

    assert captured_company_id["value"] == "company-1"
    assert response.id == "video-abc"
    assert response.path == "gs://bink_video_storage_alpha/companies/company-1/videos/clip.mp4"
    assert response.url == "https://signed.example/clip.mp4"


def test_get_video_metadata_requires_user_header():
    with pytest.raises(HTTPException) as exc:
        api_module.get_video_metadata(video_id="video-abc", x_user_id=None, db=object())
    assert exc.value.status_code == 400

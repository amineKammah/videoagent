from __future__ import annotations

from pathlib import Path

import pytest

from videoagent.voiceover_v3 import ElevenLabsRateLimitError, VoiceOverV3Generator


class _DummyResponse:
    def __init__(self, *, status_code: int, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text


def _write_fake_wave(
    filename: Path,
    pcm: bytes,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
) -> None:
    _ = (channels, rate, sample_width)
    filename.write_bytes(pcm)


def test_synthesize_retries_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    generator = VoiceOverV3Generator()
    attempts = {"count": 0}
    delays: list[float] = []

    def fake_post(*args, **kwargs) -> _DummyResponse:
        _ = (args, kwargs)
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _DummyResponse(status_code=429, text='{"detail":"too many requests"}')
        return _DummyResponse(status_code=200, content=b"\x00\x01")

    monkeypatch.setattr("videoagent.voiceover_v3.requests.post", fake_post)
    monkeypatch.setattr("videoagent.voiceover_v3.wave_file", _write_fake_wave)
    monkeypatch.setattr(generator, "_retry_sleep", lambda seconds: delays.append(seconds))

    output_path = tmp_path / "voice.wav"
    result_path = generator._synthesize_text_to_wav("hello", output_path, "eleven_v3")

    assert result_path == output_path
    assert output_path.read_bytes() == b"\x00\x01"
    assert attempts["count"] == 3
    assert delays == [1.0, 2.0]


def test_synthesize_stops_after_five_429_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    generator = VoiceOverV3Generator()
    attempts = {"count": 0}
    delays: list[float] = []
    expected_text = '{"detail":"too many concurrent requests"}'

    def always_429(*args, **kwargs) -> _DummyResponse:
        _ = (args, kwargs)
        attempts["count"] += 1
        return _DummyResponse(status_code=429, text=expected_text)

    monkeypatch.setattr("videoagent.voiceover_v3.requests.post", always_429)
    monkeypatch.setattr("videoagent.voiceover_v3.wave_file", _write_fake_wave)
    monkeypatch.setattr(generator, "_retry_sleep", lambda seconds: delays.append(seconds))

    with pytest.raises(ElevenLabsRateLimitError, match="ElevenLabs TTS failed \\(429\\)") as excinfo:
        generator._synthesize_text_to_wav("hello", tmp_path / "voice.wav", "eleven_v3")

    assert attempts["count"] == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert expected_text in str(excinfo.value)


def test_synthesize_does_not_retry_non_429(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    generator = VoiceOverV3Generator()
    attempts = {"count": 0}
    delays: list[float] = []

    def always_500(*args, **kwargs) -> _DummyResponse:
        _ = (args, kwargs)
        attempts["count"] += 1
        return _DummyResponse(status_code=500, text='{"detail":"server error"}')

    monkeypatch.setattr("videoagent.voiceover_v3.requests.post", always_500)
    monkeypatch.setattr("videoagent.voiceover_v3.wave_file", _write_fake_wave)
    monkeypatch.setattr(generator, "_retry_sleep", lambda seconds: delays.append(seconds))

    with pytest.raises(RuntimeError, match="ElevenLabs TTS failed \\(500\\)"):
        generator._synthesize_text_to_wav("hello", tmp_path / "voice.wav", "eleven_v3")

    assert attempts["count"] == 1
    assert delays == []

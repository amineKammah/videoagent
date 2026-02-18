from __future__ import annotations

import asyncio

import pytest

from videoagent.gemini import GeminiClient


class _RateLimitError(Exception):
    def __init__(self, message: str = "429 too many requests"):
        super().__init__(message)
        self.status_code = 429


def test_run_with_retry_sync_uses_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient()
    attempts = {"count": 0}
    delays: list[float] = []

    monkeypatch.setattr("videoagent.gemini.time.sleep", lambda seconds: delays.append(seconds))

    def flaky_operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _RateLimitError("temporary sync 429")
        return "ok"

    result = client._run_with_retry(flaky_operation, operation_name="sync_test")

    assert result == "ok"
    assert attempts["count"] == 3
    assert delays == [1.0, 2.0]


def test_run_with_retry_async_uses_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient()
    attempts = {"count": 0}
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("videoagent.gemini.asyncio.sleep", fake_sleep)

    async def flaky_operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _RateLimitError("temporary async 429")
        return "ok"

    result = asyncio.run(client._run_with_retry_async(flaky_operation, operation_name="async_test"))

    assert result == "ok"
    assert attempts["count"] == 3
    assert delays == [1.0, 2.0]


def test_run_with_retry_sync_stops_after_three_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient()
    attempts = {"count": 0}
    delays: list[float] = []
    expected_error = _RateLimitError("still failing 429")

    monkeypatch.setattr("videoagent.gemini.time.sleep", lambda seconds: delays.append(seconds))

    def always_fail() -> None:
        attempts["count"] += 1
        raise expected_error

    with pytest.raises(RuntimeError, match="sync_fail_test failed after 3 attempts.") as excinfo:
        client._run_with_retry(always_fail, operation_name="sync_fail_test")

    assert excinfo.value.__cause__ is expected_error
    assert attempts["count"] == 3
    assert delays == [1.0, 2.0]


def test_run_with_retry_sync_does_not_retry_non_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient()
    attempts = {"count": 0}
    delays: list[float] = []
    expected_error = ValueError("not rate limited")

    monkeypatch.setattr("videoagent.gemini.time.sleep", lambda seconds: delays.append(seconds))

    def fail_once() -> None:
        attempts["count"] += 1
        raise expected_error

    with pytest.raises(ValueError, match="not rate limited") as excinfo:
        client._run_with_retry(fail_once, operation_name="sync_non429_test")

    assert excinfo.value is expected_error
    assert attempts["count"] == 1
    assert delays == []

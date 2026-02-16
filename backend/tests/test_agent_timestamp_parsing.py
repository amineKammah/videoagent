from __future__ import annotations

import pytest

from videoagent.agent.storage import _parse_timestamp


def test_parse_timestamp_accepts_mmss() -> None:
    assert _parse_timestamp("02:23.456") == pytest.approx(143.456)


def test_parse_timestamp_accepts_hhmmss() -> None:
    assert _parse_timestamp("00:01:54.500") == pytest.approx(114.5)
    assert _parse_timestamp("01:00:00.000") == pytest.approx(3600.0)


def test_parse_timestamp_rejects_out_of_range_minutes_for_hhmmss() -> None:
    with pytest.raises(ValueError, match="Timestamp out of range"):
        _parse_timestamp("00:61:00.000")

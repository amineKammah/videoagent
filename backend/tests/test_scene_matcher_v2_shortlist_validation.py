from __future__ import annotations

from types import SimpleNamespace

import pytest

from videoagent.agent.scene_matcher_v2 import SceneMatcherV2, ShortlistClip


def _matcher() -> SceneMatcherV2:
    return SceneMatcherV2.__new__(SceneMatcherV2)


def test_validate_shortlist_caps_small_end_overrun() -> None:
    matcher = _matcher()
    clips = [
        ShortlistClip(
            video_id="video_1",
            start_time=100.0,
            end_time=130.0,
            reason="test",
        )
    ]
    video_map = {"video_1": SimpleNamespace(duration=129.660227)}

    error = matcher._validate_shortlist(clips, video_map)

    assert error is None
    assert clips[0].end_time == pytest.approx(129.660227)


def test_validate_shortlist_rejects_large_end_overrun() -> None:
    matcher = _matcher()
    clips = [
        ShortlistClip(
            video_id="video_1",
            start_time=100.0,
            end_time=130.3,
            reason="test",
        )
    ]
    video_map = {"video_1": SimpleNamespace(duration=129.660227)}

    error = matcher._validate_shortlist(clips, video_map)

    assert error == (
        "Shortlist rejected: clip end exceeds video duration at "
        "position 1 (130.300 > 129.660)."
    )


def test_validate_shortlist_rejects_end_overrun_at_cap_boundary() -> None:
    matcher = _matcher()
    clips = [
        ShortlistClip(
            video_id="video_1",
            start_time=100.0,
            end_time=130.0,
            reason="test",
        )
    ]
    video_map = {"video_1": SimpleNamespace(duration=129.5)}

    error = matcher._validate_shortlist(clips, video_map)

    assert error == (
        "Shortlist rejected: clip end exceeds video duration at "
        "position 1 (130.000 > 129.500)."
    )


def test_validate_shortlist_rejects_invalid_timing_after_cap() -> None:
    matcher = _matcher()
    clips = [
        ShortlistClip(
            video_id="video_1",
            start_time=129.7,
            end_time=130.0,
            reason="test",
        )
    ]
    video_map = {"video_1": SimpleNamespace(duration=129.660227)}

    error = matcher._validate_shortlist(clips, video_map)

    assert error == "Shortlist rejected: invalid timing at position 1."

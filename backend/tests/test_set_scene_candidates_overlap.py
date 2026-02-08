from videoagent.agent.tools import _dedupe_high_overlap_candidates
from videoagent.story import SceneCandidate


def _candidate(
    source_video_id: str,
    start: float,
    end: float,
) -> SceneCandidate:
    return SceneCandidate(
        source_video_id=source_video_id,
        start_time=start,
        end_time=end,
        description="",
        rationale="",
        keep_original_audio=False,
        shortlisted=True,
        last_rank=1,
    )


def test_dedupe_high_overlap_same_video_removes_later_candidate() -> None:
    candidates_with_index = [
        (0, _candidate("video_a", 10.0, 20.0)),
        (1, _candidate("video_a", 10.6, 19.4)),
        (2, _candidate("video_b", 0.0, 5.0)),
    ]

    kept, warnings = _dedupe_high_overlap_candidates("scene_1", candidates_with_index)

    assert [idx for idx, _ in kept] == [0, 2]
    assert len(warnings) == 1
    assert "removed candidate #2" in warnings[0]
    assert "scene_1" in warnings[0]


def test_dedupe_same_video_non_overlapping_keeps_all() -> None:
    candidates_with_index = [
        (0, _candidate("video_a", 0.0, 5.0)),
        (1, _candidate("video_a", 6.0, 10.0)),
    ]

    kept, warnings = _dedupe_high_overlap_candidates("scene_2", candidates_with_index)

    assert [idx for idx, _ in kept] == [0, 1]
    assert warnings == []


def test_dedupe_different_videos_keeps_all_even_if_timestamps_match() -> None:
    candidates_with_index = [
        (0, _candidate("video_a", 5.0, 12.0)),
        (1, _candidate("video_b", 5.0, 12.0)),
    ]

    kept, warnings = _dedupe_high_overlap_candidates("scene_3", candidates_with_index)

    assert [idx for idx, _ in kept] == [0, 1]
    assert warnings == []

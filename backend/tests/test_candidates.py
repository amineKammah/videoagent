"""Unit tests for scene candidate management."""
from __future__ import annotations

import pytest

from videoagent.story import (
    _StoryboardScene,
    _MatchedScene,
    SceneCandidate,
    SelectionHistoryEntry,
)
from videoagent.candidates import (
    select_candidate,
    restore_from_history,
    update_trim,
    set_candidates,
)


def _make_scene(scene_id: str = "scene_1") -> _StoryboardScene:
    """Create a minimal test scene."""
    return _StoryboardScene(
        scene_id=scene_id,
        title="Test Scene",
        purpose="Testing",
        script="Test script",
    )


def _make_candidate(
    candidate_id: str = "cand_001",
    source_video_id: str = "video_abc",
    start_time: float = 0.0,
    end_time: float = 5.0,
    last_rank: int = 1,
) -> SceneCandidate:
    """Create a test candidate."""
    return SceneCandidate(
        candidate_id=candidate_id,
        source_video_id=source_video_id,
        start_time=start_time,
        end_time=end_time,
        description="Test clip",
        rationale="Fits the scene",
        last_rank=last_rank,
    )


class TestSceneCandidateModel:
    """Tests for SceneCandidate model."""

    def test_candidate_auto_generates_id(self):
        c = SceneCandidate(source_video_id="vid1", start_time=0, end_time=5)
        assert c.candidate_id.startswith("cand_")
        assert len(c.candidate_id) == 13  # "cand_" + 8 hex chars

    def test_candidate_auto_generates_timestamps(self):
        c = SceneCandidate(source_video_id="vid1", start_time=0, end_time=5)
        assert c.created_at.endswith("Z")
        assert c.updated_at.endswith("Z")


class TestSelectionHistoryEntry:
    """Tests for SelectionHistoryEntry model."""

    def test_entry_auto_generates_id(self):
        e = SelectionHistoryEntry(candidate_id="cand_001")
        assert e.entry_id.startswith("hist_")
        assert len(e.entry_id) == 13  # "hist_" + 8 hex chars


class TestStoryboardSceneInvariants:
    """Tests for _StoryboardScene invariant enforcement."""

    def test_shortlist_capped_at_5(self):
        scene = _make_scene()
        # Add 7 shortlisted candidates
        for i in range(7):
            scene.matched_scene_candidates.append(
                _make_candidate(candidate_id=f"cand_{i:03d}", last_rank=i + 1)
            )
        
        # Re-validate to trigger invariant
        scene = _StoryboardScene.model_validate(scene.model_dump())
        
        shortlisted = [c for c in scene.matched_scene_candidates if c.shortlisted]
        assert len(shortlisted) == 5

    def test_history_capped_at_20(self):
        scene = _make_scene()
        # Add 25 history entries
        for i in range(25):
            scene.matched_scene_history.append(
                SelectionHistoryEntry(candidate_id=f"cand_{i:03d}")
            )
        
        # Re-validate to trigger invariant
        scene = _StoryboardScene.model_validate(scene.model_dump())
        
        assert len(scene.matched_scene_history) == 20

    def test_matched_scene_syncs_from_selected_candidate(self):
        scene = _make_scene()
        cand = _make_candidate(
            candidate_id="cand_sync",
            source_video_id="sync_video",
            start_time=10.0,
            end_time=20.0,
        )
        scene.matched_scene_candidates = [cand]
        scene.selected_candidate_id = "cand_sync"
        
        # Re-validate to trigger sync
        scene = _StoryboardScene.model_validate(scene.model_dump())
        
        assert scene.matched_scene is not None
        assert scene.matched_scene.source_video_id == "sync_video"
        assert scene.matched_scene.start_time == 10.0
        assert scene.matched_scene.end_time == 20.0


class TestSelectCandidate:
    """Tests for select_candidate function."""

    def test_select_candidate_changes_selection(self):
        scene = _make_scene()
        cand1 = _make_candidate(candidate_id="cand_1")
        cand2 = _make_candidate(candidate_id="cand_2")
        scene.matched_scene_candidates = [cand1, cand2]
        scene.selected_candidate_id = "cand_1"
        
        select_candidate(scene, "cand_2")
        
        assert scene.selected_candidate_id == "cand_2"

    def test_select_candidate_appends_history(self):
        scene = _make_scene()
        cand1 = _make_candidate(candidate_id="cand_1")
        cand2 = _make_candidate(candidate_id="cand_2")
        scene.matched_scene_candidates = [cand1, cand2]
        scene.selected_candidate_id = "cand_1"
        
        select_candidate(scene, "cand_2", reason="Better option")
        
        assert len(scene.matched_scene_history) == 1
        assert scene.matched_scene_history[0].candidate_id == "cand_1"
        assert scene.matched_scene_history[0].reason == "Better option"

    def test_select_candidate_skips_duplicate(self):
        scene = _make_scene()
        cand = _make_candidate(candidate_id="cand_1")
        scene.matched_scene_candidates = [cand]
        scene.selected_candidate_id = "cand_1"
        
        select_candidate(scene, "cand_1")
        
        # No history entry for selecting same candidate
        assert len(scene.matched_scene_history) == 0

    def test_select_candidate_raises_for_missing(self):
        scene = _make_scene()
        scene.matched_scene_candidates = []
        
        with pytest.raises(ValueError, match="not found"):
            select_candidate(scene, "cand_missing")


class TestRestoreFromHistory:
    """Tests for restore_from_history function."""

    def test_restore_from_history_swaps_selection(self):
        scene = _make_scene()
        cand1 = _make_candidate(candidate_id="cand_1")
        cand2 = _make_candidate(candidate_id="cand_2")
        scene.matched_scene_candidates = [cand1, cand2]
        scene.selected_candidate_id = "cand_2"
        scene.matched_scene_history = [
            SelectionHistoryEntry(entry_id="hist_1", candidate_id="cand_1")
        ]
        
        restore_from_history(scene, "hist_1")
        
        assert scene.selected_candidate_id == "cand_1"

    def test_restore_raises_for_missing_entry(self):
        scene = _make_scene()
        
        with pytest.raises(ValueError, match="not found"):
            restore_from_history(scene, "hist_missing")


class TestUpdateTrim:
    """Tests for update_trim function."""

    def test_trim_updates_times(self):
        scene = _make_scene()
        cand = _make_candidate(candidate_id="cand_1", start_time=0.0, end_time=10.0)
        scene.matched_scene_candidates = [cand]
        scene.selected_candidate_id = "cand_1"
        scene.matched_scene = _MatchedScene(
            source_video_id="vid",
            start_time=0.0,
            end_time=10.0,
            description="",
            keep_original_audio=False,
        )
        
        update_trim(scene, start_time=2.0, end_time=8.0)
        
        assert scene.matched_scene_candidates[0].start_time == 2.0
        assert scene.matched_scene_candidates[0].end_time == 8.0
        assert scene.matched_scene.start_time == 2.0
        assert scene.matched_scene.end_time == 8.0

    def test_trim_raises_without_selection(self):
        scene = _make_scene()
        
        with pytest.raises(ValueError, match="No active selection"):
            update_trim(scene, 0.0, 5.0)


class TestSetCandidates:
    """Tests for set_candidates function."""

    def test_set_candidates_replaces_all(self):
        scene = _make_scene()
        scene.matched_scene_candidates = [_make_candidate(candidate_id="old")]
        
        new_candidates = [
            _make_candidate(candidate_id="new_1", last_rank=1),
            _make_candidate(candidate_id="new_2", last_rank=2),
        ]
        set_candidates(scene, new_candidates)
        
        assert len(scene.matched_scene_candidates) == 2
        assert scene.matched_scene_candidates[0].candidate_id == "new_1"

    def test_set_candidates_auto_selects_best(self):
        scene = _make_scene()
        
        candidates = [
            _make_candidate(candidate_id="rank2", last_rank=2),
            _make_candidate(candidate_id="rank1", last_rank=1),
            _make_candidate(candidate_id="rank3", last_rank=3),
        ]
        set_candidates(scene, candidates)
        
        assert scene.selected_candidate_id == "rank1"

    def test_set_candidates_preserves_existing_selection(self):
        scene = _make_scene()
        scene.selected_candidate_id = "existing"
        
        candidates = [_make_candidate(candidate_id="new", last_rank=1)]
        set_candidates(scene, candidates, auto_select_best=True)
        
        # Should keep existing selection even though auto_select is True
        # because selected_candidate_id was already set
        assert scene.selected_candidate_id == "existing"


class TestBackwardCompatibility:
    """Tests for backward compatibility with old storyboard JSON."""

    def test_scene_without_candidate_fields_loads(self):
        """Old storyboard JSON without candidates should still load."""
        old_json = {
            "scene_id": "old_scene",
            "title": "Old Scene",
            "purpose": "Testing",
            "script": "Script",
            "matched_scene": {
                "source_video_id": "vid",
                "start_time": 0,
                "end_time": 5,
                "description": "Clip",
                "keep_original_audio": False,
            },
        }
        
        scene = _StoryboardScene.model_validate(old_json)
        
        assert scene.scene_id == "old_scene"
        assert scene.matched_scene is not None
        assert scene.matched_scene_candidates == []
        assert scene.selected_candidate_id is None
        assert scene.matched_scene_history == []

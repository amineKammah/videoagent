"""Integration tests for scene candidate selection feature.

These tests verify the full flow of:
1. Setting scene candidates via the set_scene_candidates tool
2. Selecting candidates via the API endpoints
3. Restoring selections from history
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from videoagent.story import _StoryboardScene, SceneCandidate, SelectionHistoryEntry
from videoagent.candidates import select_candidate, restore_from_history, set_candidates
from videoagent.agent.schemas import (
    CandidateItem,
    SceneCandidatesItem,
    SetSceneCandidatesPayload,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def sample_scene() -> _StoryboardScene:
    """Create a sample scene for testing."""
    return _StoryboardScene(
        scene_id="scene_001",
        title="Opening Hook",
        purpose="Grab viewer attention",
        script="Welcome to our demo",
    )


@pytest.fixture
def sample_candidates() -> list[SceneCandidate]:
    """Create sample candidates for testing."""
    return [
        SceneCandidate(
            candidate_id="cand_best",
            source_video_id="video_abc123",
            start_time=10.0,
            end_time=20.0,
            description="Person presenting product demo",
            rationale="Clear visuals, no subtitles",
            last_rank=1,
            shortlisted=True,
        ),
        SceneCandidate(
            candidate_id="cand_alt1",
            source_video_id="video_def456",
            start_time=5.0,
            end_time=15.0,
            description="Wide shot of office environment",
            rationale="Good atmosphere, matches brand",
            last_rank=2,
            shortlisted=True,
        ),
        SceneCandidate(
            candidate_id="cand_alt2",
            source_video_id="video_ghi789",
            start_time=0.0,
            end_time=8.0,
            description="Animated logo reveal",
            rationale="Professional look, modern style",
            last_rank=3,
            shortlisted=True,
        ),
    ]


# ==============================================================================
# Integration Tests: Candidate Flow
# ==============================================================================

class TestSetSceneCandidatesIntegration:
    """Tests for the set_scene_candidates tool integration."""

    def test_set_candidates_creates_valid_scene_state(
        self, sample_scene: _StoryboardScene, sample_candidates: list[SceneCandidate]
    ):
        """Setting candidates should create a valid scene with matched_scene synced."""
        set_candidates(sample_scene, sample_candidates)
        
        # Best candidate (rank 1) should be auto-selected
        assert sample_scene.selected_candidate_id == "cand_best"
        
        # All candidates should be stored
        assert len(sample_scene.matched_scene_candidates) == 3
        
        # matched_scene should be synced from selected candidate
        assert sample_scene.matched_scene is not None
        assert sample_scene.matched_scene.source_video_id == "video_abc123"
        assert sample_scene.matched_scene.start_time == 10.0
        assert sample_scene.matched_scene.end_time == 20.0

    def test_switch_candidates_preserves_history(
        self, sample_scene: _StoryboardScene, sample_candidates: list[SceneCandidate]
    ):
        """Switching candidates should preserve selection history."""
        set_candidates(sample_scene, sample_candidates)
        
        # Switch to alternative
        select_candidate(sample_scene, "cand_alt1", changed_by="user", reason="Prefer this angle")
        
        # History should have the previous selection
        assert len(sample_scene.matched_scene_history) == 1
        assert sample_scene.matched_scene_history[0].candidate_id == "cand_best"
        assert sample_scene.matched_scene_history[0].reason == "Prefer this angle"
        
        # Current selection should be updated
        assert sample_scene.selected_candidate_id == "cand_alt1"
        assert sample_scene.matched_scene.source_video_id == "video_def456"

    def test_restore_from_history_reverts_selection(
        self, sample_scene: _StoryboardScene, sample_candidates: list[SceneCandidate]
    ):
        """Restoring from history should revert to previous selection."""
        set_candidates(sample_scene, sample_candidates)
        
        # Make some changes
        select_candidate(sample_scene, "cand_alt1", changed_by="user", reason="Try this")
        select_candidate(sample_scene, "cand_alt2", changed_by="user", reason="And this")
        
        # History now has 2 entries: cand_best, then cand_alt1
        assert len(sample_scene.matched_scene_history) == 2
        
        # Restore to first history entry (cand_best)
        entry_id = sample_scene.matched_scene_history[0].entry_id
        restore_from_history(sample_scene, entry_id)
        
        # Should be back to original
        assert sample_scene.selected_candidate_id == "cand_best"


class TestSetSceneCandidatesPayloadValidation:
    """Tests for payload schema validation."""

    def test_valid_payload_constructs_correctly(self):
        """Valid payload should be accepted."""
        payload = SetSceneCandidatesPayload(
            scenes=[
                SceneCandidatesItem(
                    scene_id="scene_001",
                    candidates=[
                        CandidateItem(
                            source_video_id="video_123",
                            start_time=0.0,
                            end_time=10.0,
                            description="Test clip",
                            keep_original_audio=False,
                        ),
                        CandidateItem(
                            source_video_id="video_456",
                            start_time=5.0,
                            end_time=15.0,
                        ),
                    ],
                    selected_index=0,
                )
            ]
        )
        
        assert len(payload.scenes) == 1
        assert len(payload.scenes[0].candidates) == 2
        assert payload.scenes[0].selected_index == 0

    def test_empty_candidates_list_is_valid(self):
        """Empty candidates list should be allowed (no-op)."""
        payload = SetSceneCandidatesPayload(
            scenes=[
                SceneCandidatesItem(
                    scene_id="scene_001",
                    candidates=[],
                    selected_index=0,
                )
            ]
        )
        
        assert len(payload.scenes[0].candidates) == 0

    def test_multiple_scenes_in_single_payload(self):
        """Payload should support multiple scenes."""
        payload = SetSceneCandidatesPayload(
            scenes=[
                SceneCandidatesItem(
                    scene_id="scene_001",
                    candidates=[
                        CandidateItem(source_video_id="v1", start_time=0, end_time=5),
                    ],
                    selected_index=0,
                ),
                SceneCandidatesItem(
                    scene_id="scene_002",
                    candidates=[
                        CandidateItem(source_video_id="v2", start_time=0, end_time=5),
                        CandidateItem(source_video_id="v3", start_time=5, end_time=10),
                    ],
                    selected_index=1,
                ),
            ]
        )
        
        assert len(payload.scenes) == 2
        assert payload.scenes[1].selected_index == 1


class TestCandidateSelectionFlow:
    """End-to-end flow tests for candidate selection."""

    def test_full_agent_workflow(self, sample_scene: _StoryboardScene):
        """Simulate the full agent workflow."""
        # Step 1: Agent receives scene matching results (simulated)
        scene_matching_results = [
            {"video_id": "video_1", "start_time": 0.0, "end_time": 10.0, "description": "Option A"},
            {"video_id": "video_2", "start_time": 5.0, "end_time": 15.0, "description": "Option B"},
            {"video_id": "video_3", "start_time": 10.0, "end_time": 18.0, "description": "Option C"},
        ]
        
        # Step 2: Agent curates best candidates (picks 2 out of 3)
        curated_candidates = [
            SceneCandidate(
                source_video_id=scene_matching_results[0]["video_id"],
                start_time=scene_matching_results[0]["start_time"],
                end_time=scene_matching_results[0]["end_time"],
                description=scene_matching_results[0]["description"],
                rationale="Best visual match",
                last_rank=1,
                shortlisted=True,
            ),
            SceneCandidate(
                source_video_id=scene_matching_results[2]["video_id"],
                start_time=scene_matching_results[2]["start_time"],
                end_time=scene_matching_results[2]["end_time"],
                description=scene_matching_results[2]["description"],
                rationale="Good alternative",
                last_rank=2,
                shortlisted=True,
            ),
        ]
        
        # Step 3: Agent saves curated candidates
        set_candidates(sample_scene, curated_candidates)
        
        # Verify initial state
        assert sample_scene.selected_candidate_id == curated_candidates[0].candidate_id
        assert sample_scene.matched_scene.source_video_id == "video_1"
        assert len(sample_scene.matched_scene_candidates) == 2
        
        # Step 4: User switches to alternative
        select_candidate(
            sample_scene,
            curated_candidates[1].candidate_id,
            changed_by="user",
            reason="Prefer the longer clip"
        )
        
        # Verify switch
        assert sample_scene.matched_scene.source_video_id == "video_3"
        assert len(sample_scene.matched_scene_history) == 1
        
        # Step 5: User reverts to original
        entry_id = sample_scene.matched_scene_history[0].entry_id
        restore_from_history(sample_scene, entry_id)
        
        # Verify revert
        assert sample_scene.matched_scene.source_video_id == "video_1"

    def test_scene_serialization_with_candidates(
        self, sample_scene: _StoryboardScene, sample_candidates: list[SceneCandidate]
    ):
        """Scene with candidates should serialize and deserialize correctly."""
        set_candidates(sample_scene, sample_candidates)
        select_candidate(sample_scene, "cand_alt1", changed_by="user", reason="Test selection")
        
        # Serialize to JSON
        scene_json = sample_scene.model_dump_json()
        
        # Deserialize back
        restored_scene = _StoryboardScene.model_validate_json(scene_json)
        
        # Verify all data is preserved
        assert restored_scene.selected_candidate_id == "cand_alt1"
        assert len(restored_scene.matched_scene_candidates) == 3
        assert len(restored_scene.matched_scene_history) == 1
        assert restored_scene.matched_scene.source_video_id == "video_def456"

    def test_multiple_scenes_independent_candidates(self):
        """Each scene should maintain independent candidate state."""
        scene1 = _StoryboardScene(
            scene_id="scene_1", title="Scene 1", purpose="P1", script="S1"
        )
        scene2 = _StoryboardScene(
            scene_id="scene_2", title="Scene 2", purpose="P2", script="S2"
        )
        
        # Set different candidates for each scene
        set_candidates(scene1, [
            SceneCandidate(source_video_id="v1a", start_time=0, end_time=5, last_rank=1),
            SceneCandidate(source_video_id="v1b", start_time=0, end_time=5, last_rank=2),
        ])
        set_candidates(scene2, [
            SceneCandidate(source_video_id="v2a", start_time=0, end_time=5, last_rank=1),
        ])
        
        # Scene 1 has 2 candidates, scene 2 has 1
        assert len(scene1.matched_scene_candidates) == 2
        assert len(scene2.matched_scene_candidates) == 1
        
        # Each scene has its own selection
        assert scene1.matched_scene.source_video_id == "v1a"
        assert scene2.matched_scene.source_video_id == "v2a"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_select_nonexistent_candidate_raises(self, sample_scene: _StoryboardScene):
        """Selecting a non-existent candidate should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            select_candidate(sample_scene, "cand_nonexistent")

    def test_restore_nonexistent_history_raises(self, sample_scene: _StoryboardScene):
        """Restoring from non-existent history entry should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            restore_from_history(sample_scene, "hist_nonexistent")

    def test_select_already_selected_is_noop(
        self, sample_scene: _StoryboardScene, sample_candidates: list[SceneCandidate]
    ):
        """Selecting the already-selected candidate should be a no-op."""
        set_candidates(sample_scene, sample_candidates)
        
        # Select the same candidate again
        select_candidate(sample_scene, "cand_best")
        
        # History should be empty (no change recorded)
        assert len(sample_scene.matched_scene_history) == 0

    def test_history_limit_enforced(self, sample_scene: _StoryboardScene):
        """History should be capped at 20 entries."""
        # Create 30 candidates to cycle through
        candidates = [
            SceneCandidate(
                candidate_id=f"cand_{i:03d}",
                source_video_id=f"video_{i}",
                start_time=0,
                end_time=5,
                last_rank=i,
            )
            for i in range(30)
        ]
        
        set_candidates(sample_scene, candidates)
        
        # Cycle through all candidates
        for i in range(1, 30):
            select_candidate(sample_scene, f"cand_{i:03d}")
        
        # Re-validate to trigger cap
        sample_scene = _StoryboardScene.model_validate(sample_scene.model_dump())
        
        # History should be capped at 20
        assert len(sample_scene.matched_scene_history) <= 20

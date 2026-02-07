"""
Candidate management logic for scene matching.

This module provides functions to select, restore, and update scene candidates
without requiring full storyboard rewrites.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from videoagent.story import _StoryboardScene, SceneCandidate, SelectionHistoryEntry


def select_candidate(
    scene: "_StoryboardScene",
    candidate_id: str,
    changed_by: str = "user",
    reason: str = "",
) -> "_StoryboardScene":
    """
    Switch active selection to a different candidate.
    
    Appends the prior selection to history and syncs matched_scene.
    Skips if the candidate is already selected (no duplicate history).
    
    Args:
        scene: The storyboard scene to update.
        candidate_id: ID of the candidate to select.
        changed_by: Who made the change ('user' or 'agent').
        reason: Optional reason for the change.
        
    Returns:
        The updated scene (mutated in place).
        
    Raises:
        ValueError: If the candidate_id is not found.
    """
    from videoagent.story import SelectionHistoryEntry
    
    # Validate candidate exists
    candidate = next(
        (c for c in scene.matched_scene_candidates
         if c.candidate_id == candidate_id),
        None
    )
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found in scene {scene.scene_id}")

    # Skip if already selected (no duplicate history)
    if scene.selected_candidate_id == candidate_id:
        return scene

    # Record prior selection in history
    if scene.selected_candidate_id:
        scene.matched_scene_history.append(
            SelectionHistoryEntry(
                candidate_id=scene.selected_candidate_id,
                changed_by=changed_by,
                reason=reason,
            )
        )

    # Switch selection
    scene.selected_candidate_id = candidate_id
    
    # Manually sync matched_scene from selected candidate
    from videoagent.story import _MatchedScene
    scene.matched_scene = _MatchedScene(
        source_video_id=candidate.source_video_id,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        description=candidate.description,
        keep_original_audio=candidate.keep_original_audio,
    )
    
    return scene


def restore_from_history(
    scene: "_StoryboardScene",
    entry_id: str,
    changed_by: str = "user",
    reason: str = "",
) -> "_StoryboardScene":
    """
    Restore a previous selection from history.
    
    Args:
        scene: The storyboard scene to update.
        entry_id: ID of the history entry to restore.
        changed_by: Who made the change ('user' or 'agent').
        reason: Optional reason for the restore.
        
    Returns:
        The updated scene (mutated in place).
        
    Raises:
        ValueError: If the entry_id is not found.
    """
    entry = next(
        (e for e in scene.matched_scene_history if e.entry_id == entry_id),
        None
    )
    if not entry:
        raise ValueError(f"History entry {entry_id} not found in scene {scene.scene_id}")

    return select_candidate(scene, entry.candidate_id, changed_by, reason)


def update_trim(
    scene: "_StoryboardScene",
    start_time: float,
    end_time: float,
) -> "_StoryboardScene":
    """
    Update trim (start/end times) on the active selection.
    
    This does NOT create a history entry - trims are in-place edits.
    
    Args:
        scene: The storyboard scene to update.
        start_time: New start time in seconds.
        end_time: New end time in seconds.
        
    Returns:
        The updated scene (mutated in place).
        
    Raises:
        ValueError: If no candidate is selected.
    """
    if not scene.selected_candidate_id:
        raise ValueError(f"No active selection to trim in scene {scene.scene_id}")

    # Find and update the selected candidate
    for c in scene.matched_scene_candidates:
        if c.candidate_id == scene.selected_candidate_id:
            c.start_time = start_time
            c.end_time = end_time
            c.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            break

    # Sync matched_scene
    if scene.matched_scene:
        scene.matched_scene.start_time = start_time
        scene.matched_scene.end_time = end_time

    return scene


def set_candidates(
    scene: "_StoryboardScene",
    candidates: list["SceneCandidate"],
    auto_select_best: bool = True,
) -> "_StoryboardScene":
    """
    Replace all candidates for this scene (used when re-running matching).
    
    Args:
        scene: The storyboard scene to update.
        candidates: New list of candidates (replaces existing).
        auto_select_best: If True and no selection exists, select rank 1.
        
    Returns:
        The updated scene (mutated in place).
    """
    from videoagent.story import _MatchedScene
    
    scene.matched_scene_candidates = candidates
    
    # Auto-select best ranked if no selection
    if auto_select_best and not scene.selected_candidate_id and candidates:
        best = min(candidates, key=lambda c: c.last_rank)
        scene.selected_candidate_id = best.candidate_id
    
    # Manually sync matched_scene from selected candidate
    if scene.selected_candidate_id:
        selected = next(
            (c for c in candidates if c.candidate_id == scene.selected_candidate_id),
            None
        )
        if selected:
            scene.matched_scene = _MatchedScene(
                source_video_id=selected.source_video_id,
                start_time=selected.start_time,
                end_time=selected.end_time,
                description=selected.description,
                keep_original_audio=selected.keep_original_audio,
            )
    
    return scene

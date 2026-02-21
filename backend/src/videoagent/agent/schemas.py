"""
Pydantic schemas for the Video Agent.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from videoagent.models import VideoBrief
from videoagent.story import _MatchedScene, _StoryboardScene


class StoryboardSceneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(
        description="Unique id for the scene. If it does not exist, a new scene will be created.",
    )
    title: str = Field(min_length=1, description="Short scene title.")
    purpose: str = Field(min_length=1, description="Narrative goal for the scene.")
    script: str = Field(
        min_length=1,
        description="Voice over script grounded in the available content.",
    )
    use_voice_over: bool = Field(
        default=True,
        description=(
            "If true, generate a voice over for this scene. If false, use the original "
            "scene audio and do not generate a voice over."
        ),
    )
    order: Optional[int] = Field(
        default=None,
        description="Optional ordering index for the scene.",
    )


class StoryboardUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[StoryboardSceneUpdate]


class StoryboardSceneUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: StoryboardSceneUpdate


class MatchedSceneUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    matched_scene: _MatchedScene


class MatchedScenesUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[MatchedSceneUpdateItem]


class VideoBriefUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: VideoBrief


class SceneMatchRequest(BaseModel):
    scene_id: str
    candidate_video_ids: list[str] = Field(
        description=(
            "Video ids from the library catalog for this scene (max 5)."
        )
    )
    notes: str  = Field(
        description=(
            "A description of the visual style of the scene you are looking for for this scene."
        )
    )
    duration_seconds: Optional[float] = None
    start_offset_seconds: Optional[float] = Field(
        default=None,
        description=(
            "Optional analysis window start in source video seconds. "
            "If provided, end_offset_seconds must also be provided."
        ),
    )
    end_offset_seconds: Optional[float] = Field(
        default=None,
        description=(
            "Optional analysis window end in source video seconds. "
            "If provided, start_offset_seconds must also be provided."
        ),
    )


class SceneMatchBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[SceneMatchRequest] = Field(
        description="List of scene match requests to process in one call."
    )


class SceneMatchV2Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(description="Storyboard scene ID to match with v2.")
    notes: str = Field(
        description=(
            "Visual direction for the scene. Include desired visuals, avoids, and narrative role."
        )
    )


class SceneMatchV2BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[SceneMatchV2Request] = Field(
        description="List of v2 scene match requests to process in one call."
    )


class SceneMatchCandidate(BaseModel):
    video_id: str
    start_timestamp: str
    end_timestamp: str
    description: str
    rationale: str


class SceneMatchResponse(BaseModel):
    """Response from the scene matching LLM call."""
    candidates: list[SceneMatchCandidate] = Field(default_factory=list)
    notes: Optional[str] = None


class AgentResponse(BaseModel):
    response: str = Field(description="The natural language response to the user.")
    suggested_actions: list[str] = Field(
        description=(
            "A list of 1-3 short, actionable, and context-aware follow-up prompts for the user "
            "to continue the workflow. Examples: 'Match scenes 2 and 3', 'Generate all voice-overs', "
            "'Render the video', 'Change scene 1 title to ...'. "
            "If no obvious next step exists, list can be empty."
        ),
        max_length=3,
    )


class SceneMatchVoiceOverCandidate(SceneMatchCandidate):
    no_talking_heads_confirmed: bool = Field(
        description="Confirm that there are no people speaking to the camera."
    )
    no_subtitles_confirmed: bool = Field(
        description="Confirm that there are no burnt-in subtitles."
    )
    no_camera_recording_on_edge_of_frame_confirmed: bool = Field(
        description="Confirm there is no camera recording of a person speaking on the edge of the frame."
    )
    clip_compatible_with_scene_script_confirmed: bool = Field(
        description=(
            "Confirm that the clip is compatible with the scene script "
            "(no text overs/widgets that don't match)."
        )
    )


class SceneMatchVoiceOverResponse(BaseModel):
    """Response from the scene matching LLM call for Voice Over mode."""
    candidates: list[SceneMatchVoiceOverCandidate] = Field(default_factory=list)
    notes: Optional[str] = None


# Candidate selection API schemas
class SelectCandidateRequest(BaseModel):
    """Request to select a specific candidate for a scene."""
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(description="ID of the candidate to select.")
    reason: str = Field(default="", description="Optional reason for the selection.")


class RestoreSelectionRequest(BaseModel):
    """Request to restore a previous selection from history."""
    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(description="ID of the history entry to restore.")
    reason: str = Field(default="", description="Optional reason for the restore.")


class SceneUpdateResponse(BaseModel):
    """Response after updating a scene's candidate selection."""
    scene: _StoryboardScene


# Agent tool schemas for saving handpicked candidates
class CandidateItem(BaseModel):
    """A candidate clip handpicked by the agent."""
    model_config = ConfigDict(extra="forbid")
    source_video_id: str = Field(description="12-hex video id from the library.")
    start_time: float = Field(description="Clip start time in seconds.")
    end_time: float = Field(description="Clip end time in seconds.")
    description: str = Field(default="", description="Visual description of the clip.")
    keep_original_audio: bool = Field(default=False, description="If true, keep original audio.")


class SceneCandidatesItem(BaseModel):
    """Candidates for a single scene."""
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(description="Scene ID to set candidates for.")
    candidates: list[CandidateItem] = Field(description="Ranked list of candidates (best first).")
    selected_index: int = Field(default=0, description="Index of the candidate to select (0 = first/best).")


class SetSceneCandidatesPayload(BaseModel):
    """Payload for setting handpicked candidates for multiple scenes."""
    model_config = ConfigDict(extra="forbid")
    scenes: list[SceneCandidatesItem] = Field(description="List of scenes with their candidates.")


class RenderedVoiceoverItem(BaseModel):
    """Final rendered text for a storyboard scene voiceover."""
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(description="Storyboard scene ID for this rendered voiceover text.")
    rendered_text: str = Field(
        min_length=1,
        description="Final ElevenLabs-ready text to synthesize for the scene.",
    )


class GenerateVoiceoverV3Payload(BaseModel):
    """Payload for ElevenLabs v3 voiceover generation."""
    model_config = ConfigDict(extra="forbid")
    segment_ids: list[str] = Field(
        description="Storyboard scene IDs that should get regenerated voiceovers."
    )
    rendered_voiceovers: list[RenderedVoiceoverItem] = Field(
        min_length=1,
        description=(
            "Final rendered text per scene. Each entry must include scene_id and "
            "the exact text that should be sent to ElevenLabs."
        ),
    )


class SetSceneAnimationPayload(BaseModel):
    """Payload for setting an animation overlay on a scene."""

    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(description="Scene ID to set the animation for.")
    html_content: str = Field(
        min_length=1,
        description="Self-contained HTML/CSS/JS animation code to overlay on the video.",
    )

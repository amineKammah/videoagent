"""
Pydantic schemas for the Video Agent.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from videoagent.models import VideoBrief
from videoagent.story import _StoryboardScene, _MatchedScene


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


class SceneMatchBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[SceneMatchRequest] = Field(
        description="List of scene match requests to process in one call."
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
        description="Confirm that the clip is compatible with the scene script (no text overs/widgets that don't match)."
    )


class SceneMatchVoiceOverResponse(BaseModel):
    """Response from the scene matching LLM call for Voice Over mode."""
    candidates: list[SceneMatchVoiceOverCandidate] = Field(default_factory=list)
    notes: Optional[str] = None

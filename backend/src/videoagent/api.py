"""
FastAPI service for VideoAgent orchestration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from videoagent.agent import VideoAgentService
from videoagent.config import Config
from videoagent.models import RenderResult, VideoBrief
from videoagent.story import _StoryboardScene
from videoagent.library import VideoLibrary
from videoagent.annotations import (
    Annotation,
    AnnotationMetrics,
    ComparisonResult,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
    Severity,
    SessionStatus,
    SessionStatusInfo,
    init_annotations_table,
    create_annotation as db_create_annotation,
    get_annotation as db_get_annotation,
    list_annotations as db_list_annotations,
    update_annotation as db_update_annotation,
    delete_annotation as db_delete_annotation,
    get_annotation_metrics as db_get_annotation_metrics,
    compare_annotations as db_compare_annotations,
    get_all_session_annotation_counts as db_get_all_session_annotation_counts,
    get_all_session_conflict_counts as db_get_all_session_conflict_counts,
    set_session_status as db_set_session_status,
    get_session_status as db_get_session_status,
    get_all_session_statuses as db_get_all_session_statuses,
    resolve_annotations as db_resolve_annotations,
    reject_annotations as db_reject_annotations,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_LIBRARY_DIR = REPO_ROOT / "assets" / "test_videos"


class HealthResponse(BaseModel):
    status: str


class AgentSessionResponse(BaseModel):
    session_id: str


class SessionListItem(BaseModel):
    session_id: str
    created_at: str


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem]


class AgentChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class AgentStoryboardRequest(BaseModel):
    session_id: str
    brief: str


class AgentChatResponse(BaseModel):
    session_id: str
    message: str
    suggested_actions: list[str] = Field(default_factory=list)
    scenes: Optional[list[_StoryboardScene]]
    video_brief: Optional[VideoBrief]


class AgentStoryboardResponse(BaseModel):
    session_id: str
    scenes: list[_StoryboardScene]


class AgentStoryboardUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[_StoryboardScene]


class AgentRenderResponse(BaseModel):
    session_id: str
    render_result: RenderResult


class AgentDebugResponse(BaseModel):
    env: dict[str, Optional[str]]
    model: str
    output_dir: str
    library_dir: str


class VideoMetadataResponse(BaseModel):
    id: str
    path: str
    filename: str
    duration: float
    resolution: tuple[int, int]
    fps: float



class AgentEvent(BaseModel):
    ts: str
    type: str
    name: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class AgentEventsResponse(BaseModel):
    session_id: str
    events: list[AgentEvent]
    next_cursor: int


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str
    suggested_actions: list[str] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]



from contextlib import asynccontextmanager
from videoagent.database import init_db, get_all_customers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize fetching/database
    init_db()
    init_annotations_table()
    yield
    # Shutdown: Clean up if needed

app = FastAPI(title="VideoAgent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent_config = Config(
    video_library_path=Path("assets/normalized_videos"),
    transcript_library_path=Path("assets/normalized_transcripts"),
    output_dir=DEFAULT_OUTPUT_DIR,
)
agent_config.output_dir.mkdir(parents=True, exist_ok=True)
agent_service = VideoAgentService(
    config=agent_config,
    base_dir=DEFAULT_OUTPUT_DIR / "agent_sessions",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/customers")
def list_customers():
    return get_all_customers()


@app.get("/agent/sessions", response_model=SessionListResponse)
def list_sessions() -> SessionListResponse:
    sessions = agent_service.list_sessions()
    return SessionListResponse(
        sessions=[SessionListItem(session_id=s["session_id"], created_at=s["created_at"]) for s in sessions]
    )


@app.post("/agent/sessions", response_model=AgentSessionResponse)
def create_agent_session() -> AgentSessionResponse:
    session_id = agent_service.create_session()
    return AgentSessionResponse(session_id=session_id)


@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    try:
        # run_turn returns a string (the agent's message)
        result = agent_service.run_turn(request.session_id, request.message)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Handle both string and dict returns for backwards compatibility
    if isinstance(result, str):
        message = result
        suggested_actions = []
    else:
        message = result.get("response", "")
        suggested_actions = result.get("suggested_actions", [])

    scenes = agent_service.get_storyboard(request.session_id)
    video_brief = agent_service.get_video_brief(request.session_id)
    return AgentChatResponse(
        session_id=request.session_id,
        message=message,
        suggested_actions=suggested_actions,
        scenes=scenes,
        video_brief=video_brief,
    )


@app.post("/agent/storyboard/draft", response_model=AgentStoryboardResponse)
def draft_storyboard(request: AgentStoryboardRequest) -> AgentStoryboardResponse:
    """Directly trigger the storyboard generation without the Agent loop or TTS."""
    try:
        scenes = agent_service.generate_storyboard(request.session_id, request.brief)
        return AgentStoryboardResponse(session_id=request.session_id, scenes=scenes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/agent/sessions/{session_id}/storyboard", response_model=AgentStoryboardResponse)
def get_storyboard(session_id: str) -> AgentStoryboardResponse:
    scenes = agent_service.get_storyboard(session_id) or []
    return AgentStoryboardResponse(session_id=session_id, scenes=scenes)


@app.get("/agent/sessions/{session_id}/brief", response_model=Optional[VideoBrief])
def get_video_brief(session_id: str) -> Optional[VideoBrief]:
    return agent_service.get_video_brief(session_id)


@app.patch("/agent/sessions/{session_id}/storyboard", response_model=AgentStoryboardResponse)
def update_storyboard(session_id: str, request: AgentStoryboardUpdateRequest) -> AgentStoryboardResponse:
    agent_service.save_storyboard(session_id, request.scenes)
    return AgentStoryboardResponse(session_id=session_id, scenes=request.scenes)


@app.post("/agent/sessions/{session_id}/render", response_model=AgentRenderResponse)
def render_agent_plan(session_id: str) -> AgentRenderResponse:
    try:
        result = agent_service.render_storyboard(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AgentRenderResponse(session_id=session_id, render_result=result)


@app.get("/agent/sessions/{session_id}/chat", response_model=ChatHistoryResponse)
def get_chat_history(session_id: str) -> ChatHistoryResponse:
    messages = agent_service.get_chat_history(session_id)
    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessage(
                role=m.get("role", "assistant"),
                content=m.get("content", ""),
                timestamp=m.get("timestamp", ""),
                suggested_actions=m.get("suggested_actions", []),
            )
            for m in messages
        ],
    )


@app.get("/agent/debug", response_model=AgentDebugResponse)
def agent_debug() -> AgentDebugResponse:
    def _present(value: Optional[str]) -> Optional[str]:
        return value if value else None

    def _basename(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return os.path.basename(value)

    env = {
        "AGENT_MODEL": _present(os.environ.get("AGENT_MODEL")),
        "GOOGLE_CLOUD_PROJECT": _present(os.environ.get("GOOGLE_CLOUD_PROJECT")),
        "CLOUDSDK_CORE_PROJECT": _present(os.environ.get("CLOUDSDK_CORE_PROJECT")),
        "GOOGLE_CLOUD_LOCATION": _present(os.environ.get("GOOGLE_CLOUD_LOCATION")),
        "GOOGLE_APPLICATION_CREDENTIALS": _basename(
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        ),
        "GEMINI_API_KEY": "set" if os.environ.get("GEMINI_API_KEY") else None,
    }

    return AgentDebugResponse(
        env=env,
        model=getattr(agent_service, "model_name", agent_service.config.agent_model),
        output_dir=str(agent_service.config.output_dir),
        library_dir=str(agent_service.config.video_library_path),
    )


@app.get("/agent/sessions/{session_id}/events", response_model=AgentEventsResponse)
def agent_events(session_id: str, cursor: Optional[int] = Query(default=None)) -> AgentEventsResponse:
    events, next_cursor = agent_service.get_events(session_id, cursor)
    return AgentEventsResponse(session_id=session_id, events=events, next_cursor=next_cursor)


@app.get("/agent/library/videos/{video_id:path}", response_model=VideoMetadataResponse)
def get_video_metadata(video_id: str) -> VideoMetadataResponse:
    # Handle generated videos (format: "generated:<session_id>:<filename>")
    if video_id.startswith("generated:"):
        parts = video_id.split(":", 2)
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail=f"Invalid generated video_id format: {video_id}")
        
        _, session_id, filename = parts
        generated_path = agent_service.base_dir / session_id / "generated_videos" / filename
        
        if not generated_path.exists():
            raise HTTPException(status_code=404, detail=f"Generated video not found: {video_id}")
        
        # Extract metadata from the generated video
        from videoagent.library import extract_video_metadata
        try:
            meta = extract_video_metadata(generated_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract video metadata: {e}")
        
        return VideoMetadataResponse(
            id=video_id,
            path=str(generated_path.absolute()),
            filename=filename,
            duration=meta.get("duration", 0.0),
            resolution=meta.get("resolution", (1920, 1080)),
            fps=meta.get("fps", 24.0),
        )
    
    # Handle regular library videos
    library = VideoLibrary(agent_config)
    video = library.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video not found: {video_id}")
    
    return VideoMetadataResponse(
        id=video.id,
        path=str(video.path.absolute()),
        filename=video.filename,
        duration=video.duration,
        resolution=video.resolution,
        fps=video.fps,
    )


# ============================================================================
# Annotation Endpoints
# ============================================================================

class AnnotationResponse(BaseModel):
    """Response containing a single annotation."""
    id: str
    session_id: str
    scene_id: str
    timestamp: float
    global_timestamp: float
    annotator_id: str
    annotator_name: str
    category: str
    description: str
    severity: str
    created_at: str
    updated_at: str
    resolved: bool
    resolved_by: Optional[str]


class AnnotationListResponse(BaseModel):
    """Response containing a list of annotations."""
    session_id: str
    annotations: list[AnnotationResponse]


class AnnotationMetricsResponse(BaseModel):
    """Response containing annotation metrics."""
    session_id: str
    total_annotations: int
    by_category: dict[str, int]
    by_scene: dict[str, int]
    by_severity: dict[str, int]
    faultless_scenes: int
    total_scenes: int


def _annotation_to_response(ann: Annotation) -> AnnotationResponse:
    """Convert an Annotation model to a response."""
    return AnnotationResponse(
        id=ann.id,
        session_id=ann.session_id,
        scene_id=ann.scene_id,
        timestamp=ann.timestamp,
        global_timestamp=ann.global_timestamp,
        annotator_id=ann.annotator_id,
        annotator_name=ann.annotator_name,
        category=ann.category,
        description=ann.description,
        severity=ann.severity.value,
        created_at=ann.created_at.isoformat(),
        updated_at=ann.updated_at.isoformat(),
        resolved=ann.resolved,
        resolved_by=ann.resolved_by,
    )


@app.get("/annotations/stats/counts")
def get_annotation_counts() -> dict[str, int]:
    """Get annotation counts for all sessions."""
    return db_get_all_session_annotation_counts()


@app.get("/annotations/stats/statuses")
def get_session_statuses() -> dict[str, SessionStatus]:
    """Get status for all sessions."""
    return db_get_all_session_statuses()


@app.get("/annotations/stats/conflicts")
def get_session_conflicts() -> dict[str, int]:
    """Get conflict counts for all sessions."""
    return db_get_all_session_conflict_counts()


@app.get("/annotations/{session_id}", response_model=AnnotationListResponse)
def list_annotations(
    session_id: str,
    annotator_id: Optional[str] = Query(default=None),
) -> AnnotationListResponse:
    """List all annotations for a session."""
    annotations = db_list_annotations(session_id, annotator_id)
    return AnnotationListResponse(
        session_id=session_id,
        annotations=[_annotation_to_response(a) for a in annotations],
    )


@app.post("/annotations", response_model=AnnotationResponse)
def create_annotation(request: CreateAnnotationRequest) -> AnnotationResponse:
    """Create a new annotation."""
    annotation = db_create_annotation(request)
    return _annotation_to_response(annotation)


@app.get("/annotations/detail/{annotation_id}", response_model=AnnotationResponse)
def get_annotation(annotation_id: str) -> AnnotationResponse:
    """Get a single annotation by ID."""
    annotation = db_get_annotation(annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail=f"Annotation not found: {annotation_id}")
    return _annotation_to_response(annotation)


@app.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
def update_annotation(
    annotation_id: str,
    request: UpdateAnnotationRequest,
) -> AnnotationResponse:
    """Update an existing annotation."""
    annotation = db_update_annotation(annotation_id, request)
    if not annotation:
        raise HTTPException(status_code=404, detail=f"Annotation not found: {annotation_id}")
    return _annotation_to_response(annotation)


@app.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: str) -> dict:
    """Delete an annotation."""
    deleted = db_delete_annotation(annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Annotation not found: {annotation_id}")
    return {"deleted": True}


@app.get("/annotations/{session_id}/metrics", response_model=AnnotationMetricsResponse)
def get_annotation_metrics(session_id: str) -> AnnotationMetricsResponse:
    """Get aggregate metrics for annotations on a session."""
    metrics = db_get_annotation_metrics(session_id)
    
    # Get total scenes from storyboard
    scenes = agent_service.get_storyboard(session_id) or []
    total_scenes = len(scenes)
    scenes_with_annotations = len(metrics.by_scene)
    
    return AnnotationMetricsResponse(
        session_id=session_id,
        total_annotations=metrics.total_annotations,
        by_category=metrics.by_category,
        by_scene=metrics.by_scene,
        by_severity=metrics.by_severity,
        faultless_scenes=total_scenes - scenes_with_annotations,
        total_scenes=total_scenes,
    )


@app.get("/annotations/{session_id}/compare")
def compare_annotations(
    session_id: str,
    annotator_ids: Optional[str] = Query(default=None),
) -> dict:
    """Compare annotations from multiple annotators."""
    # Parse comma-separated annotator IDs
    ids_list = None
    if annotator_ids:
        ids_list = [id.strip() for id in annotator_ids.split(",")]
    
    result = db_compare_annotations(session_id, ids_list)
    
    # Convert to dict for JSON response
    return {
        "session_id": result.session_id,
        "annotators": result.annotators,
        "clusters": [
            {
                "id": c.id,
                "scene_id": c.scene_id,
                "center_timestamp": c.center_timestamp,
                "status": c.status.value,
                "resolved": c.resolved,
                "annotator_count": c.annotator_count,
                "total_annotators": c.total_annotators,
                "annotations": [_annotation_to_response(a).model_dump() for a in c.annotations],
                "resolution": c.resolution.model_dump() if c.resolution else None,
            }
            for c in result.clusters
        ],
        "stats": result.stats,
    }


class SessionStatusUpdate(BaseModel):
    status: SessionStatus
    annotator_id: Optional[str] = None


@app.post("/annotations/{session_id}/status", response_model=SessionStatusInfo)
def set_session_status(session_id: str, request: SessionStatusUpdate) -> SessionStatusInfo:
    """Set the annotation status for a session."""
    return db_set_session_status(session_id, request.status, request.annotator_id)


@app.get("/annotations/{session_id}/status", response_model=SessionStatusInfo)
def get_session_status(session_id: str) -> SessionStatusInfo:
    """Get the annotation status for a session."""
    status = db_get_session_status(session_id)
    if not status:
        # Default to PENDING if not found
        from datetime import datetime
        return SessionStatusInfo(
            session_id=session_id,
            status=SessionStatus.PENDING,
            updated_at=datetime.utcnow()
        )


class ResolveAnnotationsRequest(BaseModel):
    annotation_ids: list[str]
    resolved_by: Optional[str] = None


@app.post("/annotations/resolve")
def resolve_annotations_endpoint(request: ResolveAnnotationsRequest) -> dict:
    """Mark multiple annotations as resolved."""
    count = db_resolve_annotations(request.annotation_ids, request.resolved_by)
    return {"resolved_count": count}


@app.post("/annotations/reject")
def reject_annotations_endpoint(request: ResolveAnnotationsRequest) -> dict:
    """Mark multiple annotations as rejected (soft delete)."""
    count = db_reject_annotations(request.annotation_ids, request.resolved_by)
    return {"rejected_count": count}
    return status


@app.get("/annotations/stats/statuses")
def get_all_session_statuses() -> dict[str, str]:
    """Get annotation statuses for all sessions."""
    statuses = db_get_all_session_statuses()
    # Convert Enums to strings for simpler JSON
    return {k: v.value for k, v in statuses.items()}

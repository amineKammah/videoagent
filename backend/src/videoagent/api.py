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

from videoagent.agent_runtime import VideoAgentService
from videoagent.config import Config
from videoagent.models import RenderResult
from videoagent.story import _StoryboardScene

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_LIBRARY_DIR = REPO_ROOT / "assets" / "test_videos"


class HealthResponse(BaseModel):
    status: str


class AgentSessionResponse(BaseModel):
    session_id: str


class AgentChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class AgentStoryboardRequest(BaseModel):
    session_id: str
    brief: str


class AgentChatResponse(BaseModel):
    session_id: str
    message: str
    scenes: Optional[list[_StoryboardScene]]
    customer_details: Optional[str]

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


app = FastAPI(title="VideoAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent_config = Config(
    video_library_path=Path("/Users/amineka/Downloads/Navan_Content/normalized_videos"),
    transcript_library_path=Path("/Users/amineka/Downloads/Navan_Content/normalized_transcripts"),
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


@app.post("/agent/sessions", response_model=AgentSessionResponse)
def create_agent_session() -> AgentSessionResponse:
    session_id = agent_service.create_session()
    return AgentSessionResponse(session_id=session_id)


@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    try:
        output = agent_service.run_turn(request.session_id, request.message)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    scenes = agent_service.get_storyboard(request.session_id)
    customer_details = agent_service.get_customer_details(request.session_id)
    return AgentChatResponse(
        session_id=request.session_id,
        message=output,
        scenes=scenes,
        customer_details=customer_details,
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

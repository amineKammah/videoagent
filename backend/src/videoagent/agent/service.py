"""
Main Agent Service logic for the Video Agent.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Optional
from datetime import datetime   
from uuid import uuid4

from agents import (
    Agent,
    RunConfig,
    Runner,
    SQLiteSession,
    set_tracing_export_api_key,
)
from agents.extensions.models.litellm_model import LitellmModel

from videoagent.config import Config, default_config
from videoagent.library import VideoLibrary
from videoagent.models import RenderResult, VideoBrief
from videoagent.story import PersonalizedStoryGenerator, _StoryboardScene

from .storage import (
    BriefStore,
    ChatStore,
    EventStore,
    StoryboardStore,
)
from .tools import (
    _build_tools,
    _render_storyboard_scenes,
)
from .prompts import AGENT_SYSTEM_PROMPT


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_env = Path(__file__).resolve().parents[4] / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    else:
        load_dotenv()


def _select_model_name(config: Config) -> str:
    return os.environ.get("AGENT_MODEL") or config.agent_model or f"gemini/{config.gemini_model}"


def _select_api_key(config: Config, model_name: str) -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or config.gemini_api_key


class VideoAgentService:
    def __init__(self, config: Optional[Config] = None, base_dir: Optional[Path] = None):
        self.config = config or default_config
        self.base_dir = base_dir or (Path.cwd() / "output" / "agent_sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.storyboard_store = StoryboardStore(self.base_dir)
        self.brief_store = BriefStore(self.base_dir)
        self.event_store = EventStore(self.base_dir)
        self.chat_store = ChatStore(self.base_dir)
        self.session_db_path = self.base_dir / "agent_memory.db"
        self._agents: dict[str, Agent] = {}
        self._agent_lock = Lock()
        self._run_lock = Lock()
        self._render_lock = Lock()
        self._render_executor = ThreadPoolExecutor(max_workers=1)
        self._render_futures: dict[str, object] = {}
        _load_env()
        self._configure_tracing()

        self._base_instructions = AGENT_SYSTEM_PROMPT

    def get_video_brief(self, session_id: str) -> Optional[VideoBrief]:
        return self.brief_store.load(session_id)

    def _configure_tracing(self) -> None:
        tracing_key = os.environ.get("OPENAI_API_KEY")
        if tracing_key:
            set_tracing_export_api_key(tracing_key)

    def _build_instructions(self, context_payload: dict) -> str:
        context_block = json.dumps(context_payload, indent=2)
        return (
            f"{self._base_instructions}\n\n"
            "Context for this session (read-only JSON):\n"
            f"{context_block}"
        )

    def _build_context_payload(self, session_id: str, video_transcripts: list[dict]) -> dict:
        storyboard_scenes = self.storyboard_store.load(session_id)
        video_brief = self.brief_store.load(session_id)
        return {
            "video_transcripts": video_transcripts,
            "video_brief": video_brief.model_dump(mode="json") if video_brief else None,
            "storyboard_scenes": [
                scene.model_dump(mode="json")
                for scene in storyboard_scenes
            ] if storyboard_scenes else None,
        }

    def _get_agent(self, session_id: str) -> Agent:
        with self._agent_lock:
            video_transcripts: Optional[list[dict]] = None

            def _dynamic_instructions(run_context, agent) -> str:
                nonlocal video_transcripts
                if video_transcripts is None:
                    video_transcripts = self._build_video_transcripts()
                payload = self._build_context_payload(session_id, video_transcripts)
                return self._build_instructions(payload)

            agent = self._agents.get(session_id)
            if agent:
                agent.instructions = _dynamic_instructions
                return agent

            model_name = _select_model_name(self.config)
            self.model_name = model_name
            api_key = _select_api_key(self.config, model_name)
            model = LitellmModel(model=model_name, api_key=api_key)
            tools = _build_tools(
                self.config,
                self.storyboard_store,
                self.brief_store,
                self.event_store,
                session_id,
            )

            agent = Agent(
                name="VideoAgent",
                instructions=_dynamic_instructions,
                model=model,
                tools=tools,
            )
            self._agents[session_id] = agent
            return agent

    def create_session(self) -> str:
        return uuid4().hex

    def list_sessions(self) -> list[dict]:
        """List all available sessions with their creation timestamps."""
        sessions = []
        if not self.base_dir.exists():
            return []
        
        seen_ids = set()
        # Look for .events.jsonl files as the marker of a session
        for path in self.base_dir.glob("*.events.jsonl"):
            session_id = path.stem.split(".")[0]
            if session_id in seen_ids:
                continue
            seen_ids.add(session_id)
            
            # Use file creation time
            try:
                created_at = datetime.fromtimestamp(path.stat().st_ctime).isoformat()
            except OSError:
                created_at = datetime.now().isoformat()
                
            sessions.append({
                "session_id": session_id,
                "created_at": created_at,
            })
            
        return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

    def get_storyboard(self, session_id: str) -> Optional[list[_StoryboardScene]]:
        return self.storyboard_store.load(session_id)

    def save_storyboard(self, session_id: str, scenes: list[_StoryboardScene]) -> None:
        self.storyboard_store.save(session_id, scenes)

    def save_video_brief(self, session_id: str, brief: VideoBrief) -> None:
        self.brief_store.save(session_id, brief)

    def get_chat_history(self, session_id: str) -> list[dict]:
        """Get all chat messages for a session."""
        return self.chat_store.load(session_id)

    def append_chat_message(self, session_id: str, role: str, content: str, suggested_actions: list[str] = None) -> None:
        """Append a chat message to the session history."""
        self.chat_store.append(session_id, {
            "role": role,
            "content": content,
            "suggested_actions": suggested_actions or []
        })

    def _build_video_transcripts(self) -> list[dict]:
        video_library = VideoLibrary(self.config)
        video_library.scan_library()

        transcripts = []
        for video in video_library.list_videos():
            transcripts.append(
                {
                    "video_id": video.id,
                    "filename": video.filename,
                    "transcript": video.get_full_transcript(),
                    "duration": video.duration,
                }
            )
        return transcripts

    def preupload_library_content(self) -> None:
        """Upload all videos used by the main agent's transcript context.
        
        Use this responsibly; unnecessary caching is expensive and slow.
        """
        gemini = GeminiClient(self.config)
        video_library = VideoLibrary(self.config)
        video_library.scan_library()
        
        for video in video_library.list_videos():
            print(f"Pre-caching {video.filename}...")
            gemini.get_or_upload_file(video.path)

    def run_turn(self, session_id: str, user_message: str) -> dict:
        agent = self._get_agent(session_id)

        session = SQLiteSession(session_id, str(self.session_db_path))
        ui_update_tools = {
            "update_storyboard",
            "update_video_brief",
        }
        redacted_args = json.dumps(
            {"note": "REDACTED TO REDUCE TOKEN USAGE; SEE LATEST STATE IN SYSTEM PROMPT"}
        )

        def _scrub_input_item(item):
            if not isinstance(item, dict):
                return item
            if item.get("type") == "function_call" and item.get("name") in ui_update_tools:
                scrubbed = dict(item)
                scrubbed["arguments"] = redacted_args
                return scrubbed
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                scrubbed_calls = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        scrubbed_calls.append(call)
                        continue
                    call_copy = dict(call)
                    func = call_copy.get("function")
                    if isinstance(func, dict):
                        name = func.get("name")
                        if name in ui_update_tools and "arguments" in func:
                            func_copy = dict(func)
                            func_copy["arguments"] = redacted_args
                            call_copy["function"] = func_copy
                    scrubbed_calls.append(call_copy)
                scrubbed = dict(item)
                scrubbed["tool_calls"] = scrubbed_calls
                return scrubbed
            return item

        def _merge_session_input(history, new_input):
            scrubbed_history = [_scrub_input_item(item) for item in history]
            return scrubbed_history + new_input

        run_config = RunConfig(
            workflow_name="VideoAgent chat",
            group_id=session_id,
            session_input_callback=_merge_session_input,
        )
        self.event_store.append(
            session_id,
            {"type": "run_start", "message": user_message},
        )
        
        # Save user message to chat history
        self.append_chat_message(session_id, "user", user_message)
        
        try:
            with self._run_lock:
                result = Runner.run_sync(
                    agent,
                    input=user_message,
                    session=session,
                    max_turns=100,
                    run_config=run_config,
                )
            output = result.final_output
            if not isinstance(output, str):
                output = str(output)
            
            # Try to parse structured JSON response
            response_text = output
            suggested_actions = []
            try:
                # Handle markdown code blocks
                text = output.strip()
                if text.startswith("```"):
                    # Remove markdown code fence
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines)
                
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "response" in parsed:
                    response_text = parsed.get("response", "")
                    suggested_actions = parsed.get("suggested_actions", [])
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Save assistant response to chat history
            self.append_chat_message(session_id, "assistant", response_text, suggested_actions)
            
            return {
                "response": response_text,
                "suggested_actions": suggested_actions,
            }
        finally:
            self.event_store.append(session_id, {"type": "run_end"})

    def get_events(self, session_id: str, cursor: Optional[int]) -> tuple[list[dict], int]:
        return self.event_store.read_since(session_id, cursor)

    def render_segments(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        return self.render_storyboard(session_id, output_filename)

    def render_storyboard(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        scenes = self.storyboard_store.load(session_id) or []
        result = _render_storyboard_scenes(
            scenes,
            self.config,
            session_id,
            self.storyboard_store.base_dir,
            output_filename,
        )
        if not result.success:
            raise ValueError(result.error_message or "Storyboard render failed.")
        return result



    def generate_storyboard(self, session_id: str, brief: str) -> list[_StoryboardScene]:
        """Calls the generator directly for a text-only draft, bypassing TTS and Video matching."""
        generator = PersonalizedStoryGenerator(self.config)
        scenes = generator.plan_storyboard(brief)
        self.storyboard_store.save(session_id, scenes)
        # if brief:
        #     self.brief_store.save(session_id, brief) # Cannot save raw string to BriefStore
        return scenes

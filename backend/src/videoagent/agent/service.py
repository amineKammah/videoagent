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
from uuid import uuid4

from agents import (
    Agent,
    ModelSettings,
    RunConfig,
    Runner,
    SQLiteSession,
    set_tracing_export_api_key,
)
from agents.extensions.models.litellm_model import LitellmModel
from agents.tracing.processors import BackendSpanExporter
from pydantic import BaseModel, Field
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from videoagent.config import Config, default_config
from videoagent.company_brief_context import (
    read_company_brief_context,
)
from videoagent.db import connection, crud, models
from videoagent.gemini import GeminiClient
from videoagent.models import RenderResult, VideoBrief
from videoagent.storage import get_storage_client
from videoagent.testimony_digest_index import (
    read_testimony_digest_index,
    read_video_testimony_digest,
)
from videoagent.story import PersonalizedStoryGenerator, _StoryboardScene

from .prompts import AGENT_SYSTEM_PROMPT_V2
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


def _configure_litellm_vertex_env(config: Config) -> None:
    """Mirror standard GCP env vars into LiteLLM Vertex env vars."""
    project = (
        os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUDSDK_CORE_PROJECT")
        or config.gcp_project_id
    )
    # Keep Vertex on "global" by default; non-Vertex services may use regional locations
    # like europe-west2 and should not implicitly steer LiteLLM Vertex routing.
    location = (os.environ.get("VERTEXAI_LOCATION") or "global").strip()

    if project:
        os.environ["VERTEXAI_PROJECT"] = project
    if location:
        os.environ["VERTEXAI_LOCATION"] = location


def _select_model_name(config: Config) -> str:
    configured = os.environ.get("AGENT_MODEL") or config.agent_model or config.gemini_model
    model_name = configured.strip()
    if model_name.startswith("vertex_ai/"):
        return model_name
    if model_name.startswith("gemini/"):
        return f"vertex_ai/{model_name.split('/', 1)[1]}"
    if "/" in model_name:
        raise ValueError(
            f"Unsupported AGENT_MODEL '{model_name}'. Vertex-only mode requires a 'vertex_ai/' model."
        )
    return f"vertex_ai/{model_name}"


def _is_retryable_rate_limit_error(exc: BaseException) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and '"code": 429' in detail:
        return True
    message = str(exc).lower()
    return "ratelimiterror" in message and "429" in message


class SessionTitleOutput(BaseModel):
    """Structured output schema for session title generation."""
    title: str = Field(min_length=1, max_length=120)


def _patch_backend_span_exporter_usage_schema() -> None:
    """
    Keep tracing payload usage fields compatible with traces ingest.

    Some openai-agents + LiteLLM versions include additional usage keys
    (e.g. requests/total_tokens/details) that are currently rejected by the
    tracing ingest schema.
    """
    export_fn = BackendSpanExporter.export
    if getattr(export_fn, "_videoagent_usage_schema_patched", False):
        return

    original_export = export_fn

    def _patched_export(self, items):
        for item in items:
            span_data = getattr(item, "span_data", None)
            usage = getattr(span_data, "usage", None) if span_data is not None else None
            if not isinstance(usage, dict):
                continue

            sanitized: dict[str, int] = {}
            for key in ("input_tokens", "output_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    sanitized[key] = int(value)

            span_data.usage = sanitized if sanitized else None

        return original_export(self, items)

    setattr(_patched_export, "_videoagent_usage_schema_patched", True)
    BackendSpanExporter.export = _patched_export


class VideoAgentService:
    def __init__(
        self, 
        config: Optional[Config] = None, 
        base_dir: Optional[Path] = None, 
    ):
        self.config = config or default_config
        # user_id and company_id are resolved dynamically per session
        self.base_dir = base_dir or (Path.cwd() / "output" / "agent_sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        models.Base.metadata.create_all(bind=connection.engine)
        # Stores are initialized without static user_id; methods must provide it
        self.storyboard_store = StoryboardStore(self.base_dir)
        self.brief_store = BriefStore(self.base_dir)
        self.event_store = EventStore(self.base_dir)
        self.chat_store = ChatStore(self.base_dir)
        self.session_db_path = self.base_dir / "agent_memory.db"
        self._agents: dict[str, Agent] = {}
        self._agent_model_names: dict[str, str] = {}
        self._agent_lock = Lock()
        self._run_locks_guard = Lock()
        self._run_locks: dict[str, Lock] = {}
        self._render_lock = Lock()
        self._render_executor = ThreadPoolExecutor(max_workers=1)
        self._render_futures: dict[str, object] = {}
        self._title_executor = ThreadPoolExecutor(max_workers=2)
        self._title_lock = Lock()
        self._title_inflight: set[str] = set()
        _load_env()
        self._configure_tracing()

        self._base_instructions = AGENT_SYSTEM_PROMPT_V2

    def _resolve_session_owner(self, session_id: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve user_id and company_id for a session from the DB."""
        try:
            with connection.get_db_context() as db:
                db_session = crud.get_session(db, session_id)
                if db_session:
                    return db_session.user_id, db_session.company_id
        except Exception as e:
            print(f"[_resolve_session_owner] Failed to lookup session {session_id}: {e}")
        return None, None

    def get_video_brief(self, session_id: str) -> Optional[VideoBrief]:
        user_id, _ = self._resolve_session_owner(session_id)
        return self.brief_store.load(session_id, user_id=user_id)

    def _configure_tracing(self) -> None:
        tracing_key = os.environ.get("OPENAI_API_KEY")
        if tracing_key:
            _patch_backend_span_exporter_usage_schema()
            set_tracing_export_api_key(tracing_key)

    def _build_instructions(self, context_payload: dict) -> str:
        company_brief_content = self._normalize_text(context_payload.get("company_brief_context"))
        testimony_context = context_payload.get("testimony_digest_context")
        video_brief = context_payload.get("video_brief")
        storyboard_scenes = context_payload.get("storyboard_scenes")
        company_brief_block = company_brief_content
        testimony_block = json.dumps(testimony_context, separators=(",", ":"))
        video_brief_block = json.dumps(video_brief, separators=(",", ":"))
        storyboard_block = json.dumps(storyboard_scenes, separators=(",", ":"))
        session_state_section = ""
        if video_brief is not None or storyboard_scenes is not None:
            session_state_section = (
                "\n\nCURRENT VIDEO BRIEF (SESSION CONTEXT):\n"
                f"{video_brief_block}\n\n"
                "CURRENT STORYBOARD SCENES (SESSION CONTEXT):\n"
                f"{storyboard_block}"
            )
        return (
            f"{self._base_instructions}\n\n"
            "COMPANY BRIEF INSERT (GLOBAL COMPANY CONTEXT):\n"
            f"{company_brief_block}\n\n"
            "TESTIMONY DIGEST INSERT (PRIMARY EVIDENCE CONTEXT - USE THIS INSTEAD OF FULL TRANSCRIPTS):\n"
            f"{testimony_block}"
            f"{session_state_section}"
        )

    def _build_context_payload(
        self,
        session_id: str,
        testimony_digest_videos: Optional[list[dict]] = None,
        company_brief_context: Optional[str] = None,
    ) -> dict:
        user_id, company_id = self._resolve_session_owner(session_id)
        if testimony_digest_videos is None:
            testimony_digest_videos = self._build_testimony_digest_videos(company_id)
        if company_brief_context is None:
            company_brief_context = self._build_company_brief_context(company_id)
        testimony_cards_total = sum(
            len(item.get("testimony_cards") or [])
            for item in testimony_digest_videos
            if isinstance(item, dict)
        )
        storyboard_scenes = self.storyboard_store.load(session_id, user_id=user_id)
        video_brief = self.brief_store.load(session_id, user_id=user_id)
        return {
            "company_brief_context": company_brief_context,
            "testimony_digest_context": {
                "insert_label": "testimony_digest_v1_primary_context",
                "instruction": (
                    "Use this testimony digest context instead of full video transcripts. "
                    "Only videos with valid testimony cards are included."
                ),
                "videos_with_valid_testimony_cards_count": len(testimony_digest_videos),
                "testimony_cards_total": testimony_cards_total,
                "videos": testimony_digest_videos,
            },
            "video_brief": video_brief.model_dump(mode="json") if video_brief else None,
            "storyboard_scenes": [
                scene.model_dump(mode="json")
                for scene in storyboard_scenes
            ] if storyboard_scenes else None,
        }

    def _get_agent(self, session_id: str) -> Agent:
        with self._agent_lock:
            # Look up session owner in DB first (needed for closure)
            session_user_id, session_company_id = self._resolve_session_owner(session_id)
            print(session_id, session_user_id, session_company_id)

            testimony_digest_videos: Optional[list[dict]] = None
            company_brief_context: Optional[str] = None

            def _dynamic_instructions(run_context, agent) -> str:
                nonlocal testimony_digest_videos, company_brief_context
                payload = self._build_context_payload(
                    session_id,
                    testimony_digest_videos,
                    company_brief_context,
                )
                testimony_context = payload.get("testimony_digest_context") or {}
                testimony_digest_videos = testimony_context.get("videos") or []
                company_brief_context = payload.get("company_brief_context")
                return self._build_instructions(payload)

            _configure_litellm_vertex_env(self.config)
            self.model_name = _select_model_name(self.config)
            provider_model = self.model_name
            provider_name = "unknown"
            try:
                import litellm

                provider_model, provider_name, _, _ = litellm.get_llm_provider(
                    model=self.model_name
                )
            except Exception as exc:
                raise ValueError(
                    f"Unable to resolve LiteLLM provider for AGENT_MODEL '{self.model_name}': {exc}"
                ) from exc
            if provider_name != "vertex_ai":
                raise ValueError(
                    f"AGENT_MODEL '{self.model_name}' resolved to provider '{provider_name}' "
                    f"(provider model: '{provider_model}'). Vertex-only mode requires 'vertex_ai'."
                )

            agent = self._agents.get(session_id)
            if agent and self._agent_model_names.get(session_id) == self.model_name:
                agent.instructions = _dynamic_instructions
                return agent

            model = LitellmModel(model=self.model_name,)
            
            # Tools need resolved IDs
            tools = _build_tools(
                self.config,
                self.storyboard_store,
                self.brief_store,
                self.event_store,
                session_id,
                company_id=session_company_id,
                user_id=session_user_id,
            )

            agent = Agent(
                name="VideoAgent",
                instructions=_dynamic_instructions,
                model=model,
                model_settings=ModelSettings(),
                tools=tools,
            )
            self._agents[session_id] = agent
            self._agent_model_names[session_id] = self.model_name
            return agent

    def create_session(self, user_id: str, company_id: str, session_id: Optional[str] = None) -> str:
        session_id = session_id or uuid4().hex
        
        # Persist to DB
        try:
            with connection.get_db_context() as db:
                crud.create_session(
                    db,
                    session_id=session_id,
                    company_id=company_id,
                    user_id=user_id,
                )
        except Exception as e:
            print(f"[create_session] Failed to persist session to DB: {e}")
            raise

        # Initialize stores for this session
        # Ensure directories exist
        # Pass user_id to ensure user-scoped paths
        self.event_store.append(session_id, {"type": "session_created"}, user_id=user_id)
        
        return session_id

    def list_sessions(self) -> list[dict]:
        """List all available sessions with their creation timestamps."""
        with connection.get_db_context() as db:
            rows = crud.list_sessions(db, active_only=False)
            return [
                {
                    "session_id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]

    def get_storyboard(self, session_id: str) -> Optional[list[_StoryboardScene]]:
        user_id, _ = self._resolve_session_owner(session_id)
        return self.storyboard_store.load(session_id, user_id=user_id)


    def _mark_active(self, session_id: str) -> None:
        """Mark session as active in DB."""
        try:
            with connection.get_db_context() as db:
                crud.mark_session_active(db, session_id)
        except Exception as e:
            print(f"[_mark_active] Failed to mark session {session_id} active: {e}")

    def _get_session_title_model(self) -> str:
        configured = (
            os.environ.get("SESSION_TITLE_MODEL")
            or self.config.session_title_model
            or "gemini-2.5-flash"
        )
        model_name = configured.strip()
        return model_name or "gemini-2.5-flash"

    @staticmethod
    def _normalize_session_title(raw_title: str) -> str:
        title = " ".join((raw_title or "").split()).strip().strip("\"'")
        lowered = title.lower()
        for prefix in ("session title:", "chat title:", "title:", "session:"):
            if lowered.startswith(prefix):
                title = title[len(prefix):].strip().strip("\"'")
                break
        if len(title) > 120:
            title = title[:120].rstrip()
        return title or "New session"

    @staticmethod
    def _fallback_session_title(first_user_message: str) -> str:
        normalized = " ".join((first_user_message or "").split()).strip()
        if not normalized:
            return "New session"
        words = normalized.split(" ")
        title = " ".join(words[:6]).strip()
        if len(title) > 120:
            title = title[:120].rstrip()
        return title or "New session"

    def _schedule_session_title_generation(self, session_id: str) -> None:
        with self._title_lock:
            if session_id in self._title_inflight:
                return
            self._title_inflight.add(session_id)
        self._title_executor.submit(self._generate_session_title_job, session_id)

    def _generate_session_title_job(self, session_id: str) -> None:
        try:
            self._generate_session_title(session_id)
        except Exception as exc:
            print(f"[_generate_session_title_job] Failed for session {session_id}: {exc}")
        finally:
            with self._title_lock:
                self._title_inflight.discard(session_id)

    def _generate_session_title(self, session_id: str) -> None:
        with connection.get_db_context() as db:
            session = crud.get_session(db, session_id)
            if not session:
                return
            if session.title or session.title_source == "manual":
                return
            first_user_message = crud.get_first_user_message(db, session_id)

        if not first_user_message:
            return

        prompt = (
            "Generate a concise title for this chat session.\n"
            "Requirements:\n"
            "- Return JSON that matches the schema exactly.\n"
            "- title must be 2-6 words.\n"
            "- No quotes, markdown, or prefixes like Title:.\n"
            "- Preserve key product/company names when present.\n"
            f"First user message:\n{first_user_message}"
        )

        title = ""
        source = "fallback"
        try:
            from google.genai import types

            client = GeminiClient(self.config)
            response = client.generate_content(
                model=self._get_session_title_model(),
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=24,
                    response_mime_type="application/json",
                    response_schema=SessionTitleOutput,
                    thinking_config=types.ThinkingConfig(thinking_budget=512),
                ),
            )
            parsed = getattr(response, "parsed", None)
            if parsed and getattr(parsed, "title", None):
                title = self._normalize_session_title(parsed.title)
                source = "auto"
        except Exception as exc:
            print(f"[_generate_session_title] Model generation failed for {session_id}: {exc}")

        if not title:
            title = self._fallback_session_title(first_user_message)

        with connection.get_db_context() as db:
            updated = crud.set_session_title_if_absent(
                db,
                session_id=session_id,
                title=title,
                source=source,
            )
        if not updated:
            return

        user_id, _ = self._resolve_session_owner(session_id)
        self.event_store.append(
            session_id,
            {"type": "session_title_updated", "title": title, "source": source},
            user_id=user_id,
        )

    def save_storyboard(self, session_id: str, scenes: list[_StoryboardScene]) -> None:
        user_id, _ = self._resolve_session_owner(session_id)
        self.storyboard_store.save(session_id, scenes, user_id=user_id)
        self._mark_active(session_id)

    def save_video_brief(self, session_id: str, brief: VideoBrief) -> None:
        user_id, _ = self._resolve_session_owner(session_id)
        self.brief_store.save(session_id, brief, user_id=user_id)
        self._mark_active(session_id)

    def get_chat_history(self, session_id: str) -> list[dict]:
        """Get all chat messages for a session."""
        user_id, _ = self._resolve_session_owner(session_id)
        return self.chat_store.load(session_id, user_id=user_id)

    def append_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        suggested_actions: list[str] = None,
    ) -> None:
        """Append a chat message to the session history."""
        user_id, _ = self._resolve_session_owner(session_id)
        self.chat_store.append(session_id, {
            "role": role,
            "content": content,
            "suggested_actions": suggested_actions or []
        }, user_id=user_id)
        
        # Only user/assistant messages count as activity, but generally appending any message is activity
        if role in ("user", "assistant"):
            self._mark_active(session_id)


    @staticmethod
    def _normalize_text(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def _is_valid_testimony_card(cls, card: object) -> bool:
        if not isinstance(card, dict):
            return False
        speaker = card.get("speaker")
        speaker_has_data = False
        if isinstance(speaker, dict):
            speaker_has_data = any(
                cls._normalize_text(speaker.get(field))
                for field in ("name", "role", "company")
            )

        proof_claim = cls._normalize_text(card.get("proof_claim"))
        intro_seed = cls._normalize_text(card.get("intro_seed"))
        evidence_snippet = cls._normalize_text(card.get("evidence_snippet"))

        metrics_raw = card.get("metrics")
        metrics_has_data = False
        if isinstance(metrics_raw, list):
            for metric in metrics_raw:
                if not isinstance(metric, dict):
                    continue
                metric_name = cls._normalize_text(metric.get("metric"))
                metric_value = cls._normalize_text(metric.get("value"))
                if metric_name or metric_value:
                    metrics_has_data = True
                    break

        red_flags_raw = card.get("red_flags")
        red_flags_has_data = False
        if isinstance(red_flags_raw, list):
            red_flags_has_data = any(cls._normalize_text(flag) for flag in red_flags_raw)

        return bool(
            proof_claim
            or intro_seed
            or evidence_snippet
            or speaker_has_data
            or metrics_has_data
            or red_flags_has_data
        )

    @classmethod
    def _sanitize_testimony_card(cls, card: dict) -> dict:
        speaker = card.get("speaker")
        speaker_dict = speaker if isinstance(speaker, dict) else {}
        metrics_raw = card.get("metrics")
        metrics_list = metrics_raw if isinstance(metrics_raw, list) else []
        red_flags_raw = card.get("red_flags")
        red_flags_list = red_flags_raw if isinstance(red_flags_raw, list) else []

        sanitized_metrics: list[dict[str, str]] = []
        for metric in metrics_list:
            if not isinstance(metric, dict):
                continue
            metric_name = cls._normalize_text(metric.get("metric"))
            metric_value = cls._normalize_text(metric.get("value"))
            if not metric_name and not metric_value:
                continue
            sanitized_metrics.append({"metric": metric_name, "value": metric_value})

        sanitized_red_flags = [
            cls._normalize_text(flag)
            for flag in red_flags_list
            if cls._normalize_text(flag)
        ]

        return {
            "speaker": {
                "name": cls._normalize_text(speaker_dict.get("name")) or None,
                "role": cls._normalize_text(speaker_dict.get("role")) or None,
                "company": cls._normalize_text(speaker_dict.get("company")) or None,
            },
            "proof_claim": cls._normalize_text(card.get("proof_claim")),
            "metrics": sanitized_metrics,
            "intro_seed": cls._normalize_text(card.get("intro_seed")),
            "evidence_snippet": cls._normalize_text(card.get("evidence_snippet")),
            "red_flags": sanitized_red_flags,
        }

    def _build_company_brief_context(self, company_id: Optional[str]) -> str:
        if not company_id:
            return ""
        try:
            storage = get_storage_client(self.config)
        except Exception:
            return ""

        context = read_company_brief_context(storage, company_id, max_words=1200)
        if not isinstance(context, dict):
            return ""
        return self._normalize_text(context.get("content"))

    def _build_testimony_digest_videos(self, company_id: Optional[str]) -> list[dict]:
        if not company_id:
            return []
        try:
            storage = get_storage_client(self.config)
        except Exception as exc:
            print(f"[_build_testimony_digest_videos] Unable to initialize storage: {exc}")
            return []

        index_payload = read_testimony_digest_index(storage, company_id)
        if not isinstance(index_payload, dict):
            return []
        videos = index_payload.get("videos")
        if not isinstance(videos, list):
            return []

        testimony_videos: list[dict] = []
        for entry in videos:
            if not isinstance(entry, dict):
                continue
            has_cards = bool(entry.get("has_testimony_cards"))
            cards_count = int(entry.get("testimony_cards_count") or 0)
            if not has_cards or cards_count <= 0:
                continue

            video_id = self._normalize_text(entry.get("video_id"))
            if not video_id:
                continue

            digest_payload = read_video_testimony_digest(storage, company_id, video_id)
            if not isinstance(digest_payload, dict):
                continue
            cards_raw = digest_payload.get("testimony_cards")
            if not isinstance(cards_raw, list):
                continue

            valid_cards: list[dict] = []
            for raw_card in cards_raw:
                if not self._is_valid_testimony_card(raw_card):
                    continue
                if not isinstance(raw_card, dict):
                    continue
                valid_cards.append(self._sanitize_testimony_card(raw_card))

            if not valid_cards:
                continue
            testimony_videos.append(
                {
                    "video_id": video_id,
                    "testimony_cards": valid_cards,
                }
            )
        return testimony_videos

    def _get_run_lock(self, session_id: str) -> Lock:
        with self._run_locks_guard:
            lock = self._run_locks.get(session_id)
            if lock is None:
                lock = Lock()
                self._run_locks[session_id] = lock
            return lock

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
        
        # Resolve owner for event logging
        user_id, _ = self._resolve_session_owner(session_id)
        
        self.event_store.append(
            session_id,
            {"type": "run_start", "message": user_message},
            user_id=user_id,
        )
        
        # Save user message to chat history
        self.append_chat_message(session_id, "user", user_message)
        self._schedule_session_title_generation(session_id)
        
        try:
            with self._get_run_lock(session_id):
                result = None
                for attempt in Retrying(
                    retry=retry_if_exception(_is_retryable_rate_limit_error),
                    stop=stop_after_attempt(4),  # Initial attempt + up to 3 retries
                    wait=wait_exponential(multiplier=1, min=1, max=8),
                    reraise=True,
                ):
                    with attempt:
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
            uid, _ = self._resolve_session_owner(session_id)
            self.event_store.append(session_id, {"type": "run_end"}, user_id=uid)

    def get_events(self, session_id: str, cursor: Optional[int]) -> tuple[list[dict], int]:
        user_id, _ = self._resolve_session_owner(session_id)
        return self.event_store.read_since(session_id, cursor, user_id=user_id)

    def render_segments(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        return self.render_storyboard(session_id, output_filename)

    def render_storyboard(self, session_id: str, output_filename: str = "output.mp4") -> RenderResult:
        user_id, company_id = self._resolve_session_owner(session_id)
        scenes = self.storyboard_store.load(session_id, user_id=user_id) or []
        result = _render_storyboard_scenes(
            scenes,
            self.config,
            session_id,
            self.storyboard_store.base_dir,
            output_filename,
            company_id=company_id,
        )
        if not result.success:
            raise ValueError(result.error_message or "Storyboard render failed.")

        if result.output_path:
            local_output_path = Path(result.output_path)
            storage = get_storage_client(self.config)
            company_scope = company_id or "global"
            render_key = (
                f"companies/{company_scope}/generated/renders/"
                f"{session_id}/{local_output_path.name}"
            )
            storage.upload_from_filename(render_key, local_output_path, content_type="video/mp4")
            result.output_path = storage.get_url(render_key)

        print(f"[render_storyboard] Final output path: {result.output_path}")
        return result



    def generate_storyboard(self, session_id: str, brief: str) -> list[_StoryboardScene]:
        """Calls the generator directly for a text-only draft, bypassing TTS and Video matching."""
        user_id, _ = self._resolve_session_owner(session_id)
        generator = PersonalizedStoryGenerator(self.config)
        scenes = generator.plan_storyboard(brief)
        self.storyboard_store.save(session_id, scenes, user_id=user_id)
        # if brief:
        #     self.brief_store.save(session_id, brief) # Cannot save raw string to BriefStore
        return scenes

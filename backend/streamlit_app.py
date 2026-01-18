import json
import os
import shutil
import time
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import streamlit as st

from videoagent.config import Config
from videoagent.editor import VideoEditor
from videoagent.library import VideoLibrary
from videoagent.models import SegmentType, StorySegment, VoiceOver
from videoagent.story import _StoryboardScene
from videoagent.voice import VoiceOverGenerator

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    repo_env = Path(__file__).resolve().parents[1] / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)
    else:
        load_dotenv()

APP_TITLE = "VideoAgent Studio"
DEFAULT_API_BASE = "http://localhost:8000"
LLM_EXECUTOR = ThreadPoolExecutor(max_workers=2)

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@500;600&family=Sora:wght@400;500;600&display=swap');

:root {
  --bg: #f7f6f3;
  --panel: #ffffff;
  --panel-2: #f2f1ee;
  --text: #1f2328;
  --muted: #5b6470;
  --accent: #0f766e;
  --border: #e4e1dc;
  --shadow: rgba(15, 23, 42, 0.06);
}

html, body, [class*="stApp"] {
  background: linear-gradient(180deg, #fbfaf7 0%, #f3f4f6 100%);
  color: var(--text);
  font-family: 'Sora', sans-serif;
}

h1, h2, h3, h4 {
h1, h2, h3, h4 {
  font-family: 'Fraunces', serif;
  color: var(--text);
  letter-spacing: 0.2px;
}

.stTabs > [data-baseweb="tab-list"] {
  gap: 0.6rem;
}

.stTabs > [data-baseweb="tab-list"] div {
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  background: var(--panel-2);
  border: 1px solid var(--border);
}

.stTabs > [data-baseweb="tab-list"] button[aria-selected="true"] div {
  background: var(--panel);
  box-shadow: 0 8px 16px var(--shadow);
}

.stTabs [data-baseweb="tab-panel"] {
  border: none;
  padding-top: 0.8rem;
}

.stTabs [data-baseweb="tab-panel"] > div > div {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
}

.stTabs [data-baseweb="tab-panel"] .stMarkdown > div {
  box-shadow: none;
}

.stTabs [data-baseweb="tab-panel"] hr {
  display: none;
}

.stTabs [data-baseweb="tab-panel"] .stContainer,
.stTabs [data-baseweb="tab-panel"] .stElementContainer,
.stTabs [data-baseweb="tab-panel"] .stTextInput,
.stTabs [data-baseweb="tab-panel"] .stTextArea,
.stTabs [data-baseweb="tab-panel"] .stButton,
.stTabs [data-baseweb="tab-panel"] .stMetric,
.stTabs [data-baseweb="tab-panel"] .stCaptionContainer {
  background: transparent !important;
}

.stApp header {
  background: transparent;
}

.stMarkdown p {
  color: var(--text);
}

.block-container {
  padding-top: 1.6rem;
  padding-bottom: 2.6rem;
}

.va-top {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.4rem 0.2rem 1rem 0.2rem;
  border-bottom: 1px solid var(--border);
}

.va-top h1 {
  margin: 0;
  font-size: 2rem;
}

.va-top p {
  margin: 0.4rem 0 0 0;
  color: var(--muted);
}

.va-muted {
  color: var(--muted);
  font-size: 0.85rem;
}

.va-status {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}

.va-preview {
  border-radius: 10px;
  padding: 1rem;
  background: var(--panel-2);
  border: 1px dashed var(--border);
  text-align: center;
}
</style>
"""


def init_state() -> None:
    defaults = {
        "session_id": None,
        "messages": [],
        "render_result": None,
        "selected_segment_id": None,
        "brief": "",
        "activity": [],
        "storyboard_scenes": [],
        "llm_inflight": False,
        "llm_future": None,
        "llm_events_cursor": None,
        "llm_events": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def log_activity(message: str) -> None:
    st.session_state.activity.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
    })


def api_base() -> str:
    return st.session_state.get("api_base", DEFAULT_API_BASE).rstrip("/")


def api_request(method: str, path: str, payload: Optional[dict] = None) -> dict:
    url = f"{api_base()}{path}"
    response = requests.request(method, url, json=payload, timeout=1200)
    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"{response.status_code} {detail}")
    return response.json()


def api_get_events(session_id: str, cursor: Optional[int] = None) -> dict:
    url = f"{api_base()}/agent/sessions/{session_id}/events"
    params = {}
    if cursor is not None:
        params["cursor"] = cursor
    response = requests.get(url, params=params, timeout=30)
    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"{response.status_code} {detail}")
    return response.json()


def format_event(event: dict) -> str:
    event_type = event.get("type", "event")
    name = event.get("name")
    status = event.get("status")
    if event_type == "run_start":
        return "Agent started thinking..."
    if event_type == "run_end":
        return "Agent finished."
    if event_type == "tool_start":
        return f"Calling tool: {name}"
    if event_type == "tool_end":
        suffix = "ok" if status == "ok" else "error"
        return f"Tool finished: {name} ({suffix})"
    if event_type == "auto_render_start":
        return "Auto render started..."
    if event_type == "auto_render_end":
        suffix = "ok" if status == "ok" else "error"
        return f"Auto render finished ({suffix})"
    if event_type == "auto_render_skipped":
        return event.get("error", "Auto render skipped")
    if event_type == "segment_warning":
        return event.get("message", "Segment warning")
    return event.get("message", event_type)


def render_events(events: list[dict]) -> str:
    if not events:
        return "Waiting for agent activity..."
    lines = [f"- {format_event(event)}" for event in events[-12:]]
    return "\n".join(lines)


def api_get(path: str) -> dict:
    return api_request("GET", path)


def api_post(path: str, payload: Optional[dict] = None) -> dict:
    return api_request("POST", path, payload)


def api_patch(path: str, payload: dict) -> dict:
    return api_request("PATCH", path, payload)


def format_seconds(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}s"


def segment_label(segment: StorySegment) -> str:
    return segment.segment_type.value.replace("_", " ").title()


def segment_status(segment: StorySegment) -> str:
    if segment.segment_type == SegmentType.VIDEO_CLIP:
        return "matched"
    return "storyboard"


def segment_summary(segment: StorySegment) -> str:
    if segment.segment_type == SegmentType.VIDEO_CLIP:
        content = segment.content
        return f"Clip {content.start_time:.2f}-{content.end_time:.2f}s"
    return "Clip"


def voice_summary(segment: StorySegment) -> str:
    if not segment.voice_over:
        return "No voice over"
    script = segment.voice_over.script
    if len(script) > 100:
        return f"{script[:97]}..."
    return script


def prompt_match_all() -> str:
    return (
        "First create StorySegments for every storyboard scene and call update_segments with the full list. "
        "Each segment should be a video_clip. Use scan_library/search tools to find the best clip and set "
        "source_video_id, start_time, end_time, "
        "and description. Include storyboard_scene_id on each segment so voice overs can be paired later. "
        "If the clip should keep original audio (e.g., testimonial), set keep_original_audio=true and "
        "include transcript text; otherwise set keep_original_audio=false. "
        "When matching video_clip segments, first identify up to 10 candidate video ids from transcripts, "
        "then call match_scene_to_video with the segment id, candidate ids, and any notes for context. "
        "Review the returned candidates and update the segment yourself with the chosen clip. "
        "After segments are saved, call generate_voice_overs with the list of segment ids that need voice "
        "over audio (the script must already be set on each segment's voice_over)."
    )


def prompt_refine_segment(segment: StorySegment, note: str) -> str:
    return (
        f"Update only the segment with id {segment.id} (order {segment.order}). "
        f"Apply this instruction: {note}. "
        "Keep all other segments unchanged and return the full list."
    )


def build_llm_prompt(user_prompt: str, segments: Optional[list[StorySegment]]) -> str:
    return user_prompt


def start_llm_action(prompt: str, label: str, segments: Optional[list[StorySegment]] = None) -> None:
    if not st.session_state.session_id:
        st.warning("Create a session first.")
        return
    if st.session_state.llm_inflight:
        st.warning("An LLM request is already running.")
        return
    st.session_state.messages.append({"role": "user", "content": label})
    try:
        cursor_payload = api_get_events(st.session_state.session_id)
        st.session_state.llm_events_cursor = cursor_payload.get("next_cursor")
    except Exception:
        st.session_state.llm_events_cursor = None
    st.session_state.llm_events = []
    payload = {
        "session_id": st.session_state.session_id,
        "message": build_llm_prompt(prompt, segments),
    }
    st.session_state.llm_future = LLM_EXECUTOR.submit(api_post, "/agent/chat", payload)
    st.session_state.llm_inflight = True
    log_activity(label)
    st.rerun()


def poll_llm_action() -> None:
    if not st.session_state.llm_inflight:
        return
    status = st.status("Thinking...", expanded=True)
    events_box = st.empty()
    while True:
        future: Optional[Future] = st.session_state.llm_future
        if future is None:
            break
        if future.done():
            try:
                output = future.result()
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": output.get("message", ""),
                })
                if "scenes" in output:
                    st.session_state.storyboard_scenes = [
                        _StoryboardScene.model_validate(item) for item in (output.get("scenes") or [])
                    ]
                customer_details = output.get("customer_details")
                if customer_details is not None:
                    st.session_state.brief = customer_details
            except Exception as exc:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error: {exc}",
                })
            st.session_state.llm_inflight = False
            st.session_state.llm_future = None
            st.session_state.llm_events = []
            st.session_state.llm_events_cursor = None
            status.update(label="Done", state="complete")
            st.rerun()
            return
        try:
            cursor = st.session_state.llm_events_cursor
            response = api_get_events(st.session_state.session_id, cursor)
            new_events = response.get("events") or []
            st.session_state.llm_events_cursor = response.get("next_cursor", cursor)
            if new_events:
                st.session_state.llm_events.extend(new_events)
        except Exception as exc:
            st.session_state.llm_events.append({"type": "message", "message": f"Event polling error: {exc}"})
        events_box.markdown(render_events(st.session_state.llm_events))
        last_event = st.session_state.llm_events[-1] if st.session_state.llm_events else None
        if last_event and last_event.get("type") == "tool_start":
            status.update(label=f"Calling {last_event.get('name')}")
        time.sleep(0.4)


def fetch_segments(session_id: str) -> tuple[Optional[list[StorySegment]], Optional[str], Optional[list[dict]]]:
    plan = None
    parse_error = None
    raw = None
    if session_id:
        try:
            data = api_get(f"/agent/sessions/{session_id}/plan")
            raw = data.get("segments")
        except Exception as exc:
            parse_error = str(exc)
            return None, parse_error, raw
    if raw:
        try:
            plan = [StorySegment.model_validate(item) for item in raw]
        except Exception as exc:
            parse_error = str(exc)
    return plan, parse_error, raw


def fetch_storyboard(
    session_id: str,
) -> tuple[Optional[list[_StoryboardScene]], Optional[str], Optional[list[dict]]]:
    scenes = None
    parse_error = None
    raw = None
    if session_id:
        try:
            data = api_get(f"/agent/sessions/{session_id}/storyboard")
            raw = data.get("scenes")
        except Exception as exc:
            parse_error = str(exc)
            return None, parse_error, raw
    if raw is not None:
        try:
            scenes = [_StoryboardScene.model_validate(item) for item in raw]
        except Exception as exc:
            parse_error = str(exc)
    return scenes, parse_error, raw


def save_segments(session_id: str, segments: list[StorySegment]) -> None:
    payload = {
        "segments": [segment.model_dump(mode="json") for segment in segments]
    }
    api_patch(f"/agent/sessions/{session_id}/plan", payload)


def save_storyboard(session_id: str, scenes: list[_StoryboardScene]) -> None:
    payload = {
        "scenes": [scene.model_dump(mode="json") for scene in scenes]
    }
    api_patch(f"/agent/sessions/{session_id}/storyboard", payload)


def ensure_order(segments: list[StorySegment]) -> list[StorySegment]:
    for index, segment in enumerate(segments):
        segment.order = index
    return segments


def next_scene_id(scenes: list[_StoryboardScene]) -> str:
    return f"scene_{len(scenes) + 1}"


def compute_progress(segments: Optional[list[StorySegment]]) -> dict:
    total = len(segments) if segments else 0
    matched = 0
    voiced = 0
    for segment in segments or []:
        if segment.segment_type == SegmentType.VIDEO_CLIP:
            matched += 1
        if segment.voice_over:
            audio_path = resolve_voice_over_path(segment, st.session_state.session_id)
            if audio_path and audio_path.exists():
                voiced += 1
    return {
        "total": total,
        "matched": matched,
        "voiced": voiced,
    }


def get_library_dir() -> Path:
    try:
        debug = api_get("/agent/debug")
        return Path(debug["library_dir"])
    except Exception:
        return Config().video_library_path


@st.cache_resource
def load_library(library_dir: str) -> VideoLibrary:
    config = Config()
    config.video_library_path = Path(library_dir)
    library = VideoLibrary(config)
    library.scan_library()
    return library


def resolve_video_path(segment: StorySegment, library_dir: Path) -> Optional[Path]:
    if segment.segment_type != SegmentType.VIDEO_CLIP:
        return None
    content = segment.content
    if not content.source_video_id:
        return None
    library = load_library(str(library_dir))
    metadata = library.get_video(content.source_video_id)
    if metadata and metadata.path.exists():
        return metadata.path
    return None


@st.cache_data(show_spinner=False)
def get_video_duration(path: str) -> Optional[float]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def preview_dir(session_id: str) -> Path:
    base = Config().output_dir / "streamlit_previews" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def voice_dir(session_id: str) -> Path:
    base = Config().output_dir / "streamlit_voiceovers" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def voice_over_path_for_id(session_id: str, audio_id: str) -> Optional[Path]:
    candidates = [
        voice_dir(session_id) / f"vo_{audio_id}.wav",
        Config().output_dir / "agent_sessions" / session_id / "voice_overs" / f"vo_{audio_id}.wav",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def resolve_voice_over_path(segment: StorySegment, session_id: str) -> Optional[Path]:
    voice_over = segment.voice_over
    if not voice_over or not voice_over.audio_id or not session_id:
        return None
    return voice_over_path_for_id(session_id, voice_over.audio_id)


def preview_path_for_segment(segment: StorySegment, session_id: str) -> Optional[Path]:
    if segment.segment_type != SegmentType.VIDEO_CLIP:
        return None
    content = segment.content
    token = f"{segment.id}_{int(content.start_time * 1000)}_{int(content.end_time * 1000)}"
    voice_token = ""
    audio_path = resolve_voice_over_path(segment, session_id)
    if audio_path and audio_path.exists():
        try:
            voice_token = f"_vo_{int(audio_path.stat().st_mtime)}"
        except (OSError, ValueError):
            voice_token = ""
    return preview_dir(session_id) / f"preview_{token}{voice_token}.mp4"


def build_preview(segment: StorySegment, session_id: str, library_dir: Path) -> Optional[Path]:
    if segment.segment_type != SegmentType.VIDEO_CLIP:
        return None
    video_path = resolve_video_path(segment, library_dir)
    audio_path = resolve_voice_over_path(segment, session_id)
    content = segment.content
    if not video_path:
        return None
    duration = get_video_duration(str(video_path))
    if duration is not None and (content.start_time >= duration or content.end_time > duration):
        return None
    output_path = preview_path_for_segment(segment, session_id)
    if output_path is None:
        return None
    if output_path.exists():
        return output_path
    editor = VideoEditor(Config())
    try:
        if audio_path and audio_path.exists():
            segment = segment.model_copy(deep=True)
            rendered = editor.render_segment(
                segment,
                normalize=False,
                voice_over_path=audio_path,
            )
            shutil.copy(rendered, output_path)
        else:
            editor.cut_video_segment(content, output_path)
    finally:
        editor.cleanup()
    return output_path if output_path.exists() else None


def generate_voice_over(segment: StorySegment, session_id: str) -> Optional[VoiceOver]:
    if not segment.voice_over or not segment.voice_over.script.strip():
        return None
    output_path = voice_dir(session_id) / f"vo_{segment.id}.wav"
    generator = VoiceOverGenerator(Config())
    try:
        voice = segment.voice_over.voice or Config().tts_voice
        vo = generator.generate_voice_over(
            segment.voice_over.script,
            voice=voice,
            speed=segment.voice_over.speed,
            output_path=output_path,
        )
        vo.audio_id = segment.id
        vo.volume = segment.voice_over.volume
        return vo
    finally:
        generator.cleanup()


st.set_page_config(page_title=APP_TITLE, layout="wide")
init_state()

st.markdown(STYLE, unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="va-top">
      <div>
        <h1>{APP_TITLE}</h1>
        <p class="va-muted">Chat, craft the storyboard, match footage, and render a polished sales video.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Session")
    st.text_input("API Base URL", value=api_base(), key="api_base")

    api_ok = False
    try:
        health = api_get("/health")
        api_ok = health.get("status") == "ok"
    except Exception:
        api_ok = False

    if api_ok:
        st.success("API: healthy")
    else:
        st.error("API: unreachable")

    def _create_session() -> None:
        data = api_post("/agent/sessions")
        st.session_state.session_id = data["session_id"]
        st.session_state.messages = []
        st.session_state.render_result = None
        st.session_state.selected_segment_id = None
        st.session_state.activity = []
        st.session_state.storyboard_scenes = []

    if st.button("New session"):
        try:
            _create_session()
        except Exception as exc:
            st.error(f"Failed to create session: {exc}")

    if api_ok and not st.session_state.session_id:
        try:
            _create_session()
        except Exception:
            pass

    session_input = st.text_input("Session ID", value=st.session_state.session_id or "")
    if st.button("Load session", key="load_session"):
        if not session_input.strip():
            st.warning("Enter a session id to load.")
        else:
            st.session_state.session_id = session_input.strip()
            st.session_state.messages = []
            st.session_state.render_result = None
            st.session_state.selected_segment_id = None
            st.session_state.activity = []
            st.session_state.storyboard_scenes = []
            st.rerun()

    st.subheader("Environment")
    if os.environ.get("GEMINI_API_KEY"):
        st.success("GEMINI_API_KEY set")
    else:
        st.warning("GEMINI_API_KEY not set")
    try:
        debug = api_get("/agent/debug")
        st.caption(f"Model: {debug.get('model', 'unknown')}")
        st.caption(f"Library: {debug.get('library_dir', 'unknown')}")
    except Exception:
        st.caption(f"Model: {os.environ.get('AGENT_MODEL', 'gemini/gemini-3-pro-preview')}")

segments, parse_error, raw_plan = fetch_segments(st.session_state.session_id)
storyboard_scenes, storyboard_error, raw_storyboard = fetch_storyboard(
    st.session_state.session_id
)
if storyboard_scenes is not None:
    st.session_state.storyboard_scenes = storyboard_scenes
if segments:
    segments = sorted(segments, key=lambda s: s.order)
    if st.session_state.selected_segment_id not in {seg.id for seg in segments}:
        st.session_state.selected_segment_id = segments[0].id

st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

main_cols = st.columns([1, 2])

with main_cols[0]:
    st.markdown("**Chat**")
    st.caption("Quick chat with the LLM.")

    chat_box = st.container(height=600)
    with chat_box:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

    user_prompt = st.chat_input(
        "Message the LLM",
        disabled=st.session_state.llm_inflight,
    )
    if user_prompt:
        start_llm_action(user_prompt, user_prompt, segments)

with main_cols[1]:
    tab_story, tab_match, tab_render = st.tabs(
        ["Storyboard", "Video Matching", "Final Render"]
    )

    with tab_story:
        st.markdown("**Project Brief**")
        brief = st.text_area(
            "Describe the customer situation and desired outcome",
            value=st.session_state.brief,
            height=140,
        )
        st.session_state.brief = brief

        brief_actions = st.columns([1, 1])
        with brief_actions[0]:
            if st.button("Draft storyboard", key="draft_storyboard"):
                if not brief.strip():
                    st.warning("Add a brief first.")
                else:
                    with st.spinner("Planning storyboard..."):
                        try:
                            payload = {"session_id": st.session_state.session_id, "brief": brief}
                            response = api_post("/agent/storyboard/draft", payload)
                            st.session_state.storyboard_scenes = [
                                _StoryboardScene.model_validate(item)
                                for item in response.get("scenes", [])
                            ]
                            st.session_state.messages.append({"role": "user", "content": "Draft storyboard from brief"})
                            st.session_state.messages.append({"role": "assistant", "content": "I've created a draft storyboard based on your brief."})
                            log_activity("Drafted storyboard")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
        with brief_actions[1]:
            if st.button("Refresh plan", key="refresh_plan_story"):
                st.rerun()

        st.divider()
        st.markdown("**Storyboard**")
        scenes = list(st.session_state.storyboard_scenes or [])
        if storyboard_error:
            st.error(f"Failed to load storyboard: {storyboard_error}")
        elif not scenes:
            st.info("No storyboard yet. Draft from the brief or chat with the LLM.")
            if st.button("Add first scene", key="add_first_story_scene"):
                if not st.session_state.session_id:
                    st.warning("Create a session first.")
                else:
                    new_scene = _StoryboardScene(
                        scene_id=next_scene_id([]),
                        title="New scene",
                        purpose="Describe the purpose of this scene.",
                        script="",
                    )
                    save_storyboard(st.session_state.session_id, [new_scene])
                    log_activity("Added first storyboard scene")
                    st.rerun()
        else:
            for index, scene in enumerate(scenes, start=1):
                header = f"{index}. {scene.title}"
                with st.expander(header, expanded=index == 1):
                    st.caption(f"Scene id: {scene.scene_id}")
                    action_cols = st.columns([1, 1, 1])
                    with action_cols[0]:
                        if st.button("Move up", key=f"scene_up_{scene.scene_id}") and index > 1:
                            scenes[index - 2], scenes[index - 1] = (
                                scenes[index - 1],
                                scenes[index - 2],
                            )
                            save_storyboard(st.session_state.session_id, scenes)
                            st.rerun()
                    with action_cols[1]:
                        if st.button("Move down", key=f"scene_down_{scene.scene_id}") and index < len(scenes):
                            scenes[index - 1], scenes[index] = (
                                scenes[index],
                                scenes[index - 1],
                            )
                            save_storyboard(st.session_state.session_id, scenes)
                            st.rerun()
                    with action_cols[2]:
                        if st.button("Delete", key=f"scene_delete_{scene.scene_id}"):
                            scenes.pop(index - 1)
                            save_storyboard(st.session_state.session_id, scenes)
                            st.rerun()

                    st.markdown("---")
                    title = st.text_input(
                        "Title",
                        value=scene.title,
                        key=f"scene_title_{scene.scene_id}",
                    )
                    purpose = st.text_area(
                        "Purpose",
                        value=scene.purpose,
                        height=80,
                        key=f"scene_purpose_{scene.scene_id}",
                    )
                    script = st.text_area(
                        "Voice over script",
                        value=scene.script,
                        height=120,
                        key=f"scene_script_{scene.scene_id}",
                    )
                    if st.button("Apply changes", key=f"scene_apply_{scene.scene_id}"):
                        scenes[index - 1] = _StoryboardScene(
                            scene_id=scene.scene_id,
                            title=title,
                            purpose=purpose,
                            script=script,
                        )
                        save_storyboard(st.session_state.session_id, scenes)
                        log_activity(f"Edited scene {index}")
                        st.rerun()

            st.markdown("---")
            st.markdown("**Add Scene**")
            if st.button("Add storyboard scene", key="add_storyboard_scene"):
                new_scene = _StoryboardScene(
                    scene_id=next_scene_id(scenes),
                    title="New scene",
                    purpose="Describe the purpose of this scene.",
                    script="",
                )
                scenes.append(new_scene)
                save_storyboard(st.session_state.session_id, scenes)
                log_activity("Added storyboard scene")
                st.rerun()

            with st.expander("Raw storyboard JSON"):
                plan_text = st.text_area(
                    "Edit storyboard scenes JSON",
                    value=json.dumps(raw_storyboard, indent=2)
                    if raw_storyboard is not None
                    else "",
                    height=200,
                )
                if st.button("Apply JSON", key="apply_story_json"):
                    try:
                        data = json.loads(plan_text)
                        if not isinstance(data, list):
                            raise ValueError("Expected a JSON array of storyboard scenes.")
                        updated_scenes = [_StoryboardScene.model_validate(item) for item in data]
                        save_storyboard(st.session_state.session_id, updated_scenes)
                        log_activity("Applied storyboard JSON")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Invalid storyboard JSON: {exc}")

        st.divider()
        st.markdown("**LLM Actions**")
        note = st.text_input("Instruction for selected segment", key="revise_note")
        if st.button("Revise selected segment", key="revise_segment_button"):
            if not segments:
                st.warning("No segments to revise yet.")
            elif not st.session_state.selected_segment_id:
                st.warning("Select a segment first.")
            elif not note.strip():
                st.warning("Add a revision instruction.")
            else:
                selected = next(
                    seg for seg in segments if seg.id == st.session_state.selected_segment_id
                )
                start_llm_action(prompt_refine_segment(selected, note), "Revise selected segment", segments)

        st.markdown("**Activity Log**")
        if st.session_state.activity:
            for entry in st.session_state.activity[-6:][::-1]:
                st.write(f"{entry['time']} - {entry['message']}")
        else:
            st.caption("No activity yet.")

    with tab_match:
        st.markdown("**Video Matching**")
        match_cols = st.columns([1, 1])
        with match_cols[0]:
            if st.button("Match clips (LLM)", key="match_clips"):
                start_llm_action(prompt_match_all(), "Match storyboard to clips", segments)
        with match_cols[1]:
            if st.button("Refresh plan", key="refresh_plan_match"):
                st.rerun()

        if not segments:
            if st.session_state.storyboard_scenes:
                st.info("Storyboard scenes drafted. Create segments before matching clips.")
            else:
                st.info("No storyboard yet. Draft the storyboard first.")
        else:
            segment_ids = [seg.id for seg in segments]
            labels = {
                seg.id: f"{seg.order + 1}. {segment_label(seg)}"
                for seg in segments
            }
            selected_index = 0
            if st.session_state.selected_segment_id in segment_ids:
                selected_index = segment_ids.index(st.session_state.selected_segment_id)
            selected_id = st.selectbox(
                "Selected segment",
                segment_ids,
                index=selected_index,
                format_func=lambda sid: labels[sid],
                key="match_segment_select",
            )
            st.session_state.selected_segment_id = selected_id
            selected = next(seg for seg in segments if seg.id == selected_id)
            st.caption(f"Segment {selected.order + 1} - {segment_label(selected)}")

            if selected.segment_type != SegmentType.VIDEO_CLIP:
                st.warning("Unsupported segment type.")
            else:
                library_dir = get_library_dir()
                video_path = resolve_video_path(selected, library_dir)
                content = selected.content
                st.markdown("**Matched Clip**")
                st.write(content.description or "No description")
                st.caption(f"Source id: {content.source_video_id}")
                st.caption(
                    f"Range: {format_seconds(content.start_time)} to {format_seconds(content.end_time)}"
                )
                if video_path:
                    st.caption(f"Path: {video_path}")
                    duration = get_video_duration(str(video_path))
                    if duration is not None and (content.start_time >= duration or content.end_time > duration):
                        st.error(
                            f"Clip range is outside the video duration ({duration:.2f}s). "
                            "Update the segment timestamps."
                        )
                preview_path = preview_path_for_segment(selected, st.session_state.session_id)
                if preview_path and preview_path.exists():
                    st.video(str(preview_path))
                else:
                    with st.spinner("Generating preview clip..."):
                        preview_path = build_preview(
                            selected,
                            st.session_state.session_id,
                            library_dir,
                        )
                    if preview_path:
                        log_activity("Generated preview clip")
                        st.video(str(preview_path))
                    elif video_path and video_path.exists():
                        st.caption("Preview unavailable; showing full clip from the start time.")
                        st.video(str(video_path), start_time=int(content.start_time))

            st.markdown("---")
            st.markdown("**Voice Over**")
            if selected.voice_over:
                st.write(selected.voice_over.script)
                audio_path = resolve_voice_over_path(selected, st.session_state.session_id)
                if audio_path and audio_path.exists():
                    st.audio(str(audio_path))
                else:
                    st.caption("No audio file yet.")
            else:
                st.caption("No voice over script yet.")

            if st.button("Generate voice over audio", key="generate_voice_match"):
                if not selected.voice_over or not selected.voice_over.script.strip():
                    st.warning("Add a script first.")
                else:
                    voice = generate_voice_over(selected, st.session_state.session_id)
                    if voice:
                        updated = selected.model_copy(deep=True)
                        updated.voice_over = voice
                        for idx, seg in enumerate(segments):
                            if seg.id == updated.id:
                                segments[idx] = updated
                                break
                        save_segments(
                            st.session_state.session_id,
                            ensure_order(segments),
                        )
                        log_activity("Generated voice over")
                        st.rerun()

    with tab_render:
        render_col, output_col = st.columns([1, 2])
        with render_col:
            st.markdown("**Render**")
            if st.button("Render final video", key="render_final"):
                try:
                    if not st.session_state.session_id:
                        st.warning("Create a session first.")
                    else:
                        data = api_post(f"/agent/sessions/{st.session_state.session_id}/render")
                        st.session_state.render_result = data.get("render_result")
                        log_activity("Render requested")
                except Exception as exc:
                    st.session_state.render_result = None
                    st.error(f"Render failed: {exc}")

            if st.session_state.render_result:
                result = st.session_state.render_result
                if result.get("success"):
                    st.success("Render complete")
                else:
                    st.error(result.get("error_message") or "Render failed")

        with output_col:
            st.markdown("**Output**")
            result = st.session_state.render_result
            if result and result.get("success") and result.get("output_path"):
                st.video(result["output_path"])
                st.caption(result["output_path"])
            else:
                st.info("No rendered output yet.")

with main_cols[0]:
    if st.session_state.llm_inflight:
        poll_llm_action()

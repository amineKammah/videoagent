import base64
import json
import os
import time
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import streamlit as st

from videoagent.config import Config
from videoagent.library import VideoLibrary
from videoagent.story import _StoryboardScene

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
        "brief": "",
        "activity": [],
        "storyboard_scenes": [],
        "llm_inflight": False,
        "llm_future": None,
        "llm_events_cursor": None,
        "llm_events": [],
        "render_events_cursor": None,
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

def process_render_events(events: list[dict]) -> None:
    for event in events:
        event_type = event.get("type")
        if event_type == "auto_render_end":
            status = event.get("status")
            output = event.get("output")
            if status == "ok" and output:
                st.session_state.render_result = {
                    "success": True,
                    "output_path": output,
                }
            elif status == "error":
                st.session_state.render_result = {
                    "success": False,
                    "error_message": event.get("error") or "Auto render failed",
                }
        elif event_type == "auto_render_skipped":
            st.session_state.render_result = {
                "success": False,
                "error_message": event.get("error") or "Auto render skipped",
            }


def refresh_render_from_events() -> None:
    session_id = st.session_state.get("session_id")
    if not session_id or st.session_state.llm_inflight:
        return
    cursor = st.session_state.render_events_cursor
    try:
        response = api_get_events(session_id, cursor)
    except Exception:
        return
    new_events = response.get("events") or []
    st.session_state.render_events_cursor = response.get("next_cursor", cursor)
    if new_events:
        process_render_events(new_events)


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

def scene_is_matched(scene: _StoryboardScene) -> bool:
    return scene.matched_scene is not None


def prompt_match_all() -> str:
    return (
        "Use the storyboard scenes as the single source of truth. "
        "For each scene, identify up to 5 candidate video ids from transcripts and call match_scene_to_video "
        "with the scene_id, candidate ids, and notes. "
        "Review the returned candidates and update matched_scene on each storyboard scene with "
        "segment_type, source_video_id, start_time, end_time, description, and keep_original_audio. "
        "Then call update_storyboard with the full updated scene list."
    )


def build_llm_prompt(user_prompt: str) -> str:
    return user_prompt


def start_llm_action(prompt: str, label: str) -> None:
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
        "message": build_llm_prompt(prompt),
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
                process_render_events(new_events)
        except Exception as exc:
            st.session_state.llm_events.append({"type": "message", "message": f"Event polling error: {exc}"})
        events_box.markdown(render_events(st.session_state.llm_events))
        last_event = st.session_state.llm_events[-1] if st.session_state.llm_events else None
        if last_event and last_event.get("type") == "tool_start":
            status.update(label=f"Calling {last_event.get('name')}")
        time.sleep(0.4)


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

def save_storyboard(session_id: str, scenes: list[_StoryboardScene]) -> None:
    payload = {
        "scenes": [scene.model_dump(mode="json") for scene in scenes]
    }
    api_patch(f"/agent/sessions/{session_id}/storyboard", payload)


def next_scene_id(scenes: list[_StoryboardScene]) -> str:
    return f"scene_{len(scenes) + 1}"


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


def resolve_video_path(scene: _StoryboardScene, library_dir: Path) -> Optional[Path]:
    matched_scene = scene.matched_scene
    if not matched_scene or not matched_scene.source_video_id:
        return None
    library = load_library(str(library_dir))
    metadata = library.get_video(matched_scene.source_video_id)
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


@st.cache_data(show_spinner="Loading video...")
def get_video_base64(path: str) -> Optional[str]:
    """Read video file and encode as base64 data URL for HTML5 video player."""
    try:
        video_path = Path(path)
        if not video_path.exists():
            return None
        # Determine MIME type based on extension
        ext = video_path.suffix.lower()
        mime_types = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".ogg": "video/ogg",
            ".mov": "video/quicktime",
        }
        mime_type = mime_types.get(ext, "video/mp4")
        with open(path, "rb") as f:
            video_bytes = f.read()
        b64 = base64.b64encode(video_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"
    except Exception:
        return None


st.set_page_config(page_title=APP_TITLE, layout="wide")
init_state()
refresh_render_from_events()

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

storyboard_scenes, storyboard_error, raw_storyboard = fetch_storyboard(
    st.session_state.session_id
)
if storyboard_scenes is not None:
    st.session_state.storyboard_scenes = storyboard_scenes

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
        start_llm_action(user_prompt, user_prompt)

with main_cols[1]:
    with st.container():
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
            if st.button("Refresh storyboard", key="refresh_plan_story"):
                st.rerun()

        st.divider()
        st.markdown("**Rendered Video**")
        render_cols = st.columns([1, 2])
        with render_cols[0]:
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
        with render_cols[1]:
            result = st.session_state.render_result
            if result and result.get("success") and result.get("output_path"):
                output_path = result["output_path"]
                
                # Initialize problem report state in session state
                if "problem_report_text" not in st.session_state:
                    st.session_state.problem_report_text = ""
                if "problem_report_active" not in st.session_state:
                    st.session_state.problem_report_active = False
                if "last_report_ts" not in st.session_state:
                    st.session_state.last_report_ts = None
                
                # Custom HTML5 video player with Report Problem button
                # Encode video as base64 data URL for browser access
                video_data_url = get_video_base64(output_path)
                if video_data_url is None:
                    st.error(f"Could not load video: {output_path}")
                else:
                    video_html = f'''
<div style="position: relative; width: 100%;">
    <video id="customVideoPlayer" controls style="width: 100%; border-radius: 8px; background: #000;">
        <source src="{video_data_url}" type="video/mp4">
        Your browser does not support the video tag.
    </video>
    <div style="margin-top: 8px;">
        <button id="reportProblemBtn" style="
            background: #ffffff;
            color: #1f2328;
            border: 1px solid #e4e1dc;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-family: 'Sora', sans-serif;
            font-size: 14px;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: transform 0.1s, box-shadow 0.2s, background 0.2s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.06);
        " onmouseover="this.style.background='#f7f6f3'; this.style.boxShadow='0 4px 8px rgba(0,0,0,0.1)';"
           onmouseout="this.style.background='#ffffff'; this.style.boxShadow='0 2px 4px rgba(0,0,0,0.06)';">
            🚩 Report a Problem
        </button>
    </div>
</div>
<script>
    (function() {{
        const video = document.getElementById('customVideoPlayer');
        const reportBtn = document.getElementById('reportProblemBtn');
        
        if (reportBtn && video) {{
            reportBtn.addEventListener('click', function() {{
                video.pause();
                const currentTime = video.currentTime;
                // Update parent URL with timestamp to communicate with Streamlit
                const url = new URL(window.parent.location.href);
                window.parent.postMessage({{
                    isStreamlitMessage: true,
                    type: 'streamlit:setComponentValue',
                    value: currentTime.toFixed(3)
                }}, '*');
            }});
        }}
    }})();
</script>
'''
                    report_ts_value = st.components.v1.html(
                        video_html,
                        height=380
                    )
                    st.caption(output_path)
                    if report_ts_value:
                        try:
                            ts_seconds = float(report_ts_value)
                            if ts_seconds != st.session_state.last_report_ts:
                                # Format as MM:SS
                                minutes = int(ts_seconds // 60)
                                seconds = int(ts_seconds % 60)
                                formatted_ts = f"[{minutes}:{seconds:02d}] "
                                if st.session_state.problem_report_text:
                                    st.session_state.problem_report_text += (
                                        "\n\n" + formatted_ts
                                    )
                                else:
                                    st.session_state.problem_report_text = formatted_ts
                                st.session_state.problem_report_active = True
                                st.session_state.last_report_ts = ts_seconds
                        except (ValueError, TypeError):
                            pass

                # Problem report text area - show after the first report action
                if st.session_state.problem_report_active:
                    st.markdown("**Problem Reports:**")
                    problem_text = st.text_area(
                        "Describe issues at each timestamp",
                        value=st.session_state.problem_report_text,
                        height=320,
                        key="problem_report_textarea",
                        label_visibility="collapsed"
                    )
                    st.session_state.problem_report_text = problem_text
            else:
                st.info("No rendered output yet.")

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
                        scenes[index - 1] = scene.model_copy(
                            update={
                                "title": title,
                                "purpose": purpose,
                                "script": script,
                            }
                        )
                        save_storyboard(st.session_state.session_id, scenes)
                        log_activity(f"Edited scene {index}")
                        st.rerun()

                    st.markdown("**Matched Clip**")
                    if scene_is_matched(scene):
                        matched_scene = scene.matched_scene
                        st.write(matched_scene.description or "No description")
                        st.caption(f"Source id: {matched_scene.source_video_id}")
                        st.caption(
                            f"Range: {format_seconds(matched_scene.start_time)} to {format_seconds(matched_scene.end_time)}"
                        )
                        library_dir = get_library_dir()
                        video_path = resolve_video_path(scene, library_dir)
                        if video_path:
                            st.caption(f"Path: {video_path}")
                            duration = get_video_duration(str(video_path))
                            if duration is not None and (
                                matched_scene.start_time >= duration or matched_scene.end_time > duration
                            ):
                                st.error(
                                    f"Clip range is outside the video duration ({duration:.2f}s). "
                                    "Update the scene timestamps."
                                )
                        else:
                            st.caption("Video path not available for this clip yet.")
                    else:
                        st.caption("No matched clip yet.")

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
        action_cols = st.columns([1, 2])
        with action_cols[0]:
            if st.button("Match scenes (LLM)", key="match_clips"):
                if not scenes:
                    st.warning("Draft a storyboard before matching scenes.")
                else:
                    start_llm_action(prompt_match_all(), "Match storyboard to clips")
        with action_cols[1]:
            note = st.text_input("Instruction to revise storyboard", key="revise_note")
            if st.button("Revise storyboard (LLM)", key="revise_storyboard_button"):
                if not note.strip():
                    st.warning("Add a revision instruction.")
                else:
                    start_llm_action(note, "Revise storyboard")

        st.markdown("**Activity Log**")
        if st.session_state.activity:
            for entry in st.session_state.activity[-6:][::-1]:
                st.write(f"{entry['time']} - {entry['message']}")
        else:
            st.caption("No activity yet.")

with main_cols[0]:
    if st.session_state.llm_inflight:
        poll_llm_action()

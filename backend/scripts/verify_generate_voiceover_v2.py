import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from videoagent.agent.storage import BriefStore, EventStore, StoryboardStore
from videoagent.agent.tools import _build_tools
from videoagent.config import default_config
from videoagent.story import _StoryboardScene

SESSION_ID = "c9a336d4080c4934885f02dc54a3a19d"
USER_ID = "27da5c23-8967-4df4-90b2-3b1abf2fbe78"
COMPANY_ID = "10d48e59-6717-40f2-8e97-f10d7ad51ebb"


async def main() -> None:
    print("--- Starting Verification for generate_voiceover_v2 ---")
    config = default_config
    base_dir = Path.cwd() / "output" / "agent_sessions"

    storyboard_store = StoryboardStore(base_dir)
    brief_store = BriefStore(base_dir)
    event_store = EventStore(base_dir)

    scene_id = "test_vo_v2_" + uuid4().hex[:6]
    test_scene = _StoryboardScene(
        scene_id=scene_id,
        title="Test VO V2 Scene",
        purpose="Verify SSML-first voice over generation",
        script="Welcome to Navan. We help teams automate travel operations.",
        use_voice_over=True,
        order=1000,
        voice_over=None,
    )

    scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID) or []
    scenes.append(test_scene)
    storyboard_store.save(SESSION_ID, scenes, user_id=USER_ID)
    print(f"Created temporary test scene: {scene_id}")

    tools = _build_tools(
        config,
        storyboard_store,
        brief_store,
        event_store,
        SESSION_ID,
        company_id=COMPANY_ID,
        user_id=USER_ID,
    )

    vo_tool = next((t for t in tools if t.name == "generate_voiceover_v2"), None)
    if not vo_tool:
        print("Error: generate_voiceover_v2 tool not found.")
        return

    payload = {
        "segment_ids": [scene_id],
        "notes": "Read the opening phrase in a quieter, whisper-like tone.",
        "scene_notes": {
            scene_id: "Pause briefly after 'Navan'.",
        },
    }

    print(f"Invoking generate_voiceover_v2 for scene {scene_id}...")
    start_time = time.perf_counter()
    result = await vo_tool.on_invoke_tool(None, json.dumps({"payload": payload}))
    elapsed = time.perf_counter() - start_time

    print(f"Tool finished in {elapsed:.2f} seconds")
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())

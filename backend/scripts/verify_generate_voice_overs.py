import asyncio
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from uuid import uuid4

# Load environment variables from .env
load_dotenv()

from videoagent.config import default_config
from videoagent.agent.tools import _build_tools
from videoagent.agent.storage import StoryboardStore, BriefStore, EventStore
from videoagent.story import _StoryboardScene
from videoagent.db import connection

# Test constants
SESSION_ID = "c9a336d4080c4934885f02dc54a3a19d"
USER_ID = "27da5c23-8967-4df4-90b2-3b1abf2fbe78"
COMPANY_ID = "10d48e59-6717-40f2-8e97-f10d7ad51ebb"

async def main():
    print(f"--- Starting Verification for generate_voice_overs ---")
    print(f"Session: {SESSION_ID}")
    
    config = default_config
    base_dir = Path.cwd() / "output" / "agent_sessions"
    
    # Initialize stores
    storyboard_store = StoryboardStore(base_dir)
    brief_store = BriefStore(base_dir)
    event_store = EventStore(base_dir)
    
    # 1. Create a test scene needing voice over
    scene_id = "test_vo_scene_" + uuid4().hex[:6]
    test_scene = _StoryboardScene(
        scene_id=scene_id,
        title="Test VO Scene",
        purpose="Verify voice over generation",
        script="This is a test script to verify the voice over generation tool.",
        use_voice_over=True,
        order=1000,
        voice_over=None # Explicitly None to trigger generation
    )
    
    scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID) or []
    scenes.append(test_scene)
    storyboard_store.save(SESSION_ID, scenes, user_id=USER_ID)
    print(f"Created temporary test scene: {scene_id}")

    # Build tools
    tools = _build_tools(
        config,
        storyboard_store,
        brief_store,
        event_store,
        SESSION_ID,
        company_id=COMPANY_ID,
        user_id=USER_ID,
    )
    
    vo_tool = next((t for t in tools if t.name == "generate_voice_overs"), None)
    if not vo_tool:
        print("Error: generate_voice_overs tool not found.")
        return

    # 2. Invoke tool
    print(f"\nInvoking generate_voice_overs for scene {scene_id}...")
    start_time = time.perf_counter()
    
    try:
        # payload is list[str] for segment_ids, but wrapped in json as tool expects
        # The tool definition: async def generate_voice_overs(segment_ids: list[str]) -> str:
        payload = {"segment_ids": [scene_id]}
        
        result_str = await vo_tool.on_invoke_tool(None, json.dumps(payload))
        end_time = time.perf_counter()
        
        print(f"\nTool finished in {end_time - start_time:.2f} seconds.")
        print(f"Result: {result_str}")
        
        # 3. Verify Output
        updated_scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID)
        updated_scene = next((s for s in updated_scenes if s.scene_id == scene_id), None)
        
        if updated_scene and updated_scene.voice_over:
            vo = updated_scene.voice_over
            print("\nSUCCESS: Scene updated with voice_over.")
            print(f"Audio ID: {vo.audio_id}")
            print(f"Audio Path: {vo.audio_path}")
            print(f"Duration: {vo.duration}")
            
            if vo.audio_path and vo.audio_path.startswith("gs://"):
                print("Verification PASS: Audio path is a GCS URI.")
            else:
                 print(f"Verification WARNING: Unexpected audio path format: {vo.audio_path}")
                 
        else:
             print("\nFAILURE: Scene was NOT updated with voice_over.")
             
    except Exception as e:
        print(f"\nFAILED with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

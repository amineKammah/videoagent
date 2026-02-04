import asyncio
import json
import time
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from uuid import uuid4

# Load environment variables from .env
load_dotenv()

from videoagent.config import default_config
from videoagent.agent.tools import _build_tools
from videoagent.agent.storage import StoryboardStore, BriefStore, EventStore
from videoagent.story import _StoryboardScene, VoiceOver
from videoagent.db import connection, crud

# Test constants - Using same session/user/company as verify_match_scene.py for consistency
# Typically these would be new or specific test IDs, but reusing ensures they likely exist in DB.
SESSION_ID = "c9a336d4080c4934885f02dc54a3a19d"
USER_ID = "27da5c23-8967-4df4-90b2-3b1abf2fbe78"
COMPANY_ID = "10d48e59-6717-40f2-8e97-f10d7ad51ebb"

async def main():
    print(f"--- Starting Verification for generate_scene ---")
    print(f"Session: {SESSION_ID}")
    print(f"User: {USER_ID}")
    print(f"Company: {COMPANY_ID}")

    config = default_config
    base_dir = Path.cwd() / "output" / "agent_sessions"
    
    # Initialize stores
    storyboard_store = StoryboardStore(base_dir)
    brief_store = BriefStore(base_dir)
    event_store = EventStore(base_dir)

    # 1. Ensure we have a valid storyboard scene with a voice over
    # We will create a dedicated test scene for this to avoid messing up existing real data too much
    # or failing if no scene exists.
    
    scene_id = "test_gen_scene_" + uuid4().hex[:6]
    test_scene = _StoryboardScene(
        scene_id=scene_id,
        title="Test Generation Scene",
        purpose="Verify generate_scene tool",
        script="This is a test script for video generation verification.",
        use_voice_over=True,
        order=999,
        voice_over=VoiceOver(
            audio_id="test_audio_id",
            script="This is a test voice over script.",
            duration=4.5, # Suitable for 4s or 6s generation
            audio_path="gs://test-bucket/test_audio.wav" # Mock path, we just need the duration
        )
    )

    # Load existing scenes and append our test scene
    scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID) or []
    scenes.append(test_scene)
    storyboard_store.save(SESSION_ID, scenes, user_id=USER_ID)
    print(f"Created temporary test scene: {scene_id} with mock voice over (duration=4.5s)")

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
    
    gen_tool = next((t for t in tools if t.name == "generate_scene"), None)
    if not gen_tool:
        print("Error: generate_scene tool not found in built tools.")
        return

    # 2. Invoke generate_scene
    prompt = "A futuristic city skyline with flying cars at sunset, cinematic lighting, 4k"
    print(f"\nInvoking generate_scene for scene {scene_id}...")
    print(f"Prompt: {prompt}")
    
    start_time = time.perf_counter()
    
    try:
        # FunctionTool invocation expects a JSON string with arguments
        payload = {
            "prompt": prompt,
            "scene_id": scene_id,
            "duration_seconds": 4, # Matching close to our mock VO duration
            "negative_prompt": "blurry, low quality"
        }
        
        result_json_str = await gen_tool.on_invoke_tool(None, json.dumps(payload))
        end_time = time.perf_counter()
        
        print(f"\nTool finished in {end_time - start_time:.2f} seconds.")
        print(f"Result: {result_json_str}")
        
        # 3. Verify Output
        # Reload storyboard to check if scene was updated
        updated_scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID)
        updated_scene = next((s for s in updated_scenes if s.scene_id == scene_id), None)
        
        if updated_scene and updated_scene.matched_scene:
            ms = updated_scene.matched_scene
            print("\nSUCCESS: Scene updated with matched_scene.")
            print(f"Video ID: {ms.source_video_id}")
            print(f"Description: {ms.description}")
            
            # Verify it looks like a GCS video ID we generated
            if ms.source_video_id.startswith("generated:") and f":{SESSION_ID}:" in ms.source_video_id:
                 print("Verification PASS: Video ID format is correct.")
            else:
                 print(f"Verification WARNING: Unexpected Video ID format: {ms.source_video_id}")

        else:
             print("\nFAILURE: Scene was NOT updated with matched_scene.")

    except Exception as e:
        print(f"\nFAILED with exception: {e}")
        import traceback
        traceback.print_exc()

    # Cleanup (optional - maybe leave it for manual inspection?)
    # For now, we leave the test scene in the storyboard file.

if __name__ == "__main__":
    asyncio.run(main())

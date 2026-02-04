import asyncio
import json
import time
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from videoagent.config import default_config
from videoagent.agent.tools import _build_tools
from videoagent.agent.schemas import SceneMatchBatchRequest, SceneMatchRequest
from videoagent.agent.storage import StoryboardStore, BriefStore, EventStore
from videoagent.library import VideoLibrary
from videoagent.db import connection, crud

# Test constants found from DB
SESSION_ID = "c9a336d4080c4934885f02dc54a3a19d"
USER_ID = "27da5c23-8967-4df4-90b2-3b1abf2fbe78"
COMPANY_ID = "10d48e59-6717-40f2-8e97-f10d7ad51ebb"

async def main():
    print(f"--- Starting Verification for match_scene_to_video ---")
    print(f"Session: {SESSION_ID}")
    print(f"User: {USER_ID}")
    print(f"Company: {COMPANY_ID}")

    config = default_config
    base_dir = Path.cwd() / "output" / "agent_sessions"
    
    # Initialize stores
    storyboard_store = StoryboardStore(base_dir)
    brief_store = BriefStore(base_dir)
    event_store = EventStore(base_dir)
    
    # Load existing storyboard to get a valid scene_id
    scenes = storyboard_store.load(SESSION_ID, user_id=USER_ID)
    if not scenes:
        print("Error: No scenes found in storyboard for this session.")
        return
    
    target_scene = scenes[0]
    scene_id = target_scene.scene_id
    print(f"Selected Scene: {scene_id} ({target_scene.title})")

    # Initialize library to get a valid video_id
    library = VideoLibrary(config, company_id=COMPANY_ID)
    videos = library.list_videos()
    if not videos:
        print("Error: No videos found in library for this company.")
        return
    
    # Pick a video
    test_video = min(videos, key=lambda v: v.duration)
    video_id = test_video.id
    print(f"Selected Video: {video_id} ({test_video.filename}, {test_video.duration:.1f}s)")
    print(f"Video Path: {test_video.path}")

    # Check GCS validity
    from videoagent.storage import get_storage_client
    storage = get_storage_client(config)
    
    if test_video.path.startswith("gs://"):
        bucket_name = storage.bucket_name
        blob_path = test_video.path.replace(f"gs://{bucket_name}/", "")
        if storage.exists(blob_path):
            print(f"SUCCESS: GCS file exists at {test_video.path}")
        else:
            print(f"ERROR: GCS file DOES NOT EXIST at {test_video.path}")
            return
    else:
        if Path(test_video.path).exists():
            print(f"SUCCESS: Local file exists at {test_video.path}")
        else:
            print(f"ERROR: Local file DOES NOT EXIST at {test_video.path}")
            return

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
    
    # _build_tools returns a list of FunctionTool objects
    print(f"Built {len(tools)} tools: {[t.name for t in tools]}")
    match_tool = next((t for t in tools if t.name == "match_scene_to_video"), None)
    if not match_tool:
        print("Error: match_scene_to_video tool not found in built tools.")
        return
    
    # Create request
    request = SceneMatchBatchRequest(
        requests=[
            SceneMatchRequest(
                scene_id=scene_id,
                candidate_video_ids=[video_id],
                notes="Verifying tool functionality and performance."
            )
        ]
    )

    print("\nExecuting match_scene_to_video...")
    start_time = time.perf_counter()
    
    try:
        # FunctionTool objects use on_invoke_tool(ctx, payload_json_string)
        # The tool expects a JSON object with keys matching function arguments.
        # Def: match_scene_to_video(payload: SceneMatchBatchRequest)
        wrapped_payload = {"payload": request.model_dump()}
        print(f"Sending request with wrapped payload...")
        result_json = await match_tool.on_invoke_tool(None, json.dumps(wrapped_payload))
        end_time = time.perf_counter()
        
        duration = end_time - start_time
        print(f"\nTool finished in {duration:.2f} seconds.")
        print(f"Raw Result: {result_json}")
        
        # Parse and print results
        # The tool returns a string that contains JSON followed by a message
        parts = result_json.split("\nMessage:", 1)
        data = json.loads(parts[0])
        print("\nTool Output (Data):")
        print(json.dumps(data, indent=2))
        
        if "results" in data and len(data["results"]) > 0:
            res = data["results"][0]
            if "candidates" in res and len(res["candidates"]) > 0:
                print("\nSUCCESS: Found candidates.")
            else:
                print("\nWARNING: No candidates found but tool executed.")
        
        if "errors" in data:
            print("\nERRORS found in response:")
            print(json.dumps(data["errors"], indent=2))

    except Exception as e:
        print(f"\nFAILED with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
from pathlib import Path
from videoagent.voice_options import ELEVENLABS_VOICES
from videoagent.api import list_voices
from videoagent.voiceover_v3 import VoiceOverV3Generator

def verify_voices_endpoint():
    print("Verifying /voices endpoint...")
    response = list_voices()
    voices = response["voices"]
    if voices == ELEVENLABS_VOICES:
        print("SUCCESS: /voices endpoint returns ELEVENLABS_VOICES.")
    else:
        print("FAILURE: /voices endpoint returned unexpected voices.")
        print(f"Expected 1st ID: {ELEVENLABS_VOICES[0]['id']}")
        print(f"Got 1st ID: {voices[0]['id'] if voices else 'None'}")

async def verify_generation():
    print("\nVerifying voice generation with specific ID...")
    # Use Roger (first in list)
    voice_id = "CwhRBWXzGAHq8TQ4Fs17"
    out_path = Path("test_voice_roger.wav")
    
    generator = VoiceOverV3Generator()
    
    try:
        await generator.generate_voice_over_async(
            script="This is a test of the specific voice ID selection.",
            output_path=out_path,
            voice_id=voice_id
        )
        print(f"SUCCESS: Generated audio at {out_path}")
        # We rely on the print statement in the code to verify the ID used
    except Exception as e:
        print(f"FAILURE: Generation failed: {e}")

if __name__ == "__main__":
    verify_voices_endpoint()
    asyncio.run(verify_generation())

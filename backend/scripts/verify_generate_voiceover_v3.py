"""Direct smoke test for the ElevenLabs v3 voiceover generator.

This script does not use agent tools or DB interactions.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from videoagent.config import default_config
from videoagent.voiceover_v3 import VoiceOverV3Generator


async def main() -> int:
    load_dotenv()

    if not (os.getenv("ELEVENLABS_API_KEY") or "").strip():
        print("Missing ELEVENLABS_API_KEY. Add it to your environment and run again.")
        return 1

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("output/voiceover_v3_verify") / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    rendered_text = (
        "At Navan, our RevOps team partnered with HubSpot and Salesforce "
        "to reduce handoff delays by 28 percent in six weeks."
    )
    output_path = run_dir / "verify_voiceover_v3.wav"
    text_path = run_dir / "verify_voiceover_v3.text_sent_to_elevenlabs.txt"

    generator = VoiceOverV3Generator(default_config)
    try:
        start = time.perf_counter()
        voice_over = await generator.generate_voice_over_async(
            rendered_text=rendered_text,
            output_path=output_path,
            rendered_text_output_path=text_path,
        )
        elapsed = time.perf_counter() - start
    finally:
        generator.cleanup()

    print(f"Saved audio: {output_path.resolve()}")
    print(f"Saved text sent to ElevenLabs: {text_path.resolve()}")
    print(f"Duration: {voice_over.duration:.2f}s")
    print(f"Elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

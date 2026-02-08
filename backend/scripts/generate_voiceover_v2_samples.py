"""Generate local quality-check samples for voiceover_v2.

This script does not use DB state. It feeds fake scripts, notes, and pronunciation
entries directly into VoiceOverV2Generator and saves WAV files locally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from videoagent.config import default_config
from videoagent.voiceover_v2 import PronunciationGuidance, VoiceOverV2Generator


def _build_sample_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "01_easy_baseline",
            "difficulty": "easy",
            "script": (
                "Welcome to the weekly product update. In this short recap, we will cover "
                "what shipped, what improved, and what is next."
            ),
            "notes": "Neutral, professional narration.",
            "pronunciations": [],
        },
        {
            "id": "02_medium_brand_names",
            "difficulty": "medium",
            "script": (
                "At Navan, our RevOps team partnered with HubSpot and Salesforce to reduce "
                "handoff delays by 28 percent in six weeks."
            ),
            "notes": "Clear and confident. Add a short pause after each company name.",
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "nuh-VAHN"},
                {"word": "RevOps", "phonetic_spelling": "REV-ops"},
                {"word": "HubSpot", "phonetic_spelling": "HUB-spot"},
                {"word": "Salesforce", "phonetic_spelling": "SAYLZ-force"},
            ],
        },
        {
            "id": "03_hard_whisper_then_normal",
            "difficulty": "hard",
            "script": (
                "This part is confidential and should feel almost whispered. "
                "After that, switch back to normal delivery and explain the launch timeline "
                "for the full customer success team."
            ),
            "notes": (
                "First sentence should feel quiet and secretive, almost whisper-like. "
                "Second sentence should return to clear normal narration."
            ),
            "pronunciations": [
                {"word": "timeline", "phonetic_spelling": "TIME-line"},
            ],
        },
        {
            "id": "04_hard_numbers_symbols",
            "difficulty": "hard",
            "script": (
                "Q4 revenue moved from 12 point 4 million dollars to 18 point 9 million dollars. "
                "Average response time dropped from 3 point 2 seconds to 0 point 8 seconds, "
                "with p ninety five latency below 120 milliseconds."
            ),
            "notes": "Be precise and deliberate when reading numbers and technical terms.",
            "pronunciations": [
                {"word": "latency", "phonetic_spelling": "LAY-ten-see"},
                {"word": "milliseconds", "phonetic_spelling": "MIL-ee-SEK-uhndz"},
            ],
        },
        {
            "id": "05_very_hard_dense_jargon",
            "difficulty": "very_hard",
            "script": (
                "Our GTM motion now combines intent scoring, territory rebalancing, and "
                "post-sale expansion plays. The objective is simple: reduce pipeline leakage, "
                "improve forecast reliability, and protect margin while scaling support capacity."
            ),
            "notes": (
                "Strong executive tone. Keep rhythm steady even in long clauses. "
                "Do not rush acronyms."
            ),
            "pronunciations": [
                {"word": "GTM", "phonetic_spelling": "JEE-TEE-EM"},
                {"word": "pipeline", "phonetic_spelling": "PIPE-line"},
                {"word": "margin", "phonetic_spelling": "MAR-jin"},
            ],
        },
        {
            "id": "06_navan_variant_navaaan",
            "difficulty": "pronunciation_ab_test",
            "script": (
                "Navan helps finance teams standardize travel approvals. "
                "In this clip, repeat Navan clearly two times: Navan, Navan."
            ),
            "notes": (
                "Keep cadence identical to other pronunciation variant cases. "
                "Neutral tone, medium pace."
            ),
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "Navaaan"},
            ],
        },
        {
            "id": "07_navan_variant_naaavan",
            "difficulty": "pronunciation_ab_test",
            "script": (
                "Navan helps finance teams standardize travel approvals. "
                "In this clip, repeat Navan clearly two times: Navan, Navan."
            ),
            "notes": (
                "Keep cadence identical to other pronunciation variant cases. "
                "Neutral tone, medium pace."
            ),
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "Naaavan"},
            ],
        },
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local voiceover_v2 samples.")
    parser.add_argument(
        "--output-dir",
        default="output/voiceover_v2_samples",
        help="Base output directory for generated samples.",
    )
    parser.add_argument(
        "--ssml-model",
        default=None,
        help="Optional Gemini model override for SSML generation.",
    )
    parser.add_argument(
        "--elevenlabs-model-id",
        default=None,
        help="Optional ElevenLabs model id override.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Optional specific case id to run. Repeatable.",
    )
    return parser.parse_args()


def _to_pronunciations(raw_items: list[dict[str, str]]) -> list[PronunciationGuidance]:
    entries: list[PronunciationGuidance] = []
    for item in raw_items:
        word = (item.get("word") or "").strip()
        phonetic = (item.get("phonetic_spelling") or "").strip()
        if not word or not phonetic:
            continue
        entries.append(PronunciationGuidance(word=word, phonetic_spelling=phonetic))
    return entries


async def _run() -> int:
    load_dotenv()

    if not (os.getenv("ELEVENLABS_API_KEY") or "").strip():
        print("Missing ELEVENLABS_API_KEY. Add it to your environment and run again.")
        return 1

    args = _parse_args()
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    all_cases = _build_sample_cases()
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in all_cases if case["id"] in wanted]
        missing = sorted(wanted - {case["id"] for case in cases})
        if missing:
            print(f"Unknown case_id values: {', '.join(missing)}")
            return 1
    else:
        cases = all_cases

    generator = VoiceOverV2Generator(default_config)
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir.resolve()),
        "created_at": datetime.now().isoformat(),
        "ssml_model": args.ssml_model,
        "elevenlabs_model_id": args.elevenlabs_model_id,
        "results": [],
    }

    print(f"Generating {len(cases)} sample(s) into {run_dir} ...")

    try:
        for idx, case in enumerate(cases, start=1):
            case_id = case["id"]
            output_path = run_dir / f"{case_id}.wav"
            script_path = run_dir / f"{case_id}.txt"
            ssml_path = run_dir / f"{case_id}.ssml.xml"

            script_path.write_text(
                "\n".join(
                    [
                        f"id: {case_id}",
                        f"difficulty: {case['difficulty']}",
                        f"notes: {case['notes']}",
                        "",
                        case["script"],
                    ]
                ),
                encoding="utf-8",
            )

            print(f"[{idx}/{len(cases)}] {case_id} ({case['difficulty']})")
            try:
                voice_over = await generator.generate_voice_over_async(
                    script=case["script"],
                    output_path=output_path,
                    notes=case.get("notes"),
                    pronunciations=_to_pronunciations(case.get("pronunciations", [])),
                    elevenlabs_model_id=args.elevenlabs_model_id,
                    ssml_model=args.ssml_model,
                    ssml_output_path=ssml_path,
                )
                manifest["results"].append(
                    {
                        "id": case_id,
                        "difficulty": case["difficulty"],
                        "status": "ok",
                        "audio_path": str(output_path.resolve()),
                        "ssml_path": str(ssml_path.resolve()),
                        "duration_seconds": voice_over.duration,
                    }
                )
                print(f"  saved: {output_path} ({voice_over.duration:.2f}s)")
            except Exception as exc:
                manifest["results"].append(
                    {
                        "id": case_id,
                        "difficulty": case["difficulty"],
                        "status": "error",
                        "error": str(exc),
                    }
                )
                print(f"  failed: {exc}")

    finally:
        generator.cleanup()

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone. Manifest: {manifest_path}")

    failures = [r for r in manifest["results"] if r["status"] != "ok"]
    if failures:
        print(f"Completed with {len(failures)} failure(s).")
        return 2

    print("All samples generated successfully.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()

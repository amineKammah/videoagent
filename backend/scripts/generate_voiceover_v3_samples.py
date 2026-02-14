"""Integration runner for voiceover_v3 quality checks.

This script intentionally avoids DB interactions.
It exercises both runtime branches:
1) Direct path: no notes -> script is sent straight to ElevenLabs.
2) Enhanced path: notes present -> Gemini enhances text before ElevenLabs.

Outputs are written locally so you can listen and compare quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from videoagent.config import default_config
from videoagent.voiceover_v3 import PronunciationGuidance, VoiceOverV3Generator


def _build_sample_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "01_direct_baseline_no_notes",
            "difficulty": "easy",
            "mode": "direct",
            "script": (
                "Welcome to the weekly product update. In this short recap, we cover what shipped, "
                "what improved, and what is next."
            ),
            "notes": None,
            "pronunciations": [],
        },
        {
            "id": "02_enhanced_brand_names_with_pauses",
            "difficulty": "medium",
            "mode": "enhanced",
            "script": (
                "At Navan, our RevOps team partnered with HubSpot and Salesforce to reduce "
                "handoff delays by 28 percent in six weeks."
            ),
            "notes": "Clear and confident. Add short pauses after company names.",
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "nuh-VAHN"},
                {"word": "RevOps", "phonetic_spelling": "REV-ops"},
                {"word": "HubSpot", "phonetic_spelling": "HUB-spot"},
                {"word": "Salesforce", "phonetic_spelling": "SAYLZ-force"},
            ],
        },
        {
            "id": "03_enhanced_whisper_then_normal",
            "difficulty": "hard",
            "mode": "enhanced",
            "script": (
                "This section should feel private and discreet. "
                "Then return to a normal delivery and explain the launch timeline for the customer success team."
            ),
            "notes": (
                "First sentence should feel whisper-like and secretive. "
                "Second sentence should return to normal neutral narration."
            ),
            "pronunciations": [
                {"word": "timeline", "phonetic_spelling": "TIME-line"},
            ],
        },
        {
            "id": "04_direct_navan_variant_navaaan",
            "difficulty": "pronunciation_ab_test",
            "mode": "direct",
            "script": (
                "Navan helps finance teams standardize travel approvals. "
                "Repeat Navan clearly two times: Navan, Navan."
            ),
            "notes": None,
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "Navaaan"},
            ],
        },
        {
            "id": "05_direct_navan_variant_naaavan",
            "difficulty": "pronunciation_ab_test",
            "mode": "direct",
            "script": (
                "Navan helps finance teams standardize travel approvals. "
                "Repeat Navan clearly two times: Navan, Navan."
            ),
            "notes": None,
            "pronunciations": [
                {"word": "Navan", "phonetic_spelling": "Naaavan"},
            ],
        },
        {
            "id": "06_enhanced_numbers_and_jargon",
            "difficulty": "very_hard",
            "mode": "enhanced",
            "script": (
                "Q4 revenue moved from 12 point 4 million dollars to 18 point 9 million dollars. "
                "Average response time dropped from 3 point 2 seconds to 0 point 8 seconds, "
                "with p ninety five latency below 120 milliseconds."
            ),
            "notes": "Use deliberate pacing for all numbers and technical terms.",
            "pronunciations": [
                {"word": "latency", "phonetic_spelling": "LAY-ten-see"},
                {"word": "milliseconds", "phonetic_spelling": "MIL-ee-SEK-uhndz"},
            ],
        },
        {
            "id": "07_direct_whiper_typo_normalization",
            "difficulty": "tag_normalization",
            "mode": "direct",
            "script": (
                "[whiper] This sentence should sound whispered. "
                "[small pause] Then continue in a normal tone."
            ),
            "notes": None,
            "pronunciations": [],
        },
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local voiceover_v3 integration samples.")
    parser.add_argument(
        "--output-dir",
        default="output/voiceover_v3_samples",
        help="Base output directory for generated samples.",
    )
    parser.add_argument(
        "--enhancer-model",
        default=None,
        help="Optional Gemini enhancer model override (used only when notes are present).",
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
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=0.0,
        help="Optional seconds to sleep between cases (helps avoid provider throttling).",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "direct", "enhanced"],
        default="all",
        help="Filter cases by branch under test.",
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


def _select_cases(all_cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cases = all_cases

    if args.mode != "all":
        cases = [case for case in cases if case.get("mode") == args.mode]

    if args.case_id:
        wanted = set(args.case_id)
        filtered = [case for case in cases if case["id"] in wanted]
        missing = sorted(wanted - {case["id"] for case in filtered})
        if missing:
            raise ValueError(f"Unknown case_id values for current filter: {', '.join(missing)}")
        cases = filtered

    return cases


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
    try:
        cases = _select_cases(all_cases, args)
    except ValueError as exc:
        print(str(exc))
        return 1

    if not cases:
        print("No cases selected after filters.")
        return 1

    generator = VoiceOverV3Generator(default_config)
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir.resolve()),
        "created_at": datetime.now().isoformat(),
        "enhancer_model": args.enhancer_model,
        "elevenlabs_model_id": args.elevenlabs_model_id,
        "mode_filter": args.mode,
        "sleep_between": args.sleep_between,
        "results": [],
    }

    print(f"Generating {len(cases)} sample(s) into {run_dir} ...")

    try:
        for idx, case in enumerate(cases, start=1):
            case_id = case["id"]
            output_path = run_dir / f"{case_id}.wav"
            script_path = run_dir / f"{case_id}.txt"
            text_sent_path = run_dir / f"{case_id}.text_sent_to_elevenlabs.txt"

            notes_value = case.get("notes")
            notes_text = notes_value if isinstance(notes_value, str) else ""
            enhancer_used = bool(notes_text.strip())

            script_path.write_text(
                "\n".join(
                    [
                        f"id: {case_id}",
                        f"difficulty: {case['difficulty']}",
                        f"mode: {case.get('mode', 'unknown')}",
                        f"enhancer_used: {enhancer_used}",
                        f"notes: {notes_text or '(none)'}",
                        "",
                        case["script"],
                    ]
                ),
                encoding="utf-8",
            )

            print(f"[{idx}/{len(cases)}] {case_id} ({case['difficulty']} | enhancer={enhancer_used})")
            started = time.perf_counter()
            try:
                voice_over = await generator.generate_voice_over_async(
                    script=case["script"],
                    output_path=output_path,
                    notes=notes_value,
                    pronunciations=_to_pronunciations(case.get("pronunciations", [])),
                    elevenlabs_model_id=args.elevenlabs_model_id,
                    enhancer_model=args.enhancer_model,
                    enhanced_text_output_path=text_sent_path,
                )
                elapsed = time.perf_counter() - started
                manifest["results"].append(
                    {
                        "id": case_id,
                        "difficulty": case["difficulty"],
                        "mode": case.get("mode"),
                        "enhancer_used": enhancer_used,
                        "status": "ok",
                        "audio_path": str(output_path.resolve()),
                        "text_sent_to_elevenlabs_path": str(text_sent_path.resolve()),
                        "duration_seconds": voice_over.duration,
                        "elapsed_seconds": elapsed,
                    }
                )
                print(f"  saved: {output_path} ({voice_over.duration:.2f}s, {elapsed:.2f}s)")
            except Exception as exc:
                elapsed = time.perf_counter() - started
                manifest["results"].append(
                    {
                        "id": case_id,
                        "difficulty": case["difficulty"],
                        "mode": case.get("mode"),
                        "enhancer_used": enhancer_used,
                        "status": "error",
                        "elapsed_seconds": elapsed,
                        "error": str(exc),
                    }
                )
                print(f"  failed ({elapsed:.2f}s): {exc}")

            if args.sleep_between > 0 and idx < len(cases):
                await asyncio.sleep(args.sleep_between)

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

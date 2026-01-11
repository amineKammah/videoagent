#!/usr/bin/env python3
"""
Basic integration-style tests for the Video Agent repo.

Run:
  python3 scripts/run_basic_tests.py
  python3 scripts/run_basic_tests.py --run-llm
  python3 scripts/run_basic_tests.py --run-e2e
"""
from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

try:
    from videoagent.agent import VideoAgent
    from videoagent.config import Config
    from videoagent.editor import VideoEditor
    from videoagent.library import VideoLibrary
    from videoagent.models import SegmentType, StaticScene, StoryPlan, StorySegment, VideoSegment
    from videoagent.story import PersonalizedStoryGenerator
except ImportError as exc:
    raise SystemExit(
        "videoagent is not installed. Run: python3 -m pip install -e backend"
    ) from exc

LIBRARY_PATH: Path | None = None
OUTPUT_DIR: Path = REPO_ROOT / "output/test_runs"
RUN_LLM = False
RUN_E2E = False


def resolve_library_path(explicit: Path | None) -> Path:
    if explicit:
        return explicit

    candidates = [
        REPO_ROOT / "assets/test_videos",
        REPO_ROOT / "assets/case_studies",
        REPO_ROOT / "assets/Navan_Content/Assets/case_studies",
        REPO_ROOT / "assets/Navan_Content/case_studies",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No video library found. Pass --library or place videos under assets/."
    )


def write_tone_wav(output_path: Path, duration_s: float = 2.5, freq_hz: float = 440.0) -> Path:
    sample_rate = 44100
    total_samples = int(sample_rate * duration_s)
    amplitude = 0.4

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(total_samples):
            sample = amplitude * math.sin(2 * math.pi * freq_hz * (i / sample_rate))
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return output_path


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


class BasicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global LIBRARY_PATH, OUTPUT_DIR
        cls.library_path = resolve_library_path(LIBRARY_PATH)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.config = Config(video_library_path=cls.library_path, output_dir=OUTPUT_DIR)
        cls.editor = VideoEditor(cls.config)

        cls.library = VideoLibrary(cls.config)
        cls.library.scan_library(force_reindex=True)
        cls.videos = cls.library.list_videos()

        if not cls.videos:
            raise RuntimeError("No videos found in the library.")

        cls.source_video = min(cls.videos, key=lambda v: v.duration)

    def test_library_scan_and_metadata(self) -> None:
        self.assertGreater(len(self.videos), 0)
        sample = self.videos[0]
        self.assertGreater(sample.duration, 0)
        self.assertGreater(sample.resolution[0], 0)
        self.assertGreater(sample.resolution[1], 0)
        self.assertGreater(sample.fps, 0)
        self.assertGreater(sample.file_size, 0)

    def test_search_by_duration(self) -> None:
        short = self.library.search_by_duration(max_duration=120)
        long = self.library.search_by_duration(min_duration=180)
        self.assertIsInstance(short, list)
        self.assertIsInstance(long, list)

    def test_cut_video_segment(self) -> None:
        cut_path = OUTPUT_DIR / "cut_test.mp4"
        segment = VideoSegment(
            source_video_id=self.source_video.id,
            source_path=self.source_video.path,
            start_time=0.0,
            end_time=min(2.5, self.source_video.duration),
            description="Test cut",
        )
        result = self.editor.cut_video_segment(segment, output_path=cut_path)
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 0)
        self.assertGreater(ffprobe_duration(result), 0)

    def test_normalize_video(self) -> None:
        input_path = OUTPUT_DIR / "cut_test.mp4"
        normalized_path = OUTPUT_DIR / "normalized_test.mp4"
        result = self.editor.normalize_video(input_path, output_path=normalized_path)
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 0)

    def test_static_scene(self) -> None:
        scene_path = OUTPUT_DIR / "static_scene_test.mp4"
        scene = StaticScene(
            text="Basic Test",
            duration=3.0,
            background_color="#1a1a2e",
            text_color="#eaeaea",
            subtitle="Static scene",
        )
        result = self.editor.create_static_scene(scene, output_path=scene_path)
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 0)

    def test_concatenate(self) -> None:
        cut_path = OUTPUT_DIR / "cut_test.mp4"
        scene_path = OUTPUT_DIR / "static_scene_test.mp4"
        concat_path = OUTPUT_DIR / "concat_test.mp4"
        result = self.editor.concatenate_videos([cut_path, scene_path], output_path=concat_path)
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 0)

    def test_audio_overlay_replace(self) -> None:
        cut_path = OUTPUT_DIR / "cut_test.mp4"
        tone_path = OUTPUT_DIR / "tone.wav"
        overlay_path = OUTPUT_DIR / "overlay_test.mp4"
        write_tone_wav(tone_path)
        result = self.editor.overlay_audio(
            cut_path,
            tone_path,
            output_path=overlay_path,
            replace_original=True,
        )
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 0)

    def test_manual_story_render(self) -> None:
        intro = StorySegment(
            segment_type=SegmentType.VIDEO_CLIP,
            content=VideoSegment(
                source_video_id=self.source_video.id,
                source_path=self.source_video.path,
                start_time=0.0,
                end_time=min(2.5, self.source_video.duration),
            ),
            order=0,
        )
        mid = StorySegment(
            segment_type=SegmentType.STATIC_SCENE,
            content=StaticScene(
                text="Manual Plan",
                duration=3.0,
                background_color="#1a1a2e",
                text_color="#eaeaea",
                subtitle="No LLM",
            ),
            order=1,
        )
        outro = StorySegment(
            segment_type=SegmentType.VIDEO_CLIP,
            content=VideoSegment(
                source_video_id=self.source_video.id,
                source_path=self.source_video.path,
                start_time=min(2.5, self.source_video.duration - 1),
                end_time=min(5.0, self.source_video.duration),
            ),
            order=2,
        )
        plan = StoryPlan(
            title="Manual Test Plan",
            description="Manual story assembly without LLM",
            intro=intro,
            segments=[mid, outro],
            output_filename="manual_story_test.mp4",
        )
        result = self.editor.render_story(plan)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.output_path)
        self.assertTrue(result.output_path.exists())
        self.assertGreater(result.output_path.stat().st_size, 0)

    @unittest.skipUnless(RUN_LLM, "Set --run-llm to enable LLM tests")
    def test_llm_story_generation(self) -> None:
        generator = PersonalizedStoryGenerator(self.config)
        plan = generator.generate_story(
            "We struggle with travel expense compliance and slow reimbursements.",
            output_filename="llm_story_test.mp4",
        )
        self.assertGreater(len(plan.get_all_segments()), 0)
        self.assertTrue(plan.title)

    @unittest.skipUnless(RUN_E2E, "Set --run-e2e to enable end-to-end tests")
    def test_end_to_end_render(self) -> None:
        agent = VideoAgent(self.config)
        try:
            result = agent.create_personalized_video(
                "We struggle with travel expense compliance and slow reimbursements.",
                output_filename="llm_personalized_video_test.mp4",
            )
        finally:
            agent.cleanup()
        self.assertTrue(result.success)
        self.assertIsNotNone(result.output_path)
        self.assertTrue(result.output_path.exists())
        self.assertGreater(result.output_path.stat().st_size, 0)


def main() -> int:
    global LIBRARY_PATH, OUTPUT_DIR, RUN_LLM, RUN_E2E

    parser = argparse.ArgumentParser(description="Run basic integration tests.")
    parser.add_argument("--library", type=Path, help="Path to video library")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--run-llm", action="store_true", help="Run LLM story generation")
    parser.add_argument("--run-e2e", action="store_true", help="Run full end-to-end render")
    args = parser.parse_args()
    LIBRARY_PATH = args.library
    OUTPUT_DIR = args.output_dir
    RUN_LLM = args.run_llm
    RUN_E2E = args.run_e2e

    unittest.main(argv=[sys.argv[0]], verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

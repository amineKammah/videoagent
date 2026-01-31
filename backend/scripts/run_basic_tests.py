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
import asyncio
import math
import struct
import subprocess
import sys
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

# from videoagent.agent import VideoAgent
from videoagent.config import Config
from videoagent.editor import VideoEditor
from videoagent.library import VideoLibrary
from videoagent.models import SegmentType, StorySegment, VideoSegment, VoiceOver
from videoagent.story import (
    PersonalizedStoryGenerator,
    _ClipPlan,
    _SceneClip,
    _StoryboardPlan,
    _StoryboardScene,
)

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

    def test_concatenate(self) -> None:
        cut_path = OUTPUT_DIR / "cut_test.mp4"
        second_path = OUTPUT_DIR / "cut_test_2.mp4"
        if not cut_path.exists():
            self.editor.cut_video_segment(
                VideoSegment(
                    source_video_id=self.source_video.id,
                    source_path=self.source_video.path,
                    start_time=0.0,
                    end_time=min(2.5, self.source_video.duration),
                ),
                output_path=cut_path,
            )
        if not second_path.exists():
            self.editor.cut_video_segment(
                VideoSegment(
                    source_video_id=self.source_video.id,
                    source_path=self.source_video.path,
                    start_time=min(2.5, self.source_video.duration - 1),
                    end_time=min(5.0, self.source_video.duration),
                ),
                output_path=second_path,
            )
        concat_path = OUTPUT_DIR / "concat_test.mp4"
        result = self.editor.concatenate_videos([cut_path, second_path], output_path=concat_path)
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
            segment_type=SegmentType.VIDEO_CLIP,
            content=VideoSegment(
                source_video_id=self.source_video.id,
                source_path=self.source_video.path,
                start_time=min(2.5, self.source_video.duration - 1),
                end_time=min(5.0, self.source_video.duration),
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
        segments = [intro, mid, outro]
        result = self.editor.render_segments(segments, "manual_story_test.mp4")
        self.assertTrue(result.success)
        self.assertIsNotNone(result.output_path)
        self.assertTrue(result.output_path.exists())
        self.assertGreater(result.output_path.stat().st_size, 0)

    def test_llm_story_generation(self) -> None:
        if not RUN_LLM:
            self.skipTest("Set --run-llm to enable LLM tests")
        generator = PersonalizedStoryGenerator(self.config)
        segments = asyncio.run(
            generator.generate_story(
                "We struggle with travel expense compliance and slow reimbursements.",
            )
        )
        self.assertGreater(len(segments), 0)

    def test_select_clips_uses_uploaded_videos(self) -> None:
        generator = PersonalizedStoryGenerator(self.config)
        storyboard = _StoryboardPlan(
            scenes=[
                _StoryboardScene(
                    scene_id="scene_1",
                    title="Intro",
                    purpose="Hook",
                    script="Welcome to our story.",
                )
            ],
            top_video_ids=[self.source_video.id],
        )
        voice_over = VoiceOver(
            script="Welcome to our story.",
            duration=2.0,
            voice=self.config.tts_voice,
        )
        uploaded_files = ["uploaded_video_handle"]
        video_catalog = (
            f"- {self.source_video.id}: "
            f"{self.source_video.filename} ({self.source_video.duration:.1f}s)"
        )
        captured: dict[str, object] = {}

        def fake_generate_content(model, contents, config=None):
            captured["contents"] = contents

            class Response:
                text = (
                    "{"
                    "\"clips\":[{"
                    "\"scene_id\":\"scene_1\","
                    f"\"video_id\":\"{self.source_video.id}\","
                    "\"start\":1.0,"
                    "\"end\":2.0,"
                    "\"description\":\"Intro\","
                    "\"rationale\":\"Fits the opening.\""
                    "}]"
                    "}"
                )

            return Response()

        generator.client.generate_content = fake_generate_content

        plan = generator._select_clips(
            "Test situation",
            storyboard,
            {"scene_1": voice_over},
            video_catalog,
            uploaded_files,
        )

        self.assertEqual(plan.clips[0].video_id, self.source_video.id)
        self.assertEqual(captured["contents"][:-1], uploaded_files)
        prompt = captured["contents"][-1]
        self.assertIn("The video files are provided before this prompt", prompt)

    def test_select_clips_multiple_videos(self) -> None:
        if len(self.videos) < 2:
            self.skipTest("Need at least two videos to validate multi-video selection")

        generator = PersonalizedStoryGenerator(self.config)
        video_a = self.videos[0]
        video_b = self.videos[1]

        storyboard = _StoryboardPlan(
            scenes=[
                _StoryboardScene(
                    scene_id="scene_1",
                    title="Intro",
                    purpose="Hook",
                    script="Welcome to our story.",
                ),
                _StoryboardScene(
                    scene_id="scene_2",
                    title="Problem",
                    purpose="Highlight the pain.",
                    script="Here is the challenge we solve.",
                ),
            ],
            top_video_ids=[video_a.id, video_b.id],
        )

        voice_overs = {
            "scene_1": VoiceOver(script="Welcome to our story.", duration=2.0),
            "scene_2": VoiceOver(script="Here is the challenge we solve.", duration=2.5),
        }

        uploaded_files = ["video_a_handle", "video_b_handle"]
        video_catalog = "\n".join(
            [
                f"- {video_a.id}: {video_a.filename} ({video_a.duration:.1f}s)",
                f"- {video_b.id}: {video_b.filename} ({video_b.duration:.1f}s)",
            ]
        )
        captured: dict[str, object] = {}

        def fake_generate_content(model, contents, config=None):
            captured["contents"] = contents

            class Response:
                text = (
                    "{"
                    "\"clips\":["
                    "{"
                    "\"scene_id\":\"scene_1\","
                    f"\"video_id\":\"{video_a.id}\","
                    "\"start\":1.0,"
                    "\"end\":2.5,"
                    "\"description\":\"Intro\","
                    "\"rationale\":\"Fits the opening.\""
                    "},"
                    "{"
                    "\"scene_id\":\"scene_2\","
                    f"\"video_id\":\"{video_b.id}\","
                    "\"start\":3.0,"
                    "\"end\":5.0,"
                    "\"description\":\"Problem\","
                    "\"rationale\":\"Matches the pain point.\""
                    "}"
                    "]"
                    "}"
                )

            return Response()

        generator.client.generate_content = fake_generate_content

        plan = generator._select_clips(
            "Test situation",
            storyboard,
            voice_overs,
            video_catalog,
            uploaded_files,
        )

        self.assertEqual(len(plan.clips), 2)
        self.assertEqual({clip.video_id for clip in plan.clips}, {video_a.id, video_b.id})
        self.assertEqual(captured["contents"][:-1], uploaded_files)
        prompt = captured["contents"][-1]
        self.assertIn(video_a.id, prompt)
        self.assertIn(video_b.id, prompt)

    def test_validate_clip_ids_rejects_unknown(self) -> None:
        generator = PersonalizedStoryGenerator(self.config)
        allowed_ids = {self.source_video.id}
        clip_plan = _ClipPlan(
            clips=[
                _SceneClip(
                    scene_id="scene_1",
                    video_id="deadbeefdead",
                    start=1.0,
                    end=2.0,
                    description="Invalid clip",
                    rationale="Bad id",
                )
            ]
        )
        with self.assertRaises(ValueError):
            generator._validate_clip_plan(clip_plan, allowed_ids)

    def test_validate_clip_ids_accepts_allowed(self) -> None:
        generator = PersonalizedStoryGenerator(self.config)
        allowed_ids = {self.source_video.id}
        clip_plan = _ClipPlan(
            clips=[
                _SceneClip(
                    scene_id="scene_1",
                    video_id=self.source_video.id,
                    start=1.0,
                    end=2.0,
                    description="Valid clip",
                    rationale="Good id",
                )
            ]
        )
        generator._validate_clip_plan(clip_plan, allowed_ids)

    @unittest.skipUnless(RUN_E2E, "Set --run-e2e to enable end-to-end tests")
    def test_end_to_end_render(self) -> None:
        self.skipTest("VideoAgent class has been removed.")
        # agent = VideoAgent(self.config)
        # try:
        #     result = agent.create_personalized_video(
        #         "We struggle with travel expense compliance and slow reimbursements.",
        #         output_filename="llm_personalized_video_test.mp4",
        #     )
        # finally:
        #     agent.cleanup()
        # self.assertTrue(result.success)
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
    parser.add_argument("--test", type=str, help="Run a specific test by name")
    args = parser.parse_args()
    LIBRARY_PATH = args.library
    OUTPUT_DIR = args.output_dir
    RUN_LLM = args.run_llm
    RUN_E2E = args.run_e2e
    if args.test:
        test_name = args.test
        if "." not in test_name:
            test_name = f"{BasicIntegrationTests.__name__}.{test_name}"
        unittest.main(argv=[sys.argv[0], test_name], verbosity=2)
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Video Agent - Main orchestration for personalized video generation.

Simple pipeline that takes a customer situation and produces a personalized video.
"""
from pathlib import Path
from typing import Optional

from videoagent.config import Config, default_config
from videoagent.editor import VideoEditor
from videoagent.library import VideoLibrary
from videoagent.models import RenderResult, StoryPlan
from videoagent.story import PersonalizedStoryGenerator
from videoagent.voice import VoiceOverGenerator


class VideoAgent:
    """
    Main agent that orchestrates personalized video generation.

    Takes a customer situation and produces a complete video following:
    1. Intro with voice over
    2. Static scene explaining customer pain with voice over
    3. Solution content from videos
    4. Customer testimonial
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config

        self.library = VideoLibrary(config)
        self.editor = VideoEditor(config)
        self.voice_generator = VoiceOverGenerator(config)
        self.story_generator = PersonalizedStoryGenerator(config)

    def create_personalized_video(
        self,
        customer_situation: str,
        output_filename: str = "personalized_video.mp4"
    ) -> RenderResult:
        """
        Create a personalized video from a customer situation.

        Args:
            customer_situation: Description of the customer's pain/situation
            output_filename: Name for the output file

        Returns:
            RenderResult with the output path and metadata
        """
        print(f"\n{'='*60}")
        print("PERSONALIZED VIDEO GENERATION")
        print(f"{'='*60}\n")
        print(f"Customer situation: {customer_situation[:100]}...")
        print()

        # 1. Index the library
        print("Indexing video library...")
        self.library.scan_library()
        video_count = len(self.library.list_videos())
        print(f"  Found {video_count} videos\n")

        if video_count == 0:
            return RenderResult(
                success=False,
                error_message="No videos found in library. Add videos to proceed."
            )

        # 2. Generate the story plan (uses LLM in a loop)
        print("Generating story plan with LLM...")
        plan = self.story_generator.generate_story(customer_situation, output_filename)

        print(f"\nStory: {plan.title}")
        print(f"  Total segments: {len(plan.get_all_segments())}")
        print(f"  Estimated duration: {plan.total_duration:.1f}s\n")

        # 3. Generate voice overs for segments that have scripts
        print("Generating voice overs...")
        self._generate_voice_overs(plan)
        print("  Voice overs generated\n")

        # 4. Render the final video
        print("Rendering final video...")
        result = self.editor.render_story(plan)

        if result.success:
            print(f"\n{'='*60}")
            print("VIDEO COMPLETE")
            print(f"{'='*60}")
            print(f"Output: {result.output_path}")
            print(f"Duration: {result.duration:.1f}s")
            if result.file_size:
                print(f"Size: {result.file_size / 1024 / 1024:.1f} MB")
        else:
            print(f"\nRendering failed: {result.error_message}")

        return result

    def _generate_voice_overs(self, plan: StoryPlan) -> None:
        """Generate voice over audio for all segments with scripts."""
        for segment in plan.get_all_segments():
            if segment.voice_over and segment.voice_over.script:
                if not segment.voice_over.audio_path:
                    vo = self.voice_generator.generate_voice_over(
                        segment.voice_over.script,
                        segment.voice_over.voice,
                        segment.voice_over.speed
                    )
                    segment.voice_over.audio_path = vo.audio_path
                    segment.voice_over.duration = vo.duration

    def cleanup(self) -> None:
        """Clean up temporary files."""
        self.editor.cleanup()
        self.voice_generator.cleanup()


def create_personalized_video(
    customer_situation: str,
    library_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    output_filename: str = "personalized_video.mp4"
) -> RenderResult:
    """
    Convenience function to create a personalized video.

    Args:
        customer_situation: Description of the customer's pain/situation
        library_path: Path to the video library
        output_path: Path for output directory
        output_filename: Name for the output file

    Returns:
        RenderResult with output path and metadata
    """
    config = Config()

    if library_path:
        config.video_library_path = Path(library_path)
    if output_path:
        config.output_dir = Path(output_path)

    agent = VideoAgent(config)

    try:
        return agent.create_personalized_video(customer_situation, output_filename)
    finally:
        agent.cleanup()

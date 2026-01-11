"""
Story Generator - Personalized video creation from customer situation.

Creates a compelling story following this structure:
1. Intro with voice over
2. Static scene explaining customer pain with voice over
3. Solution content (video snippet, static image, etc.)
4. Customer testimonial corroborating the solution
"""
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from videoagent.config import Config, default_config
from videoagent.models import (
    VideoMetadata,
    VideoSegment,
    StaticScene,
    StorySegment,
    StoryPlan,
    VoiceOver,
    SegmentType,
)
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary


# ==================== Pydantic Response Models ====================

class StoryOutline(BaseModel):
    """LLM response for the initial story outline."""
    customer_pain_summary: str = Field(description="Summary of the customer's pain point")
    pain_explanation_script: str = Field(description="Voice over script explaining how the customer pain is real (2-3 sentences)")
    solution_summary: str = Field(description="What solution addresses this pain")
    solution_video_query: str = Field(description="Search query to find the solution video/content")
    testimonial_video_query: str = Field(description="Search query to find a customer testimonial video")
    intro_context: str = Field(description="Context for what kind of intro would work well")


class IntroSelection(BaseModel):
    """LLM response for intro selection."""
    video_id: str = Field(description="ID of the selected intro video")
    reasoning: str = Field(description="Why this intro was selected")
    voice_over_script: str = Field(description="Voice over script for the intro (1-2 sentences)")


class VideoSelection(BaseModel):
    """LLM response for video selection."""
    video_id: str = Field(description="ID of the selected video")
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")
    reasoning: str = Field(description="Why this segment was selected")


# ==================== Story Generator ====================

class PersonalizedStoryGenerator:
    """
    Generates a personalized video story from a customer situation.

    The workflow:
    1. Analyze customer situation against all transcripts
    2. Find a suitable intro + voice over
    3. Create pain explanation scene + voice over
    4. Find solution content from videos
    5. Find customer testimonial
    6. Merge everything together
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self.client = GeminiClient(config)
        self.library = VideoLibrary(config)

    def _get_all_transcripts(self) -> str:
        """Get all video transcripts as context for the LLM."""
        videos = self.library.list_videos()

        if not videos:
            return "No videos available in the library."

        transcript_lines = []
        for video in videos:
            transcript = video.get_full_transcript()
            if transcript:
                transcript_lines.append(
                    f"[Video ID: {video.id}]\n"
                    f"File: {video.filename}\n"
                    f"Duration: {video.duration:.1f}s\n"
                    f"Transcript: {transcript}\n"
                )

        return "\n---\n".join(transcript_lines)

    def _get_videos_summary(self) -> str:
        """Get a brief summary of all videos."""
        videos = self.library.list_videos()

        lines = []
        for video in videos:
            transcript = video.get_full_transcript()
            preview = transcript[:150] + "..." if len(transcript) > 150 else transcript
            lines.append(f"- {video.id}: {video.filename} ({video.duration:.1f}s) - {preview}")

        return "\n".join(lines)

    def generate_story(
        self,
        customer_situation: str,
        output_filename: str = "personalized_video.mp4"
    ) -> StoryPlan:
        """
        Generate a complete personalized video from a customer situation.

        Args:
            customer_situation: Description of the customer's situation/pain
            output_filename: Name for the output file

        Returns:
            StoryPlan ready for rendering
        """
        # Ensure library is indexed
        self.library.scan_library()

        all_transcripts = self._get_all_transcripts()
        videos_summary = self._get_videos_summary()

        print("Step 1: Analyzing customer situation and planning story...")
        outline = self._plan_story(customer_situation, all_transcripts)

        print("Step 2: Finding intro video...")
        intro_segment = self._find_intro(outline.intro_context, videos_summary)

        print("Step 3: Creating pain explanation scene...")
        pain_scene = self._create_pain_scene(outline.pain_explanation_script)

        print("Step 4: Finding solution content...")
        solution_segment = self._find_solution_video(
            outline.solution_video_query,
            outline.solution_summary,
            videos_summary
        )

        print("Step 5: Finding customer testimonial...")
        testimonial_segment = self._find_testimonial_video(
            outline.testimonial_video_query,
            videos_summary
        )

        print("Step 6: Assembling final story plan...")
        return self._assemble_story(
            title=f"Personalized Solution: {outline.customer_pain_summary[:50]}",
            description=outline.solution_summary,
            intro_segment=intro_segment,
            pain_scene=pain_scene,
            solution_segment=solution_segment,
            testimonial_segment=testimonial_segment,
            output_filename=output_filename
        )

    def _plan_story(self, customer_situation: str, transcripts: str) -> StoryOutline:
        """Use LLM to analyze the situation and plan the story."""
        prompt = f"""You are creating a personalized sales video for a customer.

CUSTOMER SITUATION:
{customer_situation}

AVAILABLE VIDEO TRANSCRIPTS:
{transcripts}

Based on the customer's situation, create a compelling story outline that:
1. Identifies their core pain point
2. Explains why this pain is real and relatable
3. Finds a solution from the available videos
4. Identifies a customer testimonial that supports this solution

Be specific about which videos to use based on the transcripts."""

        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": StoryOutline.model_json_schema(),
            }
        )

        return StoryOutline.model_validate_json(response.text)

    def _find_intro(self, intro_context: str, videos_summary: str) -> StorySegment:
        """Find and select the best intro video."""
        prompt = f"""Select the best video to use as an intro (first 5 seconds).

CONTEXT FOR INTRO:
{intro_context}

AVAILABLE VIDEOS:
{videos_summary}

Select a video that would make a compelling, attention-grabbing intro.
Write a short voice over script (1-2 sentences) to go over this intro."""

        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": IntroSelection.model_json_schema(),
            }
        )

        selection = IntroSelection.model_validate_json(response.text)
        video = self.library.get_video(selection.video_id)

        if not video:
            # Fallback to first video
            videos = self.library.list_videos()
            video = videos[0] if videos else None
            if not video:
                raise ValueError("No videos available for intro")

        intro_duration = min(self.config.intro_duration_seconds, video.duration)

        video_segment = VideoSegment(
            source_video_id=video.id,
            source_path=video.path,
            start_time=0,
            end_time=intro_duration,
            description="Intro"
        )

        voice_over = VoiceOver(
            script=selection.voice_over_script,
            voice=self.config.tts_voice
        )

        return StorySegment(
            segment_type=SegmentType.VIDEO_CLIP,
            content=video_segment,
            voice_over=voice_over,
            order=0
        )

    def _create_pain_scene(self, pain_script: str) -> StorySegment:
        """Create a static scene explaining the customer pain."""
        # Extract a short title from the script
        title = pain_script.split('.')[0][:50] if '.' in pain_script else pain_script[:50]

        static_scene = StaticScene(
            text=title,
            duration=5.0,  # Will be extended if VO is longer
            background_color="#1a1a2e",
            text_color="#eaeaea",
            subtitle="Understanding your challenge"
        )

        voice_over = VoiceOver(
            script=pain_script,
            voice=self.config.tts_voice
        )

        return StorySegment(
            segment_type=SegmentType.STATIC_SCENE,
            content=static_scene,
            voice_over=voice_over,
            order=1
        )

    def _find_solution_video(
        self,
        search_query: str,
        solution_summary: str,
        videos_summary: str
    ) -> StorySegment:
        """Find video content showing the solution."""
        prompt = f"""Find the best video segment that demonstrates or explains this solution.

SOLUTION TO SHOW:
{solution_summary}

SEARCH QUERY:
{search_query}

AVAILABLE VIDEOS:
{videos_summary}

Select a specific segment (with start and end times) that best shows this solution.
This could be a demo, an explanation, a slide, or any relevant content."""

        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": VideoSelection.model_json_schema(),
            }
        )

        selection = VideoSelection.model_validate_json(response.text)
        video = self.library.get_video(selection.video_id)

        if not video:
            videos = self.library.list_videos()
            video = videos[0] if videos else None
            if not video:
                raise ValueError("No videos available for solution")
            selection.start_time = 0
            selection.end_time = min(30, video.duration)

        # Clamp times to video duration
        start = max(0, min(selection.start_time, video.duration - 1))
        end = max(start + 1, min(selection.end_time, video.duration))

        video_segment = VideoSegment(
            source_video_id=video.id,
            source_path=video.path,
            start_time=start,
            end_time=end,
            description=f"Solution: {solution_summary[:50]}"
        )

        return StorySegment(
            segment_type=SegmentType.VIDEO_CLIP,
            content=video_segment,
            order=2
        )

    def _find_testimonial_video(
        self,
        search_query: str,
        videos_summary: str
    ) -> StorySegment:
        """Find a customer testimonial video."""
        prompt = f"""Find the best video segment with a customer testimonial or endorsement.

SEARCH QUERY:
{search_query}

AVAILABLE VIDEOS:
{videos_summary}

Select a segment where a customer is speaking positively about the solution,
sharing their experience, or corroborating the benefits."""

        response = self.client.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": VideoSelection.model_json_schema(),
            }
        )

        selection = VideoSelection.model_validate_json(response.text)
        video = self.library.get_video(selection.video_id)

        if not video:
            videos = self.library.list_videos()
            video = videos[0] if videos else None
            if not video:
                raise ValueError("No videos available for testimonial")
            selection.start_time = 0
            selection.end_time = min(20, video.duration)

        # Clamp times to video duration
        start = max(0, min(selection.start_time, video.duration - 1))
        end = max(start + 1, min(selection.end_time, video.duration))

        video_segment = VideoSegment(
            source_video_id=video.id,
            source_path=video.path,
            start_time=start,
            end_time=end,
            description="Customer testimonial"
        )

        return StorySegment(
            segment_type=SegmentType.VIDEO_CLIP,
            content=video_segment,
            order=3
        )

    def _assemble_story(
        self,
        title: str,
        description: str,
        intro_segment: StorySegment,
        pain_scene: StorySegment,
        solution_segment: StorySegment,
        testimonial_segment: StorySegment,
        output_filename: str
    ) -> StoryPlan:
        """Assemble all segments into a final story plan."""
        # Re-order segments
        pain_scene.order = 0
        solution_segment.order = 1
        testimonial_segment.order = 2

        return StoryPlan(
            title=title,
            description=description,
            intro=intro_segment,
            segments=[pain_scene, solution_segment, testimonial_segment],
            output_filename=output_filename
        )


# Convenience function
def generate_personalized_video(
    customer_situation: str,
    output_filename: str = "personalized_video.mp4",
    config: Optional[Config] = None
) -> StoryPlan:
    """Generate a personalized video story from a customer situation."""
    generator = PersonalizedStoryGenerator(config)
    return generator.generate_story(customer_situation, output_filename)

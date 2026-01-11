"""
Video Analyzer - LLM-based content analysis using Gemini.

Uses Google's Gemini model to analyze video content directly.
Uses Pydantic for structured output from the LLM.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from videoagent.config import Config, default_config
from videoagent.gemini import GeminiClient
from videoagent.models import IntroCandidate

# ==================== Pydantic Response Models ====================

class IntroAnalysis(BaseModel):
    """Response model for intro suitability analysis."""
    description: str = Field(description="Description of what happens in the intro")
    reasoning: str = Field(description="Why this would or wouldn't work as an intro")
    suggested_script: Optional[str] = Field(
        default=None,
        description="A suggested voice-over script for this intro (1-2 sentences)"
    )


def upload_video_segment(
    client: GeminiClient,
    video_path: Path,
    start_time: float,
    end_time: float
) -> object:
    """
    Upload a segment of a video to Gemini.

    Extracts the segment first using ffmpeg, then uploads it.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(start_time),
            "-t", str(end_time - start_time),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            str(tmp_path)
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return client.upload_file(tmp_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# ==================== Video Analyzer ====================

class VideoAnalyzer:
    """Analyzes video content using Gemini's native video understanding."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self.client = GeminiClient(config)

    def analyze_intro_suitability(
        self,
        video_path: Path,
        intro_duration: float = 5.0,
        context: Optional[str] = None
    ) -> IntroCandidate:
        """
        Analyze the first N seconds of a video for intro suitability.

        Args:
            video_path: Path to the video file
            intro_duration: Duration of intro to analyze (seconds)
            context: Optional context about what kind of intro is needed

        Returns:
            IntroCandidate with analysis
        """
        video_file = upload_video_segment(self.client, video_path, 0, intro_duration)

        context_text = f"\nContext: {context}" if context else ""

        prompt = f"""Analyze this video clip (the first {intro_duration} seconds of a longer video).
Evaluate how suitable this would be as an intro/opening for a video compilation.
{context_text}

Consider:
- Visual appeal and engagement
- Does it capture attention?
- Is it dynamic or static?
- Would it work well as an opening?"""

        result = self.client.analyze_video(video_file, prompt, IntroAnalysis)

        from videoagent.library import get_video_id
        video_id = get_video_id(video_path)

        return IntroCandidate(
            video_id=video_id,
            video_path=video_path,
            start_time=0,
            end_time=intro_duration,
            description=result.description,
            reasoning=result.reasoning,
            suggested_script=result.suggested_script
        )


# ==================== Convenience Functions ====================

def analyze_intro(
    video_path: Path,
    duration: float = 5.0,
    context: Optional[str] = None,
    config: Optional[Config] = None
) -> IntroCandidate:
    """Analyze the intro of a video."""
    analyzer = VideoAnalyzer(config)
    return analyzer.analyze_intro_suitability(video_path, duration, context)

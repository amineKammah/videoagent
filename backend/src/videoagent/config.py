"""
Configuration for the Video Agent.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """Main configuration for the video agent."""

    # Video library settings
    video_library_path: Path = field(
        default_factory=lambda: Path("assets/normalized_videos")
    )
    transcript_library_path: Optional[Path] = None
    supported_formats: tuple = (".mp4", ".mov", ".avi", ".mkv", ".webm")

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    output_format: str = "mp4"
    output_fps: int = 30
    output_resolution: tuple = (1920, 1080)
    ffmpeg_threads: int = 8  # 0 lets ffmpeg auto-select threads

    # Gemini LLM settings
    gemini_model: str = "gemini-3-flash-preview"
    gemini_tts_model: str = "gemini-2.5-flash-tts"
    agent_model: str = "vertex_ai/gemini-3-pro-preview"

    # TTS settings
    tts_voice: str = "Kore"  # Kore, Charon, Fenrir, Aoede, Puck, etc.

    # GCP settings for Transcoder API
    gcp_project_id: Optional[str] = None
    gcp_location: str = "europe-west2"

    # Intro analysis settings
    intro_duration_seconds: float = 5.0
    intro_candidates_count: int = 3

    # Static scene defaults
    default_scene_duration: float = 3.0
    default_font_size: int = 60
    default_bg_color: str = "#000000"
    default_text_color: str = "#FFFFFF"

    # Voice over timing handling
    # "extend_frame" - freeze last frame if VO is longer
    # "truncate_audio" - cut audio if longer than video
    # "speed_up_audio" - speed up audio to fit video
    vo_longer_strategy: str = "extend_frame"

    # "pad_silence" - add silence at end
    # "loop_video" - loop video segment
    # "slow_down_audio" - slow down audio (within limits)
    vo_shorter_strategy: str = "pad_silence"

    def __post_init__(self):
        """Ensure paths are Path objects and create directories."""
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)


# Default configuration instance
default_config = Config()

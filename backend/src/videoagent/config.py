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

    # LLM settings
    gemini_model: str = "gemini-3-flash-preview"
    gemini_tts_model: str = "gemini-2.5-flash-tts"
    agent_model: str = "vertex_ai/gemini-3.1-pro-preview"
    session_title_model: str = "gemini-2.5-flash"

    # TTS settings
    tts_voice: str = "Kore"  # Kore, Charon, Fenrir, Aoede, Puck, etc.

    # GCP settings for Transcoder API
    gcp_project_id: Optional[str] = None
    gcp_location: str = "europe-west2"

    def __post_init__(self):
        """Ensure paths are Path objects and create directories."""
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)


# Default configuration instance
default_config = Config()

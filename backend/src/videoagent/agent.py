"""
Video Agent - Main orchestration for personalized video generation.

    Simple pipeline that takes a customer situation and produces a personalized video.
"""
from typing import Optional

from videoagent.config import Config, default_config
from videoagent.editor import VideoEditor
from videoagent.story import PersonalizedStoryGenerator


class VideoAgent:
    """
    Agent orchestration for video generation components.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config

        self.editor = VideoEditor(config)
        self.story_generator = PersonalizedStoryGenerator(config)

    def cleanup(self) -> None:
        """Clean up temporary files."""
        self.editor.cleanup()
        self.story_generator.voice_generator.cleanup()

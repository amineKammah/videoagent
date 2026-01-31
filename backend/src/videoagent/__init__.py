"""
Video Agent - LLM-powered personalized video generation.

Creates personalized videos from customer situations by:
1. Analyzing video library transcripts
2. Finding relevant intro, solution, and testimonial content
3. Generating voice overs
4. Assembling everything into a final video
"""


from videoagent.config import Config, default_config
from videoagent.editor import VideoEditor, cut_video, join_videos
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary, scan_video_library, search_videos_by_keyword
from videoagent.models import (

    RenderResult,
    SceneMatch,
    SegmentType,
    StorySegment,
    TranscriptMatch,
    TranscriptSegment,
    VideoLibraryIndex,
    VideoMetadata,
    VideoSegment,
    VoiceOver,
)
from videoagent.story import PersonalizedStoryGenerator, generate_personalized_video
from videoagent.voice import VoiceOverGenerator, estimate_speech_duration, generate_voice_over

__version__ = "0.1.0"

__all__ = [
    # Config
    "Config",
    "default_config",

    # Models
    "VideoMetadata",
    "VideoSegment",
    "StorySegment",
    "VoiceOver",

    "RenderResult",
    "TranscriptSegment",
    "TranscriptMatch",
    "SceneMatch",
    "VideoLibraryIndex",

    # Gemini
    "GeminiClient",

    # Library
    "VideoLibrary",
    "scan_video_library",
    "search_videos_by_keyword",



    # Editor
    "VideoEditor",
    "cut_video",
    "join_videos",

    # Voice
    "VoiceOverGenerator",
    "generate_voice_over",
    "estimate_speech_duration",

    # Story
    "PersonalizedStoryGenerator",
    "generate_personalized_video",


]

"""
Video Agent - LLM-powered personalized video generation.

Creates personalized videos from customer situations by:
1. Analyzing video library transcripts
2. Finding relevant intro, solution, and testimonial content
3. Generating voice overs
4. Assembling everything into a final video
"""

from videoagent.config import Config, default_config
from videoagent.models import (
    VideoMetadata,
    VideoSegment,
    StaticScene,
    StorySegment,
    StoryPlan,
    VoiceOver,
    IntroCandidate,
    SegmentType,
    RenderResult,
    TranscriptSegment,
    SceneMatch,
    VideoLibraryIndex,
)
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary, scan_video_library, search_videos_by_keyword
from videoagent.analyzer import VideoAnalyzer, analyze_intro, IntroAnalysis
from videoagent.editor import VideoEditor, cut_video, create_title_card, join_videos
from videoagent.voice import VoiceOverGenerator, generate_voice_over, estimate_speech_duration
from videoagent.story import PersonalizedStoryGenerator, generate_personalized_video
from videoagent.agent import VideoAgent, create_personalized_video

__version__ = "0.1.0"

__all__ = [
    # Config
    "Config",
    "default_config",

    # Models
    "VideoMetadata",
    "VideoSegment",
    "StaticScene",
    "StorySegment",
    "StoryPlan",
    "VoiceOver",
    "IntroCandidate",
    "SegmentType",
    "RenderResult",
    "TranscriptSegment",
    "SceneMatch",
    "VideoLibraryIndex",

    # Gemini
    "GeminiClient",

    # Library
    "VideoLibrary",
    "scan_video_library",
    "search_videos_by_keyword",

    # Analyzer
    "VideoAnalyzer",
    "analyze_intro",
    "IntroAnalysis",

    # Editor
    "VideoEditor",
    "cut_video",
    "create_title_card",
    "join_videos",

    # Voice
    "VoiceOverGenerator",
    "generate_voice_over",
    "estimate_speech_duration",

    # Story
    "PersonalizedStoryGenerator",
    "generate_personalized_video",

    # Agent
    "VideoAgent",
    "create_personalized_video",
]

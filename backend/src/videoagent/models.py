"""
Data models for the Video Agent.

These dataclasses define the core structures used throughout the system.
"""
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Union


class SegmentType(Enum):
    """Type of segment in a story."""
    VIDEO_CLIP = "video_clip"
    STATIC_SCENE = "static_scene"
    TRANSITION = "transition"


@dataclass
class TranscriptSegment:
    """A single segment of transcript with timing information."""
    text: str
    start_time: float  # in seconds
    end_time: float  # in seconds

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class VideoMetadata:
    """
    Metadata for a video in the library.

    This is indexed and stored for quick searching.
    """
    id: str
    path: Path
    filename: str
    duration: float  # in seconds
    resolution: tuple[int, int]  # (width, height)
    fps: float
    file_size: int  # in bytes

    # Transcript with timestamps
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.path, str):
            self.path = Path(self.path)

    def get_full_transcript(self) -> str:
        """Concatenate all transcript segments into a single string."""
        return " ".join(seg.text for seg in self.transcript_segments)

    def get_transcript_at_time(self, time: float) -> Optional[TranscriptSegment]:
        """Get the transcript segment at a specific time."""
        for seg in self.transcript_segments:
            if seg.start_time <= time <= seg.end_time:
                return seg
        return None

    def get_transcript_in_range(self, start: float, end: float) -> list[TranscriptSegment]:
        """Get all transcript segments within a time range."""
        return [
            seg for seg in self.transcript_segments
            if seg.end_time >= start and seg.start_time <= end
        ]


@dataclass
class VideoSegment:
    """
    A segment cut from a source video.

    Represents a specific time range from an existing video.
    """
    source_video_id: str
    source_path: Path
    start_time: float  # in seconds
    end_time: float  # in seconds
    description: Optional[str] = None

    # Audio handling
    keep_original_audio: bool = True
    audio_volume: float = 1.0  # 0.0 to 1.0+

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def __post_init__(self):
        if isinstance(self.source_path, str):
            self.source_path = Path(self.source_path)


@dataclass
class StaticScene:
    """
    A static scene with text, used for transitions or title cards.
    """
    text: str
    duration: float  # in seconds

    # Styling
    background_color: str = "#000000"
    text_color: str = "#FFFFFF"
    font_size: int = 60
    font_family: str = "Arial"

    # Text positioning (center by default)
    text_position: str = "center"  # "center", "top", "bottom", or (x, y) tuple

    # Optional background image
    background_image_path: Optional[Path] = None

    # Optional subtitle/secondary text
    subtitle: Optional[str] = None
    subtitle_font_size: int = 40

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class VoiceOver:
    """
    A voice over segment with script and audio.
    """
    script: str
    audio_path: Optional[Path] = None  # Set after TTS generation
    duration: Optional[float] = None  # Set after TTS generation

    # TTS settings
    voice: str = "alloy"
    speed: float = 1.0

    # Volume for mixing
    volume: float = 1.0

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __post_init__(self):
        if self.audio_path and isinstance(self.audio_path, str):
            self.audio_path = Path(self.audio_path)


@dataclass
class StorySegment:
    """
    A single segment in the story timeline.

    Can be a video clip, static scene, or transition.
    """
    segment_type: SegmentType
    content: Union[VideoSegment, StaticScene]

    # Voice over for this segment (optional)
    voice_over: Optional[VoiceOver] = None

    # How to handle VO timing mismatches for this specific segment
    vo_timing_strategy: Optional[str] = None  # Override global config if set

    # Ordering
    order: int = 0

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def duration(self) -> float:
        """Get the base duration of the segment (before VO adjustments)."""
        if isinstance(self.content, VideoSegment):
            return self.content.duration
        elif isinstance(self.content, StaticScene):
            return self.content.duration
        return 0.0


@dataclass
class IntroCandidate:
    """
    A candidate video segment for use as an intro.
    """
    video_id: str
    video_path: Path
    start_time: float
    end_time: float

    # LLM analysis results
    description: str
    reasoning: str  # Why this was selected

    # Suggested voice over script for this intro
    suggested_script: Optional[str] = None

    def to_video_segment(self) -> VideoSegment:
        """Convert to a VideoSegment for use in a story."""
        return VideoSegment(
            source_video_id=self.video_id,
            source_path=self.video_path,
            start_time=self.start_time,
            end_time=self.end_time,
            description=self.description
        )


@dataclass
class SceneMatch:
    """
    A scene/segment from a video that matches a search query.

    Returned by LLM-based scene search.
    """
    video_id: str
    video_path: Path
    start_time: float
    end_time: float
    relevance_explanation: str  # Why this scene is relevant to the query
    transcript_snippet: Optional[str] = None  # The transcript text in this range

    def to_video_segment(self) -> VideoSegment:
        """Convert to a VideoSegment."""
        return VideoSegment(
            source_video_id=self.video_id,
            source_path=self.video_path,
            start_time=self.start_time,
            end_time=self.end_time,
            description=self.relevance_explanation
        )


@dataclass
class StoryPlan:
    """
    The complete plan for a generated video.

    This is what the LLM generates and what gets rendered.
    """
    title: str
    description: str

    # The intro segment (optional)
    intro: Optional[StorySegment] = None

    # Main story segments in order
    segments: list[StorySegment] = field(default_factory=list)

    # Background music (optional)
    background_music_path: Optional[Path] = None
    background_music_volume: float = 0.3

    # Output settings
    output_filename: str = "output.mp4"

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def total_duration(self) -> float:
        """Calculate total duration of the story."""
        total = 0.0
        if self.intro:
            total += self.intro.duration
        for segment in self.segments:
            total += segment.duration
        return total

    def get_all_segments(self) -> list[StorySegment]:
        """Get all segments in order (intro + main)."""
        all_segments = []
        if self.intro:
            all_segments.append(self.intro)
        all_segments.extend(self.segments)
        return all_segments


@dataclass
class RenderResult:
    """
    Result of rendering a story plan to a video file.
    """
    success: bool
    output_path: Optional[Path] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    error_message: Optional[str] = None

    # Timing adjustments made during rendering
    timing_adjustments: list[str] = field(default_factory=list)


@dataclass
class VideoLibraryIndex:
    """
    Index of all videos in the library with their metadata.
    """
    videos: dict[str, VideoMetadata] = field(default_factory=dict)
    last_indexed: Optional[str] = None  # ISO timestamp

    # LLM function for scene search (set externally)
    _llm_search_fn: Optional[Callable] = field(default=None, repr=False)

    def add_video(self, metadata: VideoMetadata) -> None:
        """Add a video to the index."""
        self.videos[metadata.id] = metadata

    def get_video(self, video_id: str) -> Optional[VideoMetadata]:
        """Get a video by ID."""
        return self.videos.get(video_id)

    def search_by_transcript_keyword(
        self,
        keyword: str
    ) -> list[tuple[VideoMetadata, list[TranscriptSegment]]]:
        """
        Search for videos containing a keyword in their transcript.

        Args:
            keyword: The keyword to search for (case-insensitive)

        Returns:
            List of tuples (video, matching_segments) where matching_segments
            are the transcript segments containing the keyword.
        """
        keyword_lower = keyword.lower()
        results = []

        for video in self.videos.values():
            matching_segments = [
                seg for seg in video.transcript_segments
                if keyword_lower in seg.text.lower()
            ]
            if matching_segments:
                results.append((video, matching_segments))

        return results

    def search_scenes_by_llm(
        self,
        query: str,
        llm_fn: Optional[Callable] = None
    ) -> list[SceneMatch]:
        """
        Use LLM to find relevant scenes across all videos.

        The LLM analyzes transcripts and video metadata to find scenes
        that match the query semantically.

        Args:
            query: Natural language query describing what to find
            llm_fn: Optional LLM function to use. If not provided,
                    uses the one set on the index via _llm_search_fn.

                    The function signature should be:
                    fn(query: str, videos: list[VideoMetadata]) -> list[SceneMatch]

        Returns:
            List of SceneMatch objects for relevant scenes.
        """
        search_fn = llm_fn or self._llm_search_fn

        if search_fn is None:
            raise ValueError(
                "No LLM search function provided. Either pass llm_fn parameter "
                "or set _llm_search_fn on the index."
            )

        videos_list = list(self.videos.values())
        return search_fn(query, videos_list)

    def set_llm_search_function(self, fn: Callable) -> None:
        """
        Set the LLM function used for scene search.

        Args:
            fn: Function with signature
                (query: str, videos: list[VideoMetadata]) -> list[SceneMatch]
        """
        self._llm_search_fn = fn

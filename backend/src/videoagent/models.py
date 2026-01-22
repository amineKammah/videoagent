"""
Data models for the Video Agent.

These models define the core structures used throughout the system.
"""
import uuid
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class VideoAgentModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)


class SegmentType(Enum):
    """Type of segment in a story."""
    VIDEO_CLIP = "video_clip"


class TranscriptSegment(VideoAgentModel):
    """A single segment of transcript with timing information."""
    text: str
    start_time: float  # in seconds
    end_time: float  # in seconds

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class VideoMetadata(VideoAgentModel):
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

    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)

    def get_full_transcript(self) -> str:
        """Concatenate transcript segments with timestamps into a single string."""
        return " ".join(
            f"[{seg.start_time:.2f}-{seg.end_time:.2f}] {seg.text}"
            for seg in self.transcript_segments
        )

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


class VideoSegment(VideoAgentModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    """
    A segment cut from a source video.

    Represents a specific time range from an existing video.
    """
    source_video_id: Optional[str] = None
    start_time: float  # in seconds
    end_time: float  # in seconds
    description: Optional[str] = None

    # Audio handling
    keep_original_audio: bool = True

    @model_validator(mode="before")
    @classmethod
    def _strip_source_path(cls, values):
        if isinstance(values, dict):
            values.pop("source_path", None)
        return values

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class VoiceOver(VideoAgentModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    """
    A voice over segment with script and audio.
    """
    script: str
    audio_id: Optional[str] = None
    duration: Optional[float] = None

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])


class StorySegment(VideoAgentModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra="forbid",
    )
    """
    A single segment in the story timeline.

    Can be a video clip.
    """
    segment_type: SegmentType
    content: VideoSegment

    storyboard_scene_id: Optional[str] = None
    transcript: Optional[str] = None
    voice_over: Optional[VoiceOver] = None
    order: int = 0

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def duration(self) -> float:
        return self.content.duration

    @model_validator(mode="after")
    def _validate_content(self) -> "StorySegment":
        if self.segment_type != SegmentType.VIDEO_CLIP or not isinstance(
            self.content, VideoSegment
        ):
            raise ValueError("video_clip segments require VideoSegment content.")
        return self


class IntroCandidate(VideoAgentModel):
    """
    A candidate video segment for use as an intro.
    """
    video_id: str
    video_path: Path
    start_time: float
    end_time: float

    description: str
    reasoning: str
    suggested_script: Optional[str] = None

    def to_video_segment(self) -> VideoSegment:
        """Convert to a VideoSegment for use in a story."""
        return VideoSegment(
            source_video_id=self.video_id,
            start_time=self.start_time,
            end_time=self.end_time,
            description=self.description,
        )


class SceneMatch(VideoAgentModel):
    """
    A scene/segment from a video that matches a search query.
    """ 
    video_id: str
    video_path: Path
    start_time: float
    end_time: float
    relevance_explanation: str
    transcript_snippet: Optional[str] = None

    def to_video_segment(self) -> VideoSegment:
        """Convert to a VideoSegment."""
        return VideoSegment(
            source_video_id=self.video_id,
            start_time=self.start_time,
            end_time=self.end_time,
            description=self.relevance_explanation,
        )


class RenderResult(VideoAgentModel):
    """
    Result of rendering story segments to a video file.
    """
    success: bool
    output_path: Optional[Path] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    error_message: Optional[str] = None

    timing_adjustments: list[str] = Field(default_factory=list)


class TranscriptMatch(VideoAgentModel):
    """
    A transcript keyword match result for a video.
    """
    video: VideoMetadata
    segments: list[TranscriptSegment] = Field(default_factory=list)


class VideoLibraryIndex(VideoAgentModel):
    """
    Index of all videos in the library with their metadata.
    """
    videos: dict[str, VideoMetadata] = Field(default_factory=dict)
    last_indexed: Optional[str] = None

    _llm_search_fn: Optional[Callable] = PrivateAttr(default=None)

    def add_video(self, metadata: VideoMetadata) -> None:
        """Add a video to the index."""
        self.videos[metadata.id] = metadata

    def get_video(self, video_id: str) -> Optional[VideoMetadata]:
        """Get a video by ID."""
        return self.videos.get(video_id)

    def search_by_transcript_keyword(
        self,
        keyword: str,
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
        llm_fn: Optional[Callable] = None,
    ) -> list[SceneMatch]:
        """
        Use LLM to find relevant scenes across all videos.

        The LLM analyzes transcripts and video metadata to find scenes
        that match the query semantically.
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
        """
        self._llm_search_fn = fn

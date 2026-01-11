"""
Video Library Manager.

Handles indexing, searching, and managing the video library.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from videoagent.config import Config, default_config
from videoagent.models import SceneMatch, TranscriptSegment, VideoLibraryIndex, VideoMetadata


def get_video_id(path: Path) -> str:
    """Generate a unique ID for a video based on its path and modification time."""
    stat = path.stat()
    content = f"{path.absolute()}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def get_video_metadata_ffprobe(path: Path) -> dict:
    """
    Extract video metadata using ffprobe.

    Returns dict with duration, resolution, fps, etc.
    """
    import json as json_module
    import subprocess

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path)
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json_module.loads(result.stdout)

        # Extract video stream info
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        if not video_stream:
            raise ValueError(f"No video stream found in {path}")

        # Parse FPS (can be in format "30/1" or "29.97")
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)

        return {
            "duration": float(data.get("format", {}).get("duration", 0)),
            "resolution": (
                int(video_stream.get("width", 0)),
                int(video_stream.get("height", 0))
            ),
            "fps": fps,
            "file_size": int(data.get("format", {}).get("size", 0))
        }
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed for {path}: {e}")
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Failed to parse ffprobe output for {path}: {e}")


def get_video_metadata_moviepy(path: Path) -> dict:
    """
    Extract video metadata using moviepy.

    Fallback if ffprobe is not available.
    """
    try:
        from moviepy.editor import VideoFileClip

        with VideoFileClip(str(path)) as clip:
            return {
                "duration": clip.duration,
                "resolution": clip.size,
                "fps": clip.fps,
                "file_size": path.stat().st_size
            }
    except ImportError:
        raise RuntimeError("moviepy not installed. Install with: pip install moviepy")


def extract_video_metadata(path: Path, use_ffprobe: bool = True) -> dict:
    """
    Extract video metadata using ffprobe or moviepy.
    """
    if use_ffprobe:
        try:
            return get_video_metadata_ffprobe(path)
        except RuntimeError:
            # Fall back to moviepy
            return get_video_metadata_moviepy(path)
    else:
        return get_video_metadata_moviepy(path)


class VideoLibrary:
    """
    Manages the video library - indexing, searching, and metadata.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self.index = VideoLibraryIndex()
        self._index_path = self.config.video_library_path / ".video_index.json"

    def _load_index(self) -> None:
        """Load the index from disk if it exists."""
        if self._index_path.exists():
            try:
                with open(self._index_path, "r") as f:
                    data = json.load(f)

                self.index.last_indexed = data.get("last_indexed")

                for video_id, video_data in data.get("videos", {}).items():
                    # Load transcript segments
                    transcript_segments = []
                    for seg_data in video_data.get("transcript_segments", []):
                        transcript_segments.append(TranscriptSegment(
                            text=seg_data["text"],
                            start_time=seg_data["start_time"],
                            end_time=seg_data["end_time"]
                        ))

                    metadata = VideoMetadata(
                        id=video_data["id"],
                        path=Path(video_data["path"]),
                        filename=video_data["filename"],
                        duration=video_data["duration"],
                        resolution=tuple(video_data["resolution"]),
                        fps=video_data["fps"],
                        file_size=video_data["file_size"],
                        transcript_segments=transcript_segments
                    )
                    self.index.videos[video_id] = metadata
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Failed to load index, will re-index: {e}")

    def _save_index(self) -> None:
        """Save the index to disk."""
        data = {
            "last_indexed": self.index.last_indexed,
            "videos": {}
        }

        for video_id, metadata in self.index.videos.items():
            # Serialize transcript segments
            transcript_segments = [
                {
                    "text": seg.text,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time
                }
                for seg in metadata.transcript_segments
            ]

            data["videos"][video_id] = {
                "id": metadata.id,
                "path": str(metadata.path),
                "filename": metadata.filename,
                "duration": metadata.duration,
                "resolution": list(metadata.resolution),
                "fps": metadata.fps,
                "file_size": metadata.file_size,
                "transcript_segments": transcript_segments
            }

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._index_path, "w") as f:
            json.dump(data, f, indent=2)

    def scan_library(self, force_reindex: bool = False) -> list[VideoMetadata]:
        """
        Scan the video library directory and index all videos.

        Args:
            force_reindex: If True, re-index all videos even if already indexed.

        Returns:
            List of newly indexed videos.
        """
        if not force_reindex:
            self._load_index()

        library_path = self.config.video_library_path
        if not library_path.exists():
            library_path.mkdir(parents=True, exist_ok=True)
            return []

        new_videos = []
        found_ids = set()

        # Scan for video files
        for path in library_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in self.config.supported_formats:
                video_id = get_video_id(path)
                found_ids.add(video_id)

                # Skip if already indexed and not forcing reindex
                if not force_reindex and video_id in self.index.videos:
                    continue

                try:
                    meta = extract_video_metadata(path)

                    metadata = VideoMetadata(
                        id=video_id,
                        path=path,
                        filename=path.name,
                        duration=meta["duration"],
                        resolution=meta["resolution"],
                        fps=meta["fps"],
                        file_size=meta["file_size"]
                    )

                    self.index.add_video(metadata)
                    new_videos.append(metadata)

                except Exception as e:
                    print(f"Warning: Failed to index {path}: {e}")

        # Remove videos that no longer exist
        removed_ids = set(self.index.videos.keys()) - found_ids
        for video_id in removed_ids:
            del self.index.videos[video_id]

        self.index.last_indexed = datetime.now().isoformat()
        self._save_index()

        return new_videos

    def list_videos(self) -> list[VideoMetadata]:
        """List all videos in the library."""
        if not self.index.videos:
            self._load_index()
        return list(self.index.videos.values())

    def get_video(self, video_id: str) -> Optional[VideoMetadata]:
        """Get a video by ID."""
        if not self.index.videos:
            self._load_index()
        return self.index.get_video(video_id)

    def get_video_by_path(self, path: Path) -> Optional[VideoMetadata]:
        """Get a video by its file path."""
        if not self.index.videos:
            self._load_index()

        path = Path(path).absolute()
        for video in self.index.videos.values():
            if video.path.absolute() == path:
                return video
        return None

    def search_by_duration(
        self,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> list[VideoMetadata]:
        """
        Search for videos by duration.

        Args:
            min_duration: Minimum duration in seconds
            max_duration: Maximum duration in seconds

        Returns:
            List of matching videos
        """
        if not self.index.videos:
            self._load_index()

        results = list(self.index.videos.values())

        if min_duration is not None:
            results = [v for v in results if v.duration >= min_duration]

        if max_duration is not None:
            results = [v for v in results if v.duration <= max_duration]

        return results

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
        if not self.index.videos:
            self._load_index()

        return self.index.search_by_transcript_keyword(keyword)

    def search_scenes_by_llm(self, query: str) -> list[SceneMatch]:
        """
        Use LLM to find relevant scenes across all videos.

        Args:
            query: Natural language query describing what to find

        Returns:
            List of SceneMatch objects for relevant scenes.

        Note:
            Requires an LLM search function to be set via set_llm_search_function()
        """
        if not self.index.videos:
            self._load_index()

        return self.index.search_scenes_by_llm(query)

    def set_llm_search_function(self, fn) -> None:
        """
        Set the LLM function used for scene search.

        Args:
            fn: Function with signature
                (query: str, videos: list[VideoMetadata]) -> list[SceneMatch]
        """
        self.index.set_llm_search_function(fn)

    def update_video_transcript(
        self,
        video_id: str,
        transcript_segments: list[TranscriptSegment]
    ) -> Optional[VideoMetadata]:
        """
        Update transcript for a video.

        Returns the updated metadata or None if video not found.
        """
        video = self.get_video(video_id)
        if not video:
            return None

        video.transcript_segments = transcript_segments
        self._save_index()
        return video


# Convenience functions for direct use
def list_all_videos(config: Optional[Config] = None) -> list[VideoMetadata]:
    """List all videos in the library."""
    library = VideoLibrary(config)
    return library.list_videos()


def scan_video_library(
    library_path: Optional[Path] = None,
    force_reindex: bool = False
) -> list[VideoMetadata]:
    """Scan and index the video library."""
    config = Config(video_library_path=library_path) if library_path else default_config
    library = VideoLibrary(config)
    return library.scan_library(force_reindex)


def search_videos_by_keyword(
    keyword: str,
    config: Optional[Config] = None
) -> list[tuple[VideoMetadata, list[TranscriptSegment]]]:
    """Search for videos by keyword in transcript."""
    library = VideoLibrary(config)
    return library.search_by_transcript_keyword(keyword)

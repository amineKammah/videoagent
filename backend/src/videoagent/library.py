"""Video Library Manager backed by Google Cloud Storage."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from videoagent.config import Config, default_config
from videoagent.models import SceneMatch, TranscriptSegment, VideoLibraryIndex, VideoMetadata
from videoagent.storage import GCSStorageClient, get_storage_client


def get_video_id(path: str, generation: Optional[str] = None, size: Optional[int] = None) -> str:
    """Generate a stable ID for a blob version."""
    content = f"{path}:{generation or ''}:{size or ''}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def get_video_metadata_ffprobe(path: Path) -> dict:
    """Extract video metadata using ffprobe."""
    import json as json_module
    import subprocess

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json_module.loads(result.stdout)

    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

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
            int(video_stream.get("height", 0)),
        ),
        "fps": fps,
        "file_size": int(data.get("format", {}).get("size", 0)),
    }


def get_video_metadata_moviepy(path: Path) -> dict:
    """Fallback metadata extraction using moviepy."""
    try:
        from moviepy.editor import VideoFileClip

        with VideoFileClip(str(path)) as clip:
            return {
                "duration": clip.duration,
                "resolution": clip.size,
                "fps": clip.fps,
                "file_size": path.stat().st_size,
            }
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("moviepy not installed. Install with: pip install moviepy") from exc


def extract_video_metadata(path: Path, use_ffprobe: bool = True) -> dict:
    """Extract video metadata using ffprobe or moviepy."""
    if use_ffprobe:
        try:
            return get_video_metadata_ffprobe(path)
        except Exception:
            return get_video_metadata_moviepy(path)
    return get_video_metadata_moviepy(path)


def load_transcript_segments_from_data(data: dict[str, Any]) -> list[TranscriptSegment]:
    """Load transcript segments from transcript JSON payload."""
    segments: list[TranscriptSegment] = []
    for seg in data.get("segments", []):
        try:
            segments.append(
                TranscriptSegment(
                    text=str(seg.get("text", "")).strip(),
                    start_time=float(seg.get("start", 0)),
                    end_time=float(seg.get("end", 0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return segments


class VideoLibrary:
    """Manages indexing/searching video metadata from GCS."""

    def __init__(self, config: Optional[Config] = None, company_id: Optional[str] = None):
        self.config = config or default_config
        self.company_id = company_id
        self.storage: GCSStorageClient = get_storage_client(self.config)
        self.index = VideoLibraryIndex()

        if company_id:
            base_prefix = f"companies/{company_id}"
            self._video_prefix = f"{base_prefix}/videos/"
            self._transcript_prefix = f"{base_prefix}/transcripts/"
            self._metadata_prefix = f"{base_prefix}/metadata/"
            self._index_key = f"{base_prefix}/indexes/video_index_2.json"
        else:
            self._video_prefix = "videos/"
            self._transcript_prefix = "transcripts/"
            self._metadata_prefix = "metadata/"
            self._index_key = "indexes/video_index_2.json"

    def _transcript_key_for_video(self, video_blob_path: str) -> str:
        if video_blob_path.startswith(self._video_prefix):
            relative = video_blob_path[len(self._video_prefix) :]
        else:
            relative = Path(video_blob_path).name
        return f"{self._transcript_prefix}{Path(relative).with_suffix('.json').as_posix()}"

    def _metadata_key_for_video(self, video_id: str) -> str:
        return f"{self._metadata_prefix}{video_id}.json"

    def _load_index(self) -> None:
        """Load index from GCS if available."""
        if not self.storage.exists(self._index_key):
            return

        try:
            data = self.storage.read_json(self._index_key)
            self.index.last_indexed = data.get("last_indexed")
            loaded: dict[str, VideoMetadata] = {}

            for video_id, video_data in data.get("videos", {}).items():
                transcript_segments = [
                    TranscriptSegment(
                        text=seg_data["text"],
                        start_time=seg_data["start_time"],
                        end_time=seg_data["end_time"],
                    )
                    for seg_data in video_data.get("transcript_segments", [])
                ]

                loaded[video_id] = VideoMetadata(
                    id=video_data["id"],
                    path=video_data["path"],
                    filename=video_data["filename"],
                    duration=video_data["duration"],
                    resolution=tuple(video_data["resolution"]),
                    fps=video_data["fps"],
                    file_size=video_data["file_size"],
                    transcript_segments=transcript_segments,
                )

            self.index.videos = loaded
        except Exception as exc:
            print(f"Warning: Failed to load video index from GCS, will re-index: {exc}")

    def _save_index(self) -> None:
        """Persist current index to GCS."""
        data = {
            "last_indexed": self.index.last_indexed,
            "videos": {},
        }

        for video_id, metadata in self.index.videos.items():
            transcript_segments = [
                {
                    "text": seg.text,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                }
                for seg in metadata.transcript_segments
            ]

            data["videos"][video_id] = {
                "id": metadata.id,
                "path": metadata.path,
                "filename": metadata.filename,
                "duration": metadata.duration,
                "resolution": list(metadata.resolution),
                "fps": metadata.fps,
                "file_size": metadata.file_size,
                "transcript_segments": transcript_segments,
            }

        self.storage.write_json(self._index_key, data)

    def _load_cached_video_metadata(
        self,
        video_id: str,
        expected_generation: Optional[str],
    ) -> Optional[dict[str, Any]]:
        metadata_key = self._metadata_key_for_video(video_id)
        if not self.storage.exists(metadata_key):
            return None

        try:
            cached = self.storage.read_json(metadata_key)
        except Exception:
            return None

        if expected_generation and cached.get("source_generation") != expected_generation:
            return None
        return cached

    def _extract_and_cache_video_metadata(
        self,
        video_blob_path: str,
        video_id: str,
        blob_meta: dict[str, Any],
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="videoagent_scan_") as temp_dir:
            local_path = Path(temp_dir) / Path(video_blob_path).name
            self.storage.download_to_filename(video_blob_path, local_path)
            extracted = extract_video_metadata(local_path)

        payload = {
            "id": video_id,
            "path": self.storage.to_gs_uri(video_blob_path),
            "filename": Path(video_blob_path).name,
            "duration": extracted.get("duration", 0.0),
            "resolution": list(extracted.get("resolution", (0, 0))),
            "fps": extracted.get("fps", 0.0),
            "file_size": extracted.get("file_size", blob_meta.get("size") or 0),
            "source_generation": blob_meta.get("generation"),
            "source_updated": blob_meta.get("updated"),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.storage.write_json(self._metadata_key_for_video(video_id), payload)
        return payload

    def _load_transcript_segments(self, video_blob_path: str) -> list[TranscriptSegment]:
        transcript_key = self._transcript_key_for_video(video_blob_path)
        if not self.storage.exists(transcript_key):
            return []

        try:
            transcript_data = self.storage.read_json(transcript_key)
            return load_transcript_segments_from_data(transcript_data)
        except Exception:
            return []

    def scan_library(self, force_reindex: bool = False) -> list[VideoMetadata]:
        """Scan the company's GCS video library and refresh index."""
        if not force_reindex:
            self._load_index()

        new_videos: list[VideoMetadata] = []
        found_ids: set[str] = set()

        for video_blob_path in self.storage.list_files(self._video_prefix, recursive=True):
            suffix = Path(video_blob_path).suffix.lower()
            if suffix not in self.config.supported_formats:
                continue

            try:
                blob_meta = self.storage.get_metadata(video_blob_path)
                video_id = get_video_id(
                    video_blob_path,
                    generation=blob_meta.get("generation"),
                    size=blob_meta.get("size"),
                )
                found_ids.add(video_id)

                if not force_reindex and video_id in self.index.videos:
                    continue

                metadata_payload = self._load_cached_video_metadata(
                    video_id,
                    expected_generation=blob_meta.get("generation"),
                )
                if not metadata_payload:
                    metadata_payload = self._extract_and_cache_video_metadata(
                        video_blob_path,
                        video_id,
                        blob_meta,
                    )

                transcript_segments = self._load_transcript_segments(video_blob_path)

                metadata = VideoMetadata(
                    id=video_id,
                    path=metadata_payload["path"],
                    filename=metadata_payload["filename"],
                    duration=float(metadata_payload.get("duration", 0.0)),
                    resolution=tuple(metadata_payload.get("resolution", (0, 0))),
                    fps=float(metadata_payload.get("fps", 0.0)),
                    file_size=int(metadata_payload.get("file_size", blob_meta.get("size") or 0)),
                    transcript_segments=transcript_segments,
                )

                self.index.add_video(metadata)
                new_videos.append(metadata)
            except Exception as exc:
                print(f"Warning: Failed to index {video_blob_path}: {exc}")

        removed_ids = set(self.index.videos.keys()) - found_ids
        for video_id in removed_ids:
            del self.index.videos[video_id]

        self.index.last_indexed = datetime.now(timezone.utc).isoformat()
        self._save_index()
        return new_videos

    def list_videos(self) -> list[VideoMetadata]:
        if not self.index.videos:
            self._load_index()
        if not self.index.videos:
            self.scan_library()
        return list(self.index.videos.values())

    def get_video(self, video_id: str) -> Optional[VideoMetadata]:
        if not self.index.videos:
            self._load_index()
        if not self.index.videos:
            self.scan_library()
        return self.index.get_video(video_id)

    def get_video_by_path(self, path: str | Path) -> Optional[VideoMetadata]:
        if not self.index.videos:
            self._load_index()
        target = str(path).strip()
        for video in self.index.videos.values():
            if video.path == target:
                return video
        return None

    def search_by_duration(
        self,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> list[VideoMetadata]:
        if not self.index.videos:
            self._load_index()
        if not self.index.videos:
            self.scan_library()

        results = list(self.index.videos.values())

        if min_duration is not None:
            results = [v for v in results if v.duration >= min_duration]
        if max_duration is not None:
            results = [v for v in results if v.duration <= max_duration]

        return results

    def search_by_transcript_keyword(
        self,
        keyword: str,
    ) -> list[tuple[VideoMetadata, list[TranscriptSegment]]]:
        if not self.index.videos:
            self._load_index()
        if not self.index.videos:
            self.scan_library()
        return self.index.search_by_transcript_keyword(keyword)

    def search_scenes_by_llm(self, query: str) -> list[SceneMatch]:
        if not self.index.videos:
            self._load_index()
        if not self.index.videos:
            self.scan_library()
        return self.index.search_scenes_by_llm(query)

    def set_llm_search_function(self, fn) -> None:
        self.index.set_llm_search_function(fn)

    def update_video_transcript(
        self,
        video_id: str,
        transcript_segments: list[TranscriptSegment],
    ) -> Optional[VideoMetadata]:
        video = self.get_video(video_id)
        if not video:
            return None

        video.transcript_segments = transcript_segments
        self._save_index()
        return video


def list_all_videos(config: Optional[Config] = None) -> list[VideoMetadata]:
    library = VideoLibrary(config)
    return library.list_videos()


def scan_video_library(
    library_path: Optional[Path] = None,
    transcript_library_path: Optional[Path] = None,
    force_reindex: bool = False,
) -> list[VideoMetadata]:
    """Backward-compatible helper; ignores local path arguments in GCS mode."""
    _ = (library_path, transcript_library_path)
    library = VideoLibrary(default_config)
    return library.scan_library(force_reindex)


def search_videos_by_keyword(
    keyword: str,
    config: Optional[Config] = None,
) -> list[tuple[VideoMetadata, list[TranscriptSegment]]]:
    library = VideoLibrary(config)
    return library.search_by_transcript_keyword(keyword)

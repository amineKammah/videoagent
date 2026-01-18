"""
Video Editor - Cut and concatenate video.

Uses ffmpeg for video manipulation.
"""
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from videoagent.config import Config, default_config
from videoagent.models import (
    RenderResult,
    SegmentType,
    StorySegment,
    VideoSegment,
    VoiceOver,
)
from videoagent.library import VideoLibrary


class VideoEditor:
    """
    Handles all video editing operations.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self._temp_dir = None

    def _get_temp_dir(self) -> Path:
        """Get or create a temporary directory for intermediate files."""
        if self._temp_dir is None:
            self._temp_dir = Path(tempfile.mkdtemp(prefix="video_agent_"))
        return self._temp_dir
    
    def _ffmpeg_thread_args(self) -> list[str]:
        """Return ffmpeg thread arguments based on config."""
        return ["-threads", str(self.config.ffmpeg_threads)]

    def cut_video_segment(
        self,
        segment: VideoSegment,
        output_path: Optional[Path] = None,
        source_path: Optional[Path] = None,
    ) -> Path:
        """
        Cut a segment from a video file.

        Args:
            segment: VideoSegment defining the cut
            output_path: Output path (auto-generated if None)

        Returns:
            Path to the cut video file
        """
        if output_path is None:
            output_path = self._get_temp_dir() / f"segment_{uuid.uuid4().hex[:8]}.mp4"

        if source_path is None and segment.source_video_id:
            library = VideoLibrary(self.config)
            library.scan_library()
            metadata = library.get_video(segment.source_video_id)
            if metadata:
                source_path = metadata.path
        if source_path is None:
            raise ValueError("Video source not found for segment.")

        # Use ffmpeg for cutting (more reliable than moviepy for seeking)
        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            "-i", str(source_path),
            "-ss", str(segment.start_time),
            "-t", str(segment.duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
        ]

        # Handle audio volume
        if not segment.keep_original_audio:
            cmd.extend(["-an"])  # No audio
        elif getattr(segment, "audio_volume", 1.0) != 1.0:
            cmd.extend(["-af", f"volume={getattr(segment, 'audio_volume', 1.0)}"])

        cmd.append(str(output_path))

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to cut video: {e.stderr.decode()}")

    def concatenate_videos(
        self,
        video_paths: list[Path],
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Concatenate multiple video files.

        Args:
            video_paths: List of video file paths
            output_path: Output path (auto-generated if None)

        Returns:
            Path to the concatenated video
        """
        if output_path is None:
            output_path = self._get_temp_dir() / f"concat_{uuid.uuid4().hex[:8]}.mp4"

        if len(video_paths) == 1:
            # Just copy the single video
            import shutil
            shutil.copy(video_paths[0], output_path)
            return output_path

        # Normalize all inputs to a consistent format and SAR
        normalized = [self.normalize_video(path) for path in video_paths]
        normalized = [path for path in normalized if self._has_video_stream(path)]
        if not normalized:
            raise ValueError("No video streams available to concatenate.")
        include_audio = all(self._has_audio_stream(p) for p in normalized)

        input_args: list[str] = []
        filter_parts: list[str] = []
        for i, path in enumerate(normalized):
            input_args.extend(["-i", str(path)])
            filter_parts.append(f"[{i}:v:0]")
            if include_audio:
                filter_parts.append(f"[{i}:a:0]")

        audio_flag = "1" if include_audio else "0"
        filter_complex = (
            "".join(filter_parts)
            + f"concat=n={len(normalized)}:v=1:a={audio_flag}[v]"
            + ("[a]" if include_audio else "")
        )

        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[v]",
        ]
        if include_audio:
            cmd.extend(["-map", "[a]", "-c:a", "aac"])
        else:
            cmd.append("-an")
        cmd.extend(["-c:v", "libx264", "-preset", "fast", str(output_path)])
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def extend_last_frame(
        self,
        video_path: Path,
        extend_duration: float,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Extend a video by freezing the last frame.

        Args:
            video_path: Path to the input video
            extend_duration: How long to extend (seconds)
            output_path: Output path (auto-generated if None)

        Returns:
            Path to the extended video
        """
        if output_path is None:
            output_path = self._get_temp_dir() / f"extended_{uuid.uuid4().hex[:8]}.mp4"

        # Extract last frame
        last_frame = self._get_temp_dir() / "last_frame.png"
        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            "-sseof", "-0.1",  # Seek to near end
            "-i", str(video_path),
            "-frames:v", "1",
            str(last_frame)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        # Create video from last frame
        freeze_video = self._get_temp_dir() / "freeze.mp4"
        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            "-loop", "1",
            "-i", str(last_frame),
            "-c:v", "libx264",
            "-t", str(extend_duration),
            "-pix_fmt", "yuv420p",
            "-r", str(self.config.output_fps),
            str(freeze_video)
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        # Concatenate original + freeze
        return self.concatenate_videos([video_path, freeze_video], output_path)

    def overlay_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Optional[Path] = None,
        replace_original: bool = False,
        audio_volume: float = 1.0,
        original_volume: float = 0.3
    ) -> Path:
        """
        Overlay audio on a video.

        Args:
            video_path: Path to the video
            audio_path: Path to the audio file
            output_path: Output path
            replace_original: If True, replace original audio; if False, mix
            audio_volume: Volume of the overlay audio
            original_volume: Volume of original audio (if mixing)

        Returns:
            Path to the output video
        """
        if not self._has_video_stream(video_path):
            return video_path

        if output_path is None:
            output_path = self._get_temp_dir() / f"audio_overlay_{uuid.uuid4().hex[:8]}.mp4"

        if replace_original:
            cmd = [
                "ffmpeg", "-y",
                *self._ffmpeg_thread_args(),
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-map", "0:v:0?",
                "-map", "1:a:0?",
                "-shortest",
                str(output_path)
            ]
        else:
            # Mix audio tracks
            filter_complex = (
                f"[0:a]volume={original_volume}[a0];"
                f"[1:a]volume={audio_volume}[a1];"
                "[a0][a1]amix=inputs=2:duration=first[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                *self._ffmpeg_thread_args(),
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-filter_complex", filter_complex,
                "-map", "0:v:0?",
                "-map", "[aout]",
                str(output_path)
            ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to overlay audio: {e.stderr.decode()}")

    def normalize_video(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        resolution: Optional[tuple[int, int]] = None,
        fps: Optional[int] = None
    ) -> Path:
        """
        Normalize a video to standard resolution and fps.

        This ensures all videos can be concatenated smoothly.
        """
        if not self._has_video_stream(video_path):
            return video_path
        if output_path is None:
            output_path = self._get_temp_dir() / f"normalized_{uuid.uuid4().hex[:8]}.mp4"

        resolution = resolution or self.config.output_resolution
        fps = fps or self.config.output_fps
        width, height = resolution

        # Scale and pad to target resolution, then normalize sample aspect ratio
        filter_complex = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )

        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            "-i", str(video_path),
            "-vf", filter_complex,
            "-r", str(fps),
            "-map", "0:v:0?",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            str(output_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to normalize video: {e.stderr.decode()}")

    def render_segment(
        self,
        segment: StorySegment,
        normalize: bool = True,
        voice_over_path: Optional[Path] = None,
    ) -> Path:
        """
        Render a single story segment to a video file.

        Handles video clips and voice over timing.

        Returns:
            Path to the rendered segment video
        """
        # First, create the base video
        if segment.segment_type == SegmentType.VIDEO_CLIP:
            video_path = self.cut_video_segment(segment.content)
        else:
            raise ValueError(f"Unknown segment type: {segment.segment_type}")

        # Normalize if needed
        if normalize:
            video_path = self.normalize_video(video_path)

        # Handle voice over if present
        if segment.voice_over and voice_over_path:
            video_path = self._apply_voice_over(
                video_path,
                segment.voice_over,
                voice_over_path,
                getattr(segment, "vo_timing_strategy", None)
            )

        return video_path

    def _apply_voice_over(
        self,
        video_path: Path,
        voice_over: VoiceOver,
        audio_path: Path,
        timing_strategy: Optional[str] = None
    ) -> Path:
        """
        Apply voice over to a video, handling timing mismatches.
        """
        video_duration = self._get_media_duration(video_path)

        vo_duration = voice_over.duration or 0
        strategy = timing_strategy or self.config.vo_longer_strategy

        if video_duration and vo_duration > video_duration:
            # Voice over is longer than video
            if strategy == "extend_frame":
                extend_by = vo_duration - video_duration + 0.5  # Add small buffer
                video_path = self.extend_last_frame(video_path, extend_by)
            elif strategy == "truncate_audio":
                pass  # Audio will be cut at video end
            # speed_up_audio would require audio processing

        elif video_duration and vo_duration < video_duration:
            # Voice over is shorter (usually okay, audio just ends earlier)
            short_strategy = self.config.vo_shorter_strategy
            if short_strategy == "pad_silence":
                pass  # Default behavior
            # Other strategies could be implemented

        # Overlay the audio
        output_path = self.overlay_audio(
            video_path,
            audio_path,
            replace_original=True,  # Replace for voice overs
            audio_volume=voice_over.volume
        )

        return output_path

    def _has_audio_stream(self, video_path: Path) -> bool:
        """Check whether a video file has an audio stream."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return bool(result.stdout.strip())

    def _has_video_stream(self, video_path: Path) -> bool:
        """Check whether a video file has a video stream."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return bool(result.stdout.strip())

    def _get_media_duration(self, media_path: Path) -> Optional[float]:
        """Return media duration in seconds, or None when unavailable."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=duration",
            "-of", "json",
            str(media_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        try:
            import json
            info = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        duration = info.get("format", {}).get("duration")
        if duration and duration != "N/A":
            return float(duration)
        for stream in info.get("streams", []):
            stream_duration = stream.get("duration")
            if stream_duration and stream_duration != "N/A":
                return float(stream_duration)
        return None

    def _ensure_audio_stream(self, video_path: Path) -> Path:
        """Ensure a video has an audio stream (silence if missing)."""
        if self._has_audio_stream(video_path):
            return video_path

        duration = self._get_media_duration(video_path)
        if not duration:
            return video_path

        output_path = self._get_temp_dir() / f"audio_pad_{uuid.uuid4().hex[:8]}.mp4"
        cmd = [
            "ffmpeg", "-y",
            *self._ffmpeg_thread_args(),
            "-i", str(video_path),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output_path)
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def render_segments(
        self,
        segments: list[StorySegment],
        output_filename: str,
        background_music_path: Optional[Path] = None,
        background_music_volume: float = 0.3,
        voice_over_paths: Optional[dict[str, Path]] = None,
    ) -> RenderResult:
        """Render a list of story segments to a video file."""
        timing_adjustments = []
        rendered_segments = []

        try:
            # Render all segments in parallel
            max_workers = min(4, len(segments))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for i, segment in enumerate(segments):
                    print(f"Rendering segment {i+1}/{len(segments)}...")
                    voice_path = None
                    if voice_over_paths:
                        voice_path = voice_over_paths.get(segment.id)
                    futures[executor.submit(self.render_segment, segment, True, voice_path)] = i
                results: dict[int, Path] = {}
                for future in as_completed(futures):
                    index = futures[future]
                    results[index] = future.result()
                rendered_segments = [results[i] for i in range(len(segments))]
            rendered_segments = [
                self._ensure_audio_stream(path) for path in rendered_segments
            ]

            # Concatenate all segments
            print("Concatenating segments...")
            output_path = self.config.output_dir / output_filename
            final_video = self.concatenate_videos(rendered_segments, output_path)

            # Add background music if specified
            if background_music_path and background_music_path.exists():
                print("Adding background music...")
                final_video = self.overlay_audio(
                    final_video,
                    background_music_path,
                    output_path,
                    replace_original=False,
                    audio_volume=background_music_volume,
                    original_volume=1.0
                )

            # Get final video info
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size",
                "-of", "json",
                str(final_video)
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            import json
            info = json.loads(result.stdout)

            return RenderResult(
                success=True,
                output_path=final_video,
                duration=float(info["format"]["duration"]),
                file_size=int(info["format"]["size"]),
                timing_adjustments=timing_adjustments
            )

        except Exception as e:
            return RenderResult(
                success=False,
                error_message=str(e),
                timing_adjustments=timing_adjustments
            )


    def cleanup(self):
        """Clean up temporary files."""
        if self._temp_dir and self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None


# Convenience functions
def cut_video(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Optional[Path] = None,
    config: Optional[Config] = None
) -> Path:
    """Cut a segment from a video."""
    editor = VideoEditor(config)
    segment = VideoSegment(
        source_video_id="manual",
        start_time=start_time,
        end_time=end_time
    )
    return editor.cut_video_segment(segment, output_path, source_path=video_path)


def join_videos(
    video_paths: list[Path],
    output_path: Optional[Path] = None,
    config: Optional[Config] = None
) -> Path:
    """Join multiple videos into one."""
    editor = VideoEditor(config)
    return editor.concatenate_videos(video_paths, output_path)

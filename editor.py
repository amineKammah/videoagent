"""
Video Editor - Cut, concatenate, and create static scenes.

Uses moviepy for video manipulation with fallback to ffmpeg.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union
import uuid

from config import Config, default_config
from models import (
    VideoSegment,
    StaticScene,
    StorySegment,
    StoryPlan,
    SegmentType,
    RenderResult,
    VoiceOver,
)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


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

    def cut_video_segment(
        self,
        segment: VideoSegment,
        output_path: Optional[Path] = None
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

        # Use ffmpeg for cutting (more reliable than moviepy for seeking)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(segment.source_path),
            "-ss", str(segment.start_time),
            "-t", str(segment.duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
        ]

        # Handle audio volume
        if not segment.keep_original_audio:
            cmd.extend(["-an"])  # No audio
        elif segment.audio_volume != 1.0:
            cmd.extend(["-af", f"volume={segment.audio_volume}"])

        cmd.append(str(output_path))

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to cut video: {e.stderr.decode()}")

    def create_static_scene(
        self,
        scene: StaticScene,
        output_path: Optional[Path] = None,
        resolution: Optional[tuple[int, int]] = None
    ) -> Path:
        """
        Create a static scene with text.

        Args:
            scene: StaticScene defining the content
            output_path: Output path (auto-generated if None)
            resolution: Video resolution (uses config default if None)

        Returns:
            Path to the generated video file
        """
        if output_path is None:
            output_path = self._get_temp_dir() / f"scene_{scene.id}.mp4"

        resolution = resolution or self.config.output_resolution
        width, height = resolution
        fps = self.config.output_fps

        # Try moviepy first (better text rendering)
        try:
            return self._create_static_scene_moviepy(
                scene, output_path, width, height, fps
            )
        except ImportError:
            # Fall back to ffmpeg
            return self._create_static_scene_ffmpeg(
                scene, output_path, width, height, fps
            )

    def _create_static_scene_moviepy(
        self,
        scene: StaticScene,
        output_path: Path,
        width: int,
        height: int,
        fps: int
    ) -> Path:
        """Create static scene using moviepy."""
        from moviepy.editor import (
            ColorClip,
            TextClip,
            CompositeVideoClip,
            ImageClip
        )

        bg_rgb = hex_to_rgb(scene.background_color)

        # Create background
        if scene.background_image_path and scene.background_image_path.exists():
            background = ImageClip(str(scene.background_image_path))
            background = background.resize(newsize=(width, height))
            background = background.set_duration(scene.duration)
        else:
            background = ColorClip(
                size=(width, height),
                color=bg_rgb,
                duration=scene.duration
            )

        # Create main text
        text_color = scene.text_color.lstrip("#")
        main_text = TextClip(
            scene.text,
            fontsize=scene.font_size,
            font=scene.font_family,
            color=text_color,
            method="caption",
            size=(width - 100, None),  # Leave margins
            align="center"
        ).set_duration(scene.duration)

        # Position text
        if scene.text_position == "center":
            main_text = main_text.set_position("center")
        elif scene.text_position == "top":
            main_text = main_text.set_position(("center", 50))
        elif scene.text_position == "bottom":
            main_text = main_text.set_position(("center", height - 150))

        clips = [background, main_text]

        # Add subtitle if present
        if scene.subtitle:
            subtitle = TextClip(
                scene.subtitle,
                fontsize=scene.subtitle_font_size,
                font=scene.font_family,
                color=text_color,
                method="caption",
                size=(width - 100, None),
                align="center"
            ).set_duration(scene.duration)

            # Position subtitle below main text
            subtitle = subtitle.set_position(("center", height // 2 + 80))
            clips.append(subtitle)

        # Composite and render
        final = CompositeVideoClip(clips, size=(width, height))
        final.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio=False,
            logger=None
        )

        return output_path

    def _create_static_scene_ffmpeg(
        self,
        scene: StaticScene,
        output_path: Path,
        width: int,
        height: int,
        fps: int
    ) -> Path:
        """Create static scene using ffmpeg (basic, no fancy text)."""
        bg_color = scene.background_color.lstrip("#")

        # Create a solid color video with text overlay
        # Note: ffmpeg text rendering is basic
        filter_complex = f"color=c=#{bg_color}:s={width}x{height}:d={scene.duration}"

        # Escape text for ffmpeg
        escaped_text = scene.text.replace("'", "'\\''").replace(":", "\\:")

        filter_complex += f",drawtext=text='{escaped_text}'"
        filter_complex += f":fontsize={scene.font_size}"
        filter_complex += f":fontcolor={scene.text_color.lstrip('#')}"
        filter_complex += ":x=(w-text_w)/2:y=(h-text_h)/2"

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", filter_complex,
            "-c:v", "libx264",
            "-t", str(scene.duration),
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create static scene: {e.stderr.decode()}")

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

        # Create concat file for ffmpeg
        concat_file = self._get_temp_dir() / "concat_list.txt"
        with open(concat_file, "w") as f:
            for path in video_paths:
                f.write(f"file '{path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError:
            # If copy fails (different codecs), re-encode
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "fast",
                str(output_path)
            ]
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

        # First, get the video duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        original_duration = float(result.stdout.strip())

        # Extract last frame
        last_frame = self._get_temp_dir() / "last_frame.png"
        cmd = [
            "ffmpeg", "-y",
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
        if output_path is None:
            output_path = self._get_temp_dir() / f"audio_overlay_{uuid.uuid4().hex[:8]}.mp4"

        if replace_original:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-map", "0:v:0",
                "-map", "1:a:0",
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
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
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
        if output_path is None:
            output_path = self._get_temp_dir() / f"normalized_{uuid.uuid4().hex[:8]}.mp4"

        resolution = resolution or self.config.output_resolution
        fps = fps or self.config.output_fps
        width, height = resolution

        # Scale and pad to target resolution
        filter_complex = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", filter_complex,
            "-r", str(fps),
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
        normalize: bool = True
    ) -> Path:
        """
        Render a single story segment to a video file.

        Handles video clips, static scenes, and voice over timing.

        Returns:
            Path to the rendered segment video
        """
        # First, create the base video
        if segment.segment_type == SegmentType.VIDEO_CLIP:
            video_path = self.cut_video_segment(segment.content)
        elif segment.segment_type in (SegmentType.STATIC_SCENE, SegmentType.TRANSITION):
            video_path = self.create_static_scene(segment.content)
        else:
            raise ValueError(f"Unknown segment type: {segment.segment_type}")

        # Normalize if needed
        if normalize:
            video_path = self.normalize_video(video_path)

        # Handle voice over if present
        if segment.voice_over and segment.voice_over.audio_path:
            video_path = self._apply_voice_over(
                video_path,
                segment.voice_over,
                segment.vo_timing_strategy
            )

        return video_path

    def _apply_voice_over(
        self,
        video_path: Path,
        voice_over: VoiceOver,
        timing_strategy: Optional[str] = None
    ) -> Path:
        """
        Apply voice over to a video, handling timing mismatches.
        """
        # Get video duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        video_duration = float(result.stdout.strip())

        vo_duration = voice_over.duration or 0
        strategy = timing_strategy or self.config.vo_longer_strategy

        if vo_duration > video_duration:
            # Voice over is longer than video
            if strategy == "extend_frame":
                extend_by = vo_duration - video_duration + 0.5  # Add small buffer
                video_path = self.extend_last_frame(video_path, extend_by)
            elif strategy == "truncate_audio":
                pass  # Audio will be cut at video end
            # speed_up_audio would require audio processing

        elif vo_duration < video_duration:
            # Voice over is shorter (usually okay, audio just ends earlier)
            short_strategy = self.config.vo_shorter_strategy
            if short_strategy == "pad_silence":
                pass  # Default behavior
            # Other strategies could be implemented

        # Overlay the audio
        output_path = self.overlay_audio(
            video_path,
            voice_over.audio_path,
            replace_original=True,  # Replace for voice overs
            audio_volume=voice_over.volume
        )

        return output_path

    def render_story(self, story: StoryPlan) -> RenderResult:
        """
        Render a complete story plan to a video file.

        Args:
            story: The StoryPlan to render

        Returns:
            RenderResult with output path and metadata
        """
        timing_adjustments = []
        rendered_segments = []

        try:
            # Render all segments
            all_segments = story.get_all_segments()

            for i, segment in enumerate(all_segments):
                print(f"Rendering segment {i+1}/{len(all_segments)}...")
                segment_path = self.render_segment(segment)
                rendered_segments.append(segment_path)

            # Concatenate all segments
            print("Concatenating segments...")
            output_path = self.config.output_dir / story.output_filename
            final_video = self.concatenate_videos(rendered_segments, output_path)

            # Add background music if specified
            if story.background_music_path and story.background_music_path.exists():
                print("Adding background music...")
                final_video = self.overlay_audio(
                    final_video,
                    story.background_music_path,
                    output_path,
                    replace_original=False,
                    audio_volume=story.background_music_volume,
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
        source_path=video_path,
        start_time=start_time,
        end_time=end_time
    )
    return editor.cut_video_segment(segment, output_path)


def create_title_card(
    text: str,
    duration: float = 3.0,
    output_path: Optional[Path] = None,
    config: Optional[Config] = None,
    **kwargs
) -> Path:
    """Create a title card / static scene."""
    editor = VideoEditor(config)
    scene = StaticScene(
        text=text,
        duration=duration,
        **kwargs
    )
    return editor.create_static_scene(scene, output_path)


def join_videos(
    video_paths: list[Path],
    output_path: Optional[Path] = None,
    config: Optional[Config] = None
) -> Path:
    """Join multiple videos into one."""
    editor = VideoEditor(config)
    return editor.concatenate_videos(video_paths, output_path)

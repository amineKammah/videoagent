"""
Voice Over System - TTS generation using Gemini.

Uses Google's Gemini TTS model to generate voice overs.
Handles timing mismatches between voice overs and video segments.
"""
import asyncio
import json
import subprocess
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Optional

from videoagent.config import Config, default_config
from videoagent.gemini import GeminiClient
from videoagent.models import VoiceOver


def wave_file(
    filename: Path,
    pcm: bytes,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2
):
    """Save PCM audio data to a wave file."""
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def get_audio_duration(audio_path: Path) -> float:
    """Get the duration of an audio file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=duration",
        "-of", "json",
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    try:
        info = json.loads(result.stdout)
        duration = info.get("format", {}).get("duration")
        if duration and duration != "N/A":
            return float(duration)
        for stream in info.get("streams", []):
            stream_duration = stream.get("duration")
            if stream_duration and stream_duration != "N/A":
                return float(stream_duration)
    except (ValueError, json.JSONDecodeError, TypeError):
        return 0.0
    return 0.0


def generate_speech_to_file(
    client: GeminiClient,
    text: str,
    output_path: Path,
    voice: str = "Kore",
    ffmpeg_threads: Optional[int] = None
) -> Path:
    """
    Generate audio from text using Gemini TTS and save to file.

    Args:
        client: GeminiClient instance
        text: Text to convert to speech
        output_path: Path to save the audio file
        voice: Voice name (Kore, Charon, Fenrir, Aoede, Puck, etc.)

    Returns:
        Path to the generated audio file
    """
    # Generate PCM audio data
    data = client.generate_speech(text, voice)

    # Save as wave file
    wav_path = output_path.with_suffix(".wav")
    wave_file(wav_path, data)

    # Convert to mp3 if requested
    if output_path.suffix.lower() == ".mp3":
        threads = ffmpeg_threads if ffmpeg_threads is not None else default_config.ffmpeg_threads
        cmd = [
            "ffmpeg", "-y",
            "-threads", str(threads),
            "-i", str(wav_path),
            "-codec:a", "libmp3lame",
            "-qscale:a", "2",
            str(output_path)
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        wav_path.unlink()  # Remove temp wav
        return output_path

    return wav_path


async def generate_speech_to_file_async(
    client: GeminiClient,
    text: str,
    output_path: Path,
    voice: str = "Kore",
    ffmpeg_threads: Optional[int] = None
) -> Path:
    """Generate audio from text using Gemini TTS and save to file (async)."""
    data = await client.generate_speech_async(text, voice)

    wav_path = output_path.with_suffix(".wav")
    await asyncio.to_thread(wave_file, wav_path, data)

    if output_path.suffix.lower() == ".mp3":
        threads = ffmpeg_threads if ffmpeg_threads is not None else default_config.ffmpeg_threads
        cmd = [
            "ffmpeg", "-y",
            "-threads", str(threads),
            "-i", str(wav_path),
            "-codec:a", "libmp3lame",
            "-qscale:a", "2",
            str(output_path)
        ]
        await asyncio.to_thread(subprocess.run, cmd, capture_output=True, check=True)
        wav_path.unlink()
        return output_path

    return wav_path


class VoiceOverGenerator:
    """Generates voice overs from scripts using Gemini TTS."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self._temp_dir = None
        self.client = GeminiClient(config)

    def _get_temp_dir(self) -> Path:
        """Get or create temporary directory."""
        if self._temp_dir is None:
            self._temp_dir = Path(tempfile.mkdtemp(prefix="voice_over_"))
        return self._temp_dir

    def generate_voice_over(
        self,
        script: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        output_path: Optional[Path] = None
    ) -> VoiceOver:
        """
        Generate a voice over from a script.

        Args:
            script: The text to convert to speech
            voice: Voice name (Kore, Charon, Fenrir, Aoede, Puck, etc.)
            speed: Speech speed multiplier (not used with Gemini TTS)
            output_path: Output audio path

        Returns:
            VoiceOver object with duration
        """
        voice = voice or self.config.tts_voice

        if output_path is None:
            output_path = self._get_temp_dir() / f"vo_{uuid.uuid4().hex[:8]}.wav"

        # Generate the audio
        audio_path = generate_speech_to_file(
            self.client,
            script,
            output_path,
            voice,
            ffmpeg_threads=self.config.ffmpeg_threads
        )

        # Get duration
        duration = get_audio_duration(audio_path)

        audio_id = None
        if output_path:
            name = output_path.name
            if name.startswith("vo_") and name.endswith(".wav"):
                audio_id = name[len("vo_") : -len(".wav")]
        return VoiceOver(
            script=script,
            audio_id=audio_id,
            duration=duration,
        )

    async def generate_voice_over_async(
        self,
        script: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        output_path: Optional[Path] = None
    ) -> VoiceOver:
        """Generate a voice over from a script (async)."""
        voice = voice or self.config.tts_voice

        if output_path is None:
            output_path = self._get_temp_dir() / f"vo_{uuid.uuid4().hex[:8]}.wav"

        audio_path = await generate_speech_to_file_async(
            self.client,
            script,
            output_path,
            voice,
            ffmpeg_threads=self.config.ffmpeg_threads
        )

        duration = await asyncio.to_thread(get_audio_duration, audio_path)

        audio_id = None
        if output_path:
            name = output_path.name
            if name.startswith("vo_") and name.endswith(".wav"):
                audio_id = name[len("vo_") : -len(".wav")]
        return VoiceOver(
            script=script,
            audio_id=audio_id,
            duration=duration,
        )

    async def generate_voice_overs_parallel(
        self,
        script_voice_pairs: list[tuple[str, str]],
        max_concurrency: int = 4,
    ) -> list[VoiceOver]:
        """Generate multiple voice overs concurrently (async)."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run(script: str, voice: str) -> VoiceOver:
            async with semaphore:
                return await self.generate_voice_over_async(script, voice=voice)

        return await asyncio.gather(*[
            _run(script, voice) for script, voice in script_voice_pairs
        ])

    def generate_for_segment_duration(
        self,
        script: str,
        target_duration: float,
        voice: Optional[str] = None,
        tolerance: float = 0.5
    ) -> VoiceOver:
        """
        Generate a voice over for a target duration.

        Note: Gemini TTS doesn't support speed adjustment, so this just
        generates at normal speed. Use video timing adjustment to handle
        duration mismatches.

        Args:
            script: The text to convert
            target_duration: Target duration in seconds
            voice: Voice to use
            tolerance: Acceptable deviation from target (seconds)

        Returns:
            VoiceOver object
        """
        return self.generate_voice_over(script, voice)

    def cleanup(self):
        """Clean up temporary files."""
        if self._temp_dir and self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None


# Convenience functions
def generate_voice_over(
    script: str,
    voice: Optional[str] = None,
    speed: float = 1.0,
    output_path: Optional[Path] = None,
    config: Optional[Config] = None
) -> VoiceOver:
    """Generate a voice over from a script."""
    generator = VoiceOverGenerator(config)
    return generator.generate_voice_over(script, voice, speed, output_path)


def estimate_speech_duration(
    text: str,
    words_per_minute: float = 150
) -> float:
    """
    Estimate how long it will take to speak text.

    Args:
        text: The text to estimate
        words_per_minute: Speaking rate (default 150 wpm for clear narration)

    Returns:
        Estimated duration in seconds
    """
    word_count = len(text.split())
    return (word_count / words_per_minute) * 60

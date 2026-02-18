"""ElevenLabs v3 voiceover generation from final rendered text."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import requests
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from videoagent.config import Config, default_config
from videoagent.models import VoiceOver
from videoagent.voice import get_audio_duration, wave_file


DEFAULT_ELEVENLABS_MODEL_ID = "eleven_v3"
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
_ELEVENLABS_RETRY_MAX_ATTEMPTS = 5
_ELEVENLABS_RETRY_MIN_DELAY_SECONDS = 1.0
_ELEVENLABS_RETRY_MAX_DELAY_SECONDS = 16.0


class ElevenLabsRateLimitError(RuntimeError):
    """Raised when ElevenLabs responds with HTTP 429."""

    def __init__(self, *, status_code: int, model_id: str, error_text: str):
        self.status_code = status_code
        self.model_id = model_id
        self.error_text = error_text
        super().__init__(
            f"ElevenLabs TTS failed ({status_code}) using model '{model_id}': {error_text}"
        )


def _truncate_error_text(raw_error_text: str, max_length: int = 500) -> str:
    error_text = (raw_error_text or "").strip()
    if len(error_text) > max_length:
        return error_text[:max_length] + "..."
    return error_text


def _is_retryable_elevenlabs_rate_limit_error(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) == 429


class VoiceOverV3Generator:
    """Generate voiceovers for ElevenLabs v3."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self._retry_sleep: Callable[[float], None] = time.sleep

    async def generate_voice_over_async(
        self,
        rendered_text: str,
        output_path: Path,
        *,
        elevenlabs_model_id: Optional[str] = None,
        rendered_text_output_path: Optional[Path] = None,
        voice_id: Optional[str] = None,
    ) -> VoiceOver:
        resolved_model_id = self._resolve_elevenlabs_model_id(elevenlabs_model_id)
        final_text = (rendered_text or "").strip()
        if not final_text:
            raise ValueError("Rendered voiceover text is required for ElevenLabs synthesis.")

        print(
            "[voiceover_v3] start "
            f"model_id={resolved_model_id} "
            f"text_chars={len(final_text)} "
            f"output_path={output_path}"
        )

        # Canonicalize common audio-tag misspellings/variants before synthesis.
        final_text = self._normalize_audio_tags(final_text)

        if rendered_text_output_path is not None:
            rendered_text_output_path.parent.mkdir(parents=True, exist_ok=True)
            rendered_text_output_path.write_text(final_text, encoding="utf-8")

        audio_path = await self._synthesize_text_to_wav_async(
            text=final_text,
            output_path=output_path,
            model_id=resolved_model_id,
            voice_id=voice_id,
        )
        duration = await asyncio.to_thread(get_audio_duration, audio_path)

        audio_id = None
        name = audio_path.name
        if name.startswith("vo_") and name.endswith(".wav"):
            audio_id = name[len("vo_") : -len(".wav")]
        if not audio_id:
            audio_id = uuid.uuid4().hex[:8]

        return VoiceOver(
            script=final_text,
            audio_id=audio_id,
            duration=duration,
            audio_path=str(audio_path),
        )

    async def _synthesize_text_to_wav_async(
        self,
        *,
        text: str,
        output_path: Path,
        model_id: str,
        voice_id: Optional[str] = None,
    ) -> Path:
        return await asyncio.to_thread(
            self._synthesize_text_to_wav,
            text,
            output_path,
            model_id,
            voice_id,
        )

    def _synthesize_text_to_wav(
        self,
        text: str,
        output_path: Path,
        model_id: str,
        voice_id: Optional[str] = None,
    ) -> Path:
        api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is missing. Add it to your environment before running generate_voiceover_v3."
            )

        base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1").rstrip("/")
        resolved_voice_id = voice_id or DEFAULT_ELEVENLABS_VOICE_ID
        url = f"{base_url}/text-to-speech/{resolved_voice_id}"
        print(
            "[voiceover_v3] text sent to ElevenLabs "
            f"(model_id={model_id}, voice_id={resolved_voice_id}):\n{text}"
        )

        def _post_tts_request() -> requests.Response:
            response = requests.post(
                url,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/octet-stream",
                },
                params={"output_format": "pcm_24000"},
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        # 0.5 = Natural. v3 accepts 0.0 / 0.5 / 1.0 only.
                        "stability": 0.5,
                        "style": 0.0,
                        "similarity_boost": 0.75,
                        "use_speaker_boost": True,
                        "speed": 1.0,
                    },
                },
                timeout=(15, 180),
            )

            if response.status_code >= 400:
                error_text = _truncate_error_text(response.text or "")
                if response.status_code == 429:
                    raise ElevenLabsRateLimitError(
                        status_code=response.status_code,
                        model_id=model_id,
                        error_text=error_text,
                    )
                raise RuntimeError(
                    f"ElevenLabs TTS failed ({response.status_code}) using model '{model_id}': {error_text}"
                )
            return response

        response: Optional[requests.Response] = None
        for attempt in Retrying(
            retry=retry_if_exception(_is_retryable_elevenlabs_rate_limit_error),
            stop=stop_after_attempt(_ELEVENLABS_RETRY_MAX_ATTEMPTS),
            wait=wait_exponential(
                multiplier=1,
                min=_ELEVENLABS_RETRY_MIN_DELAY_SECONDS,
                max=_ELEVENLABS_RETRY_MAX_DELAY_SECONDS,
            ),
            reraise=True,
            before_sleep=self._log_retry_before_sleep,
            sleep=self._retry_sleep,
        ):
            with attempt:
                response = _post_tts_request()

        if response is None:
            raise RuntimeError("ElevenLabs TTS request did not return a response.")

        pcm_audio = response.content
        if not pcm_audio:
            raise RuntimeError("ElevenLabs TTS returned an empty audio payload.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wave_file(output_path, pcm_audio, channels=1, rate=24000, sample_width=2)
        return output_path

    @staticmethod
    def _log_retry_before_sleep(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if exc is None:
            return
        wait_seconds = retry_state.next_action.sleep if retry_state.next_action else 0.0
        print(
            "[voiceover_v3] ElevenLabs rate-limited "
            f"(attempt {retry_state.attempt_number}/{_ELEVENLABS_RETRY_MAX_ATTEMPTS}): {exc}. "
            f"Retrying in {wait_seconds:.1f}s."
        )

    def _resolve_elevenlabs_model_id(self, elevenlabs_model_id: Optional[str]) -> str:
        resolved = (
            (elevenlabs_model_id or "").strip()
            or os.getenv("ELEVENLABS_MODEL_ID", "").strip()
            or DEFAULT_ELEVENLABS_MODEL_ID
        )
        if not resolved.lower().startswith("eleven_v3"):
            raise ValueError(
                f"voiceover_v3 is v3-only. Received model '{resolved}'. "
                "Use eleven_v3 or a future eleven_v3 variant."
            )
        return resolved

    @staticmethod
    def _normalize_audio_tags(text: str) -> str:
        normalized = text

        # Whisper variants/misspellings -> canonical v3 whisper tag.
        whisper_patterns = [
            r"\[\s*whiper\s*\]",
            r"\[\s*whipers\s*\]",
            r"\[\s*whisper\s*\]",
            r"\[\s*whispering\s*\]",
        ]
        for pattern in whisper_patterns:
            normalized = re.sub(pattern, "[whispers]", normalized, flags=re.IGNORECASE)

        # Normalize pause variant names to canonical forms.
        normalized = re.sub(r"\[\s*small pause\s*\]", "[short pause]", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\[\s*brief pause\s*\]", "[short pause]", normalized, flags=re.IGNORECASE)

        # Collapse excessive whitespace while keeping line breaks meaningful.
        normalized = re.sub(r"[ \t]+", " ", normalized).strip()
        return normalized

    def cleanup(self) -> None:
        """Compatibility hook with the original generator lifecycle."""
        return None

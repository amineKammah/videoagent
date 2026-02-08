"""
Voiceover generation pipeline with optional LLM enhancement.

Workflow:
- If notes are provided, generate enhanced SSML with Gemini.
- If notes are absent, send script directly to ElevenLabs.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from pydantic import BaseModel, Field


from videoagent.config import Config, default_config
from videoagent.gemini import GeminiClient
from videoagent.models import VoiceOver
from videoagent.voice import get_audio_duration, wave_file


DEFAULT_ELEVENLABS_MODEL_ID = "eleven_turbo_v2"
DEFAULT_SSML_MODEL_ID = "gemini-3-flash-preview"
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"


@dataclass(frozen=True)
class PronunciationGuidance:
    word: str
    phonetic_spelling: str


class _EnhancedTextResponse(BaseModel):
    enhanced_text: str = Field(min_length=1)


class VoiceOverV2Generator:
    """Generate voiceovers through Gemini SSML drafting and ElevenLabs synthesis."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self.gemini_client = GeminiClient(self.config)

    async def generate_voice_over_async(
        self,
        script: str,
        output_path: Path,
        *,
        notes: Optional[str] = None,
        pronunciations: Optional[list[PronunciationGuidance]] = None,
        elevenlabs_model_id: Optional[str] = None,
        ssml_model: Optional[str] = None,
        ssml_output_path: Optional[Path] = None,
    ) -> VoiceOver:
        note_text = (notes or "").strip()
        if note_text:
            ssml = await self._generate_ssml_async(
                script=script,
                notes=note_text,
                pronunciations=pronunciations or [],
                ssml_model=ssml_model,
            )
        else:
            ssml = script
        if ssml_output_path is not None:
            ssml_output_path.parent.mkdir(parents=True, exist_ok=True)
            ssml_output_path.write_text(ssml, encoding="utf-8")
        audio_path = await self._synthesize_ssml_to_wav_async(
            ssml=ssml,
            output_path=output_path,
            elevenlabs_model_id=elevenlabs_model_id,
        )
        duration = await asyncio.to_thread(get_audio_duration, audio_path)

        audio_id = None
        name = audio_path.name
        if name.startswith("vo_") and name.endswith(".wav"):
            audio_id = name[len("vo_") : -len(".wav")]
        if not audio_id:
            audio_id = uuid.uuid4().hex[:8]

        return VoiceOver(
            script=script,
            audio_id=audio_id,
            duration=duration,
            audio_path=str(audio_path),
        )

    async def _generate_ssml_async(
        self,
        *,
        script: str,
        notes: Optional[str],
        pronunciations: list[PronunciationGuidance],
        ssml_model: Optional[str],
    ) -> str:
        model_name = (
            (ssml_model or "").strip()
            or os.getenv("VOICEOVER_SSML_MODEL", "").strip()
            or self.config.gemini_model
            or DEFAULT_SSML_MODEL_ID
        )

        prompt = self._build_ssml_prompt(
            script=script,
            notes=notes,
            pronunciations=pronunciations,
        )

        response = await asyncio.to_thread(
            lambda: self.gemini_client.generate_content(
                model=model_name,
                contents=[prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": _EnhancedTextResponse,
                },
            )
        )

        if not isinstance(response.parsed, _EnhancedTextResponse):
            raise ValueError("Gemini enhancer did not return the expected structured response.")

        return response.parsed.enhanced_text

    def _build_ssml_prompt(
        self,
        *,
        script: str,
        notes: Optional[str],
        pronunciations: list[PronunciationGuidance],
    ) -> str:
        pronunciation_payload = [
            {
                "word": item.word,
                "phonetic_spelling": item.phonetic_spelling,
            }
            for item in pronunciations
        ]

        notes_text = (notes or "").strip() or "(none)"

        return f"""
You enhance narration scripts for ElevenLabs.

Return JSON only with this schema:
{{"enhanced_text": "..."}}

Hard requirements:
- You may use ElevenLabs-supported inline controls listed below. Do not invent other tags.
- SSML tags:
  - `<break time="..."/>`
  - `<phoneme alphabet="ipa|cmu-arpabet" ph="...">word</phoneme>`
- Eleven v3 audio tags:
  - Pause: `[pause]`, `[short pause]`, `[long pause]`
  - Voice-related: `[laughs]`, `[laughs harder]`, `[starts laughing]`, `[wheezing]`, `[whispers]`,
    `[shouts]`, `[sighs]`, `[exhales]`, `[clears throat]`, `[sarcastic]`, `[curious]`, `[excited]`,
    `[crying]`, `[snorts]`, `[mischievously]`
  - Sound effects: `[gunshot]`, `[applause]`, `[clapping]`, `[explosion]`, `[swallows]`, `[gulps]`
  - Special: `[strong X accent]`, `[sings]`, `[woo]`, `[fart]`
- Keep the original words and sentence order unless pronunciation fixing requires tag wrapping.
- Apply every pronunciation entry provided below.
- Apply style notes if provided.
- Keep narration length similar; do not add new sentences.
- Avoid markdown, code fences, and explanations.

Script:
{script}

Direction notes:
{notes_text}

Pronunciations (already resolved):
{json.dumps(pronunciation_payload, ensure_ascii=True)}
""".strip()

    async def _synthesize_ssml_to_wav_async(
        self,
        *,
        ssml: str,
        output_path: Path,
        elevenlabs_model_id: Optional[str],
    ) -> Path:
        return await asyncio.to_thread(
            self._synthesize_ssml_to_wav,
            ssml,
            output_path,
            elevenlabs_model_id,
        )

    def _synthesize_ssml_to_wav(
        self,
        ssml: str,
        output_path: Path,
        elevenlabs_model_id: Optional[str],
    ) -> Path:
        api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is missing. Add it to your environment before running generate_voiceover_v2."
            )

        resolved_voice_id = DEFAULT_ELEVENLABS_VOICE_ID
        model_id = (
            (elevenlabs_model_id or "").strip()
            or os.getenv("ELEVENLABS_MODEL_ID", "").strip()
            or DEFAULT_ELEVENLABS_MODEL_ID
        )

        base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1").rstrip("/")
        url = f"{base_url}/text-to-speech/{resolved_voice_id}"

        response = requests.post(
            url,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/octet-stream",
            },
            params={"output_format": "pcm_24000"},
            json={
                "text": ssml,
                "model_id": model_id,
            },
            timeout=(15, 180),
        )

        if response.status_code >= 400:
            error_text = (response.text or "").strip()
            if len(error_text) > 500:
                error_text = error_text[:500] + "..."
            raise RuntimeError(
                f"ElevenLabs TTS failed ({response.status_code}) using model '{model_id}': {error_text}"
            )

        pcm_audio = response.content
        if not pcm_audio:
            raise RuntimeError("ElevenLabs TTS returned an empty audio payload.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wave_file(output_path, pcm_audio, channels=1, rate=24000, sample_width=2)
        return output_path

    def cleanup(self) -> None:
        """Compatibility hook with the original generator lifecycle."""
        return None

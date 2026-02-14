"""
ElevenLabs v3 voiceover generation with optional LLM enhancement.

Workflow:
- If notes are provided, Gemini enhances text with v3 tags.
- If notes are absent, raw script is sent directly to ElevenLabs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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


DEFAULT_ELEVENLABS_MODEL_ID = "eleven_v3"
DEFAULT_ENHANCER_MODEL_ID = "gemini-3-flash-preview"
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"


@dataclass(frozen=True)
class PronunciationGuidance:
    word: str
    phonetic_spelling: str


class _EnhancedTextResponse(BaseModel):
    enhanced_text: str = Field(min_length=1)


class VoiceOverV3Generator:
    """Generate voiceovers for ElevenLabs v3."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config

    async def generate_voice_over_async(
        self,
        script: str,
        output_path: Path,
        *,
        notes: Optional[str] = None,
        pronunciations: Optional[list[PronunciationGuidance]] = None,
        elevenlabs_model_id: Optional[str] = None,
        enhancer_model: Optional[str] = None,
        enhanced_text_output_path: Optional[Path] = None,
        voice_id: Optional[str] = None,
    ) -> VoiceOver:
        resolved_model_id = self._resolve_elevenlabs_model_id(elevenlabs_model_id)
        resolved_pronunciations = [
            PronunciationGuidance(
                word=item.word.strip(),
                phonetic_spelling=item.phonetic_spelling.strip(),
            )
            for item in (pronunciations or [])
            if item.word.strip() and item.phonetic_spelling.strip()
        ]

        note_text = (notes or "").strip()
        print(
            "[voiceover_v3] start "
            f"model_id={resolved_model_id} "
            f"notes_present={bool(note_text)} "
            f"pronunciations={len(resolved_pronunciations)} "
            f"output_path={output_path}"
        )
        if note_text:
            print("[voiceover_v3] Gemini enhancer branch: running")
            final_text = await self._generate_enhanced_text_async(
                script=script,
                notes=note_text,
                pronunciations=resolved_pronunciations,
                enhancer_model=enhancer_model,
                target_model_id=resolved_model_id,
            )
        else:
            print("[voiceover_v3] Gemini enhancer branch: skipped (no notes)")
            final_text = script

        # Apply resolved pronunciations before synthesis in both branches.
        final_text = self._apply_resolved_pronunciations(final_text, resolved_pronunciations)

        # Canonicalize common audio-tag misspellings/variants before synthesis.
        final_text = self._normalize_audio_tags(final_text)

        if enhanced_text_output_path is not None:
            enhanced_text_output_path.parent.mkdir(parents=True, exist_ok=True)
            enhanced_text_output_path.write_text(final_text, encoding="utf-8")

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
            script=script,
            audio_id=audio_id,
            duration=duration,
            audio_path=str(audio_path),
        )

    async def _generate_enhanced_text_async(
        self,
        *,
        script: str,
        notes: str,
        pronunciations: list[PronunciationGuidance],
        enhancer_model: Optional[str],
        target_model_id: str,
    ) -> str:
        model_name = (
            (enhancer_model or "").strip()
            or os.getenv("VOICEOVER_ENHANCER_MODEL", "").strip()
            or self.config.gemini_model
            or DEFAULT_ENHANCER_MODEL_ID
        )
        print(f"[voiceover_v3] Gemini enhancer model={model_name}")

        prompt = self._build_enhancer_prompt(
            script=script,
            notes=notes,
            pronunciations=pronunciations,
            target_model_id=target_model_id,
        )

        def _call_enhancer(client: GeminiClient):
            return client.generate_content(
                model=model_name,
                contents=[prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": _EnhancedTextResponse,
                },
            )

        # Use a fresh enhancer client per call to avoid shared-client lifecycle races
        # when multiple scene notes are enhanced concurrently.
        enhancer_client = GeminiClient(self.config)
        try:
            response = await asyncio.to_thread(_call_enhancer, enhancer_client)
        except Exception as exc:
            if not self._is_closed_client_error(exc):
                raise
            print("[voiceover_v3] Gemini enhancer client was closed; retrying with fresh client")
            # Retry once with a new client if the underlying HTTP client was closed.
            retry_client = GeminiClient(self.config)
            response = await asyncio.to_thread(_call_enhancer, retry_client)

        if not isinstance(response.parsed, _EnhancedTextResponse):
            raise ValueError("Gemini enhancer did not return the expected structured response.")

        return response.parsed.enhanced_text

    @staticmethod
    def _is_closed_client_error(error: Exception) -> bool:
        message = str(error).strip().lower()
        return "client has been closed" in message

    def _build_enhancer_prompt(
        self,
        *,
        script: str,
        notes: str,
        pronunciations: list[PronunciationGuidance],
        target_model_id: str,
    ) -> str:
        pronunciation_payload = [
            {
                "word": item.word,
                "phonetic_spelling": item.phonetic_spelling,
            }
            for item in pronunciations
        ]

        return f"""
You enhance narration scripts for ElevenLabs v3.

Return JSON only with this schema:
{{"enhanced_text": "..."}}

Hard requirements:
- Target ElevenLabs model: `{target_model_id}`.
- Use only ElevenLabs v3 inline audio tags listed below.
  - Pause: `[pause]`, `[short pause]`, `[long pause]`
  - Voice-related: `[laughs]`, `[laughs harder]`, `[starts laughing]`, `[wheezing]`, `[whispers]`,
    `[shouts]`, `[sighs]`, `[exhales]`, `[clears throat]`, `[sarcastic]`, `[curious]`, `[excited]`,
    `[crying]`, `[snorts]`, `[mischievously]`
  - Sound effects: `[gunshot]`, `[applause]`, `[clapping]`, `[explosion]`, `[swallows]`, `[gulps]`
  - Special: `[strong X accent]`, `[sings]`, `[woo]`, `[fart]`
- Use `[whispers]` as the canonical whisper tag.
- Do NOT use `[whiper]`, `[whipers]`, `[whispering]`, or `[whisper]`.
- Do not output SSML/XML tags like `<speak>`, `<break>`, or `<phoneme>`.
- Keep original facts and sentence order; do not add claims.
- Apply notes naturally.
- Keep output compact and directly synthesizable.
- Pronunciations are handled separately; keep original word spellings.
- Avoid markdown, code fences, and explanations.

Script:
{script}

Direction notes:
{notes}

Pronunciation hints (read-only context):
{json.dumps(pronunciation_payload, ensure_ascii=True)}
""".strip()

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

    @staticmethod
    def _apply_resolved_pronunciations(
        text: str,
        pronunciations: list[PronunciationGuidance],
    ) -> str:
        if not pronunciations:
            return text

        # Avoid touching bracket tags like [whispers] while replacing spoken text.
        segments = re.split(r"(\[[^\]]+\])", text)
        ordered = sorted(pronunciations, key=lambda item: len(item.word), reverse=True)

        for index, segment in enumerate(segments):
            if not segment or (segment.startswith("[") and segment.endswith("]")):
                continue

            updated = segment
            for item in ordered:
                pattern = re.compile(
                    rf"(?<![A-Za-z0-9_]){re.escape(item.word)}(?![A-Za-z0-9_])",
                    flags=re.IGNORECASE,
                )
                updated = pattern.sub(item.phonetic_spelling, updated)
            segments[index] = updated

        return "".join(segments)

    def cleanup(self) -> None:
        """Compatibility hook with the original generator lifecycle."""
        return None

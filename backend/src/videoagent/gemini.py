"""
Gemini Client - Shared client for Gemini API.

Provides a centralized client for both video analysis and TTS.
"""
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel

from videoagent.config import Config, default_config

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    """
    Shared Gemini client for video analysis and TTS.

    Uses the google.genai SDK.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self._client = None

    def _get_client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            try:
                from google import genai
                try:
                    from dotenv import load_dotenv
                except ImportError:
                    load_dotenv = None

                if load_dotenv:
                    # Try repo root first, then cwd for local runs
                    repo_env = Path(__file__).resolve().parents[3] / ".env"
                    if repo_env.exists():
                        load_dotenv(dotenv_path=repo_env)
                    else:
                        load_dotenv(dotenv_path=Path(".env"))

                api_key = self.config.gemini_api_key
                if not api_key:
                    import os
                    api_key = os.environ.get("GEMINI_API_KEY")

                import os
                adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

                if adc_path:
                    # Prefer service account/ADC when explicitly provided
                    from google.auth import default as google_auth_default
                    credentials, project = google_auth_default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    project_env = (
                        os.environ.get("GOOGLE_CLOUD_PROJECT")
                        or os.environ.get("CLOUDSDK_CORE_PROJECT")
                    )
                    project = project or project_env
                    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1"
                    if not project:
                        raise ValueError(
                            "Google Cloud project not found. Set GOOGLE_CLOUD_PROJECT "
                            "or CLOUDSDK_CORE_PROJECT when using ADC."
                        )
                    self._client = genai.Client(
                        vertexai=True,
                        project=project,
                        location=location,
                        credentials=credentials,
                    )
                elif api_key:
                    self._client = genai.Client(api_key=api_key)
                else:
                    # Fall back to ADC (gcloud auth application-default login)
                    from google.auth import default as google_auth_default
                    credentials, project = google_auth_default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    project_env = (
                        os.environ.get("GOOGLE_CLOUD_PROJECT")
                        or os.environ.get("CLOUDSDK_CORE_PROJECT")
                    )
                    project = project or project_env
                    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1"
                    if not project:
                        raise ValueError(
                            "Google Cloud project not found. Set GOOGLE_CLOUD_PROJECT "
                            "or CLOUDSDK_CORE_PROJECT when using ADC."
                        )
                    self._client = genai.Client(
                        vertexai=True,
                        project=project,
                        location=location,
                        credentials=credentials,
                    )
            except ImportError:
                raise RuntimeError(
                    "google-genai not installed. "
                    "Install with: pip install google-genai"
                )
        return self._client

    @property
    def client(self):
        """Get the underlying genai client."""
        return self._get_client()

    def upload_file(self, file_path: Path) -> object:
        """Upload a file to Gemini."""
        return self.client.files.upload(file=str(file_path))

    def generate_content(
        self,
        model: str,
        contents: list,
        config: Optional[dict] = None
    ):
        """
        Generate content using Gemini.

        Args:
            model: Model name
            contents: Content to send (can include files and text)
            config: Generation config

        Returns:
            Response object
        """
        return self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

    def analyze_video(
        self,
        video_file: object,
        prompt: str,
        response_model: type[T],
        max_tokens: int = 1000
    ) -> T:
        """
        Analyze a video with structured output.

        Args:
            video_file: Uploaded file object
            prompt: The prompt
            response_model: Pydantic model for response
            max_tokens: Max output tokens

        Returns:
            Parsed Pydantic model instance
        """
        response = self.generate_content(
            model=self.config.gemini_model,
            contents=[video_file, prompt],
            config={
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
                "response_json_schema": response_model.model_json_schema(),
            }
        )
        return response_model.model_validate_json(response.text)

    def generate_speech(
        self,
        text: str,
        voice: str = "Kore"
    ) -> bytes:
        """
        Generate speech audio using Gemini TTS.

        Args:
            text: Text to convert to speech
            voice: Voice name (Kore, Charon, Fenrir, Aoede, Puck, etc.)

        Returns:
            PCM audio data as bytes
        """
        from google.genai import types

        response = self.generate_content(
            model=self.config.gemini_tts_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    )
                ),
            )
        )

        return response.candidates[0].content.parts[0].inline_data.data

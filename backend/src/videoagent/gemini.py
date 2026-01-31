"""
Gemini Client - Shared client for Gemini API.

Provides a centralized client for both video analysis and TTS.
"""
import asyncio
import hashlib
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel

from videoagent.config import Config, default_config

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    """
    Shared Gemini client for video analysis and TTS.

    Uses the google.genai SDK with API key auth only.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config
        self._content_client = None
        self._tts_client = None
        self._cache_db_path = self._default_cache_db_path()
        self._init_cache_db()

    def _load_dotenv(self) -> None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            return

        # Try repo root first, then cwd for local runs
        repo_env = Path(__file__).resolve().parents[3] / ".env"
        if repo_env.exists():
            load_dotenv(dotenv_path=repo_env)
        else:
            load_dotenv(dotenv_path=Path(".env"))

    def _create_client(self, vertexai: bool = False):
        """Create a Gemini API clien."""
        try:
            from google import genai
            self._load_dotenv()
            if vertexai:
                api_key = os.getenv("VERTEX_API_KEY")
            else:
                api_key = os.getenv("GEMINI_API_KEY")
            print("DEBUGINFO\n\n\n\n", api_key, vertexai)
            return genai.Client(
                vertexai=vertexai,
                api_key=api_key,
            )

        except ImportError:
            raise RuntimeError(
                "google-genai not installed. "
                "Install with: pip install google-genai"
            )

    def _default_cache_db_path(self) -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        cache_dir = repo_root / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "gemini_files.db"

    def _init_cache_db(self) -> None:
        with sqlite3.connect(self._cache_db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gemini_file_cache (
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    gemini_file_name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    PRIMARY KEY (file_path, file_hash)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gemini_file_cache_path "
                "ON gemini_file_cache (file_path)"
            )

    def _compute_file_hash(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _load_cached_file(self, file_path: Path, file_hash: str) -> Optional[object]:
        resolved = str(file_path.resolve())
        stats = file_path.stat()
        with sqlite3.connect(self._cache_db_path) as conn:
            row = conn.execute(
                """
                SELECT gemini_file_name, file_size, mtime
                FROM gemini_file_cache
                WHERE file_path = ? AND file_hash = ?
                """,
                (resolved, file_hash),
            ).fetchone()
        if not row:
            return None
        gemini_file_name, cached_size, cached_mtime = row
        if cached_size != stats.st_size or cached_mtime != stats.st_mtime:
            return None
        try:
            file_obj = self._get_content_client().files.get(name=gemini_file_name)
        except Exception:
            return None
        try:
            return self._wait_for_file_active(file_obj)
        except Exception:
            return None

    def _store_cached_file(
        self,
        file_path: Path,
        gemini_file_name: str,
        file_hash: str,
    ) -> None:
        resolved = str(file_path.resolve())
        stats = file_path.stat()
        now = time.time()
        with sqlite3.connect(self._cache_db_path) as conn:
            conn.execute(
                """
                INSERT INTO gemini_file_cache (
                    file_path, file_hash, file_size, mtime,
                    gemini_file_name, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path, file_hash) DO UPDATE SET
                    file_size=excluded.file_size,
                    mtime=excluded.mtime,
                    gemini_file_name=excluded.gemini_file_name,
                    last_used_at=excluded.last_used_at
                """,
                (
                    resolved,
                    file_hash,
                    stats.st_size,
                    stats.st_mtime,
                    gemini_file_name,
                    now,
                    now,
                ),
            )

    def _touch_cached_file(self, file_path: Path, file_hash: str) -> None:
        resolved = str(file_path.resolve())
        with sqlite3.connect(self._cache_db_path) as conn:
            conn.execute(
                """
                UPDATE gemini_file_cache
                SET last_used_at = ?
                WHERE file_path = ? AND file_hash = ?
                """,
                (time.time(), resolved, file_hash),
            )

    def _get_content_client(self):
        if self._content_client is None:
            self._content_client = self._create_client()
        return self._content_client

    def _get_tts_client(self):
        if self._tts_client is None:
            self._tts_client = self._create_client(vertexai=True)
        return self._tts_client

    @property
    def client(self):
        """Get the underlying genai client."""
        return self._get_content_client()

    def _upload_file(self, file_path: Path) -> object:
        """Upload a file using the Gemini File API."""
        upload_path = self._prepare_upload_path(file_path)
        try:
            uploaded = self._get_content_client().files.upload(file=str(upload_path))
            return self._wait_for_file_active(uploaded)
        finally:
            if upload_path != file_path and upload_path.exists():
                upload_path.unlink()

    def _prepare_upload_path(self, file_path: Path) -> Path:
        """Ensure the uploaded filename is ASCII-safe for HTTP headers."""
        try:
            file_path.name.encode("ascii")
            return file_path
        except UnicodeEncodeError:
            suffix = file_path.suffix if file_path.suffix else ".bin"
            tmp = tempfile.NamedTemporaryFile(prefix="gemini_upload_", suffix=suffix, delete=False)
            tmp_path = Path(tmp.name)
            tmp.close()
            tmp_path.write_bytes(file_path.read_bytes())
            return tmp_path

    def _wait_for_file_active(
        self,
        file_obj: object,
        timeout_seconds: int = 1200,
        poll_interval: float = 1.0,
    ) -> object:
        file_name = getattr(file_obj, "name", None) or getattr(file_obj, "id", None)
        if not file_name:
            return file_obj
        deadline = time.monotonic() + timeout_seconds
        current = file_obj
        while time.monotonic() < deadline:
            state = self._state_name(getattr(current, "state", None))
            if self._is_file_active(state):
                return current
            if self._is_file_failed(state):
                raise RuntimeError(
                    f"Uploaded file {file_name} failed with state {state}."
                )
            time.sleep(poll_interval)
            try:
                current = self._get_content_client().files.get(name=file_name)
            except Exception:
                current = self._get_content_client().files.get(file_name)
        raise RuntimeError(
            f"Uploaded file {file_name} did not become ACTIVE in time."
        )

    @staticmethod
    def _state_name(state: object) -> Optional[str]:
        if state is None:
            return None
        if isinstance(state, str):
            return state
        state_name = getattr(state, "name", None)
        if isinstance(state_name, str):
            return state_name
        state_value = getattr(state, "value", None)
        if isinstance(state_value, str):
            return state_value
        return None

    @staticmethod
    def _is_file_active(state: Optional[str]) -> bool:
        return bool(state and state.upper() == "ACTIVE")

    @staticmethod
    def _is_file_failed(state: Optional[str]) -> bool:
        if not state:
            return False
        return state.upper() in {"FAILED", "ERROR", "CANCELED"}

    def upload_file(self, file_path: Path) -> object:
        """Public wrapper for file uploads."""
        return self._upload_file(file_path)

    def get_or_upload_file(self, file_path: Path) -> object:
        """Return cached Gemini file if possible, otherwise upload and cache it."""
        file_hash = self._compute_file_hash(file_path)
        cached = self._load_cached_file(file_path, file_hash)
        if cached is not None:
            self._touch_cached_file(file_path, file_hash)
            return cached
        uploaded = self._upload_file(file_path)
        file_name = getattr(uploaded, "name", None) or getattr(uploaded, "id", None)
        if file_name:
            self._store_cached_file(file_path, file_name, file_hash)
        return uploaded

    def generate_content(
        self,
        model: str,
        contents: list,
        config: Optional[dict] = None,
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
        return self._get_content_client().models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    async def generate_contents_parallel(
        self,
        model: str,
        contents_list: list,
        config: Optional[dict] = None,
        max_concurrency: int = 8,
    ) -> list:
        """Generate multiple contents concurrently using the async client."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run(contents):
            async with semaphore:
                return await self._get_content_client().aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )

        return await asyncio.gather(*[_run(contents) for contents in contents_list])


    async def generate_speech_async(
        self,
        text: str,
        voice: str = "Kore",
    ) -> bytes:
        """Generate speech audio using Gemini TTS (async)."""
        from google.genai import types

        response = await self._get_tts_client().aio.models.generate_content(
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
            ),
        )

        if not response.candidates:
            raise ValueError("Gemini TTS returned no candidates. Check safety settings or prompt.")
        
        return response.candidates[0].content.parts[0].inline_data.data

    async def generate_speeches_parallel(
        self,
        text_voice_pairs: list[tuple[str, str]],
        max_concurrency: int = 8,
    ) -> list[bytes]:
        """Generate multiple TTS outputs concurrently using the async client."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run(text: str, voice: str) -> bytes:
            async with semaphore:
                return await self.generate_speech_async(text, voice)

        return await asyncio.gather(*[
            _run(text, voice) for text, voice in text_voice_pairs
        ])

    def generate_speech(
        self,
        text: str,
        voice: str = "Kore",
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

        response = self._get_tts_client().models.generate_content(
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
            ),
        )

        if not response.candidates:
            raise ValueError("Gemini TTS returned no candidates. Check safety settings or prompt.")

        return response.candidates[0].content.parts[0].inline_data.data

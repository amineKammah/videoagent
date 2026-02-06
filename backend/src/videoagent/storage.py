"""Google Cloud Storage utilities for VideoAgent (GCS-only)."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Generator, Optional, Union

try:
    from google.cloud import storage
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "google-cloud-storage is required. Install with: pip install google-cloud-storage"
    ) from exc

from videoagent.gcp import build_storage_client_kwargs


PathLike = Union[str, Path]


class GCSStorageClient:
    """Storage client for Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str,
        signed_url_ttl_seconds: int = 600,
        expected_location: Optional[str] = None,
    ):
        bucket = (bucket_name or "").strip()
        if not bucket:
            raise ValueError("GCS bucket name is required.")

        # Force project/credentials from env to avoid silently using local gcloud login.
        self.client = storage.Client(**build_storage_client_kwargs())
        self.bucket = self.client.bucket(bucket)
        self.bucket.reload()
        self.bucket_location = (self.bucket.location or "").lower()
        if expected_location:
            expected = expected_location.lower()
            if self.bucket_location and self.bucket_location != expected:
                raise RuntimeError(
                    f"GCS bucket '{bucket}' is in '{self.bucket.location}', expected '{expected_location}'. "
                    "Use a London bucket (europe-west2) or adjust GCS_BUCKET_LOCATION."
                )
        self.signed_url_ttl_seconds = max(1, int(signed_url_ttl_seconds))

    @property
    def bucket_name(self) -> str:
        return self.bucket.name

    def to_gs_uri(self, path: str) -> str:
        blob_path = self._normalize_blob_path(path)
        return f"gs://{self.bucket.name}/{blob_path}"

    def _normalize_blob_path(self, path: PathLike) -> str:
        raw = str(path).strip()
        if not raw:
            raise ValueError("Path is required.")

        if raw.startswith("gs://"):
            without_scheme = raw[len("gs://") :]
            bucket_name, sep, blob_path = without_scheme.partition("/")
            if not sep or not blob_path:
                raise ValueError(f"Invalid GCS URI: {raw}")
            if bucket_name != self.bucket.name:
                raise ValueError(
                    f"Path bucket '{bucket_name}' does not match configured bucket '{self.bucket.name}'."
                )
            return blob_path.lstrip("/")

        return raw.lstrip("/")

    def list_files(self, prefix: str, recursive: bool = True) -> Generator[str, None, None]:
        """List blob paths under prefix."""
        normalized_prefix = self._normalize_blob_path(prefix) if prefix else ""
        delimiter = None if recursive else "/"
        blobs = self.client.list_blobs(
            self.bucket,
            prefix=normalized_prefix,
            delimiter=delimiter,
        )
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            yield blob.name

    def exists(self, path: PathLike) -> bool:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        return blob.exists()

    def download_to_filename(self, path: PathLike, destination: PathLike) -> None:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(destination_path))

    def upload_from_filename(
        self,
        path: PathLike,
        source: PathLike,
        content_type: Optional[str] = None,
    ) -> None:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        blob.upload_from_filename(str(source), content_type=content_type)

    def get_url(
        self,
        path: PathLike,
        expiration_seconds: Optional[int] = None,
        method: str = "GET",
    ) -> str:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        ttl = self.signed_url_ttl_seconds if expiration_seconds is None else max(1, int(expiration_seconds))
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl),
            method=method,
        )

    def get_metadata(self, path: PathLike) -> dict[str, Any]:
        blob_path = self._normalize_blob_path(path)
        blob = self.bucket.get_blob(blob_path)
        if not blob:
            raise FileNotFoundError(f"File not found in GCS: {path}")

        return {
            "size": blob.size,
            "updated": blob.updated.isoformat() if blob.updated else None,
            "generation": str(blob.generation) if blob.generation is not None else None,
            "content_type": blob.content_type,
            "path": self.to_gs_uri(blob_path),
            "blob_path": blob_path,
            "metadata": blob.metadata or {},
        }

    def read_text(self, path: PathLike, encoding: str = "utf-8") -> str:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        return blob.download_as_text(encoding=encoding)

    def write_text(
        self,
        path: PathLike,
        content: str,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        blob = self.bucket.blob(self._normalize_blob_path(path))
        blob.upload_from_string(content, content_type=content_type)

    def read_json(self, path: PathLike) -> dict[str, Any]:
        text = self.read_text(path)
        return json.loads(text)

    def write_json(
        self,
        path: PathLike,
        payload: dict[str, Any],
        indent: Optional[int] = 2,
    ) -> None:
        content = json.dumps(payload, indent=indent)
        self.write_text(path, content, content_type="application/json")


_STORAGE_CLIENT: Optional[GCSStorageClient] = None
_STORAGE_CACHE_KEY: Optional[tuple[str, int, Optional[str]]] = None


def get_storage_client(config=None) -> GCSStorageClient:
    """Return singleton GCS storage client configured via env vars."""
    global _STORAGE_CLIENT, _STORAGE_CACHE_KEY

    bucket_name = (os.environ.get("GCS_BUCKET_NAME") or "").strip()
    if not bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME must be set.")

    ttl_raw = os.environ.get("SIGNED_URL_TTL_SECONDS", "600")
    try:
        ttl = max(1, int(ttl_raw))
    except ValueError:
        ttl = 600

    expected_location = (os.environ.get("GCS_BUCKET_LOCATION", "europe-west2") or "").strip() or None

    cache_key = (bucket_name, ttl, expected_location)
    if _STORAGE_CLIENT is None or _STORAGE_CACHE_KEY != cache_key:
        _STORAGE_CLIENT = GCSStorageClient(
            bucket_name=bucket_name,
            signed_url_ttl_seconds=ttl,
            expected_location=expected_location,
        )
        _STORAGE_CACHE_KEY = cache_key

    return _STORAGE_CLIENT

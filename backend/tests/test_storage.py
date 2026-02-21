from __future__ import annotations

from types import SimpleNamespace

import pytest

from videoagent import storage as storage_module


@pytest.fixture(autouse=True)
def _reset_storage_singletons():
    storage_module._STORAGE_CLIENT = None
    storage_module._STORAGE_CACHE_KEY = None
    yield
    storage_module._STORAGE_CLIENT = None
    storage_module._STORAGE_CACHE_KEY = None


def _install_fake_google_client(monkeypatch: pytest.MonkeyPatch, *, bucket_location: str = "europe-west2"):
    class FakeBucket:
        def __init__(self, name: str):
            self.name = name
            self.location = bucket_location

        def reload(self) -> None:
            return None

        def blob(self, _name: str):
            return SimpleNamespace()

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def bucket(self, name: str):
            return FakeBucket(name)

    monkeypatch.setattr(storage_module.storage, "Client", FakeClient)


def test_normalize_blob_path_accepts_bucket_uri(monkeypatch: pytest.MonkeyPatch):
    _install_fake_google_client(monkeypatch)
    client = storage_module.GCSStorageClient(bucket_name="bink_video_storage_alpha")

    assert client._normalize_blob_path("companies/acme/videos/a.mp4") == "companies/acme/videos/a.mp4"
    assert (
        client._normalize_blob_path("gs://bink_video_storage_alpha/companies/acme/videos/a.mp4")
        == "companies/acme/videos/a.mp4"
    )
    assert client.to_gs_uri("companies/acme/videos/a.mp4") == "gs://bink_video_storage_alpha/companies/acme/videos/a.mp4"


def test_normalize_blob_path_accepts_legacy_bucket_aliases(monkeypatch: pytest.MonkeyPatch):
    _install_fake_google_client(monkeypatch)
    client = storage_module.GCSStorageClient(bucket_name="bink_video_storage_alpha")

    assert (
        client._normalize_blob_path("gs://videoagent_assets/companies/acme/videos/a.mp4")
        == "companies/acme/videos/a.mp4"
    )
    assert (
        client._normalize_blob_path("gs://videoagent-assets/companies/acme/videos/a.mp4")
        == "companies/acme/videos/a.mp4"
    )


def test_normalize_blob_path_rejects_other_bucket(monkeypatch: pytest.MonkeyPatch):
    _install_fake_google_client(monkeypatch)
    client = storage_module.GCSStorageClient(bucket_name="bink_video_storage_alpha")

    with pytest.raises(ValueError, match="does not match configured bucket"):
        client._normalize_blob_path("gs://wrong-bucket/companies/acme/videos/a.mp4")


def test_bucket_location_guard_raises_for_non_london_bucket(monkeypatch: pytest.MonkeyPatch):
    _install_fake_google_client(monkeypatch, bucket_location="EU")

    with pytest.raises(RuntimeError, match="Use a London bucket"):
        storage_module.GCSStorageClient(
            bucket_name="bink_video_storage_alpha",
            expected_location="europe-west2",
        )


def test_get_storage_client_caches_and_rebuilds_on_env_change(monkeypatch: pytest.MonkeyPatch):
    created: list[tuple[str, int, str | None]] = []

    class FakeGCSStorageClient:
        def __init__(
            self,
            *,
            bucket_name: str,
            signed_url_ttl_seconds: int,
            expected_location: str | None,
        ):
            created.append((bucket_name, signed_url_ttl_seconds, expected_location))

    monkeypatch.setattr(storage_module, "GCSStorageClient", FakeGCSStorageClient)
    monkeypatch.setenv("GCS_BUCKET_NAME", "bink_video_storage_alpha")
    monkeypatch.setenv("SIGNED_URL_TTL_SECONDS", "900")
    monkeypatch.setenv("GCS_BUCKET_LOCATION", "europe-west2")

    first = storage_module.get_storage_client()
    second = storage_module.get_storage_client()

    assert first is second
    assert created == [("bink_video_storage_alpha", 900, "europe-west2")]

    # Invalid TTL falls back to default (600) and rebuilds because cache key changes.
    monkeypatch.setenv("SIGNED_URL_TTL_SECONDS", "not-a-number")
    third = storage_module.get_storage_client()
    assert third is not first
    assert created[-1] == ("bink_video_storage_alpha", 600, "europe-west2")


def test_get_storage_client_requires_bucket_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)

    with pytest.raises(RuntimeError, match="GCS_BUCKET_NAME must be set"):
        storage_module.get_storage_client()

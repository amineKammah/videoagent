"""Shared helpers for resolving GCP project/location/credentials from env."""

from __future__ import annotations

import os
from typing import Any, Optional, Sequence

from videoagent.config import Config

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def get_gcp_project(config: Optional[Config] = None) -> Optional[str]:
    """Resolve GCP project with env-first precedence."""
    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUDSDK_CORE_PROJECT")
        or (config.gcp_project_id if config else None)
        or ""
    ).strip()
    return project or None


def get_gcp_location(config: Optional[Config] = None) -> Optional[str]:
    """Resolve GCP location with env-first precedence."""
    location = (
        os.environ.get("GOOGLE_CLOUD_LOCATION")
        or (config.gcp_location if config else None)
        or "europe-west2"
    ).strip()
    return location or None


def get_service_account_credentials(scopes: Optional[Sequence[str]] = None):
    """Load service account credentials from GOOGLE_APPLICATION_CREDENTIALS."""
    credentials_path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not credentials_path:
        return None
    try:
        from google.oauth2 import service_account
    except ImportError:
        return None
    credentials = service_account.Credentials.from_service_account_file(credentials_path)
    if scopes:
        credentials = credentials.with_scopes(list(scopes))
    return credentials


def build_storage_client_kwargs(config: Optional[Config] = None) -> dict[str, Any]:
    """Build kwargs for google.cloud.storage.Client."""
    credentials = get_service_account_credentials()
    project = get_gcp_project(config)
    if not project and credentials is not None:
        project = getattr(credentials, "project_id", None)
    return {
        "project": project,
        "credentials": credentials,
    }


def build_vertex_client_kwargs(config: Optional[Config] = None) -> dict[str, Any]:
    """Build kwargs for google.genai.Client using Vertex AI."""
    kwargs: dict[str, Any] = {"vertexai": True}
    # vertex_api_key = (os.environ.get("VERTEX_API_KEY") or "").strip()
    # if vertex_api_key:
    #     # Vertex API key mode must not include project/location/credentials.
    #     kwargs["api_key"] = vertex_api_key
    #     return kwargs

    credentials = get_service_account_credentials(scopes=[CLOUD_PLATFORM_SCOPE])
    if credentials is not None:
        kwargs["credentials"] = credentials
    project = get_gcp_project(config)
    if not project and credentials is not None:
        project = getattr(credentials, "project_id", None)
    if project:
        kwargs["project"] = project
    kwargs["location"] = "global"
    return kwargs

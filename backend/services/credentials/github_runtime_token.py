"""Resolve GitHub bearer tokens from stored credential secrets with optional OAuth refresh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.credentials.github_oauth_client import (
    GitHubOAuthClientError,
    GitHubOAuthTokenBundle,
    refresh_github_access_token,
    resolve_github_oauth_client_config,
)

TOKEN_REFRESH_SKEW_SECONDS = 60
PROVIDER_KIND = "github"


class GitHubRuntimeTokenError(ValueError):
    """Deterministic GitHub runtime token resolution failure."""


@dataclass(slots=True)
class GitHubRuntimeTokenResolution:
    access_token: str
    updated_secret: str | None = None


def is_github_oauth_secret(secret_value: str) -> bool:
    stripped = secret_value.strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("provider_kind") == PROVIDER_KIND:
        return True
    return False


def serialize_github_oauth_secret(*, bundle: GitHubOAuthTokenBundle) -> str:
    document = {
        "provider_kind": PROVIDER_KIND,
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
        "scopes": list(bundle.scopes),
        "token_type": bundle.token_type,
    }
    return json.dumps(document, sort_keys=True)


def resolve_github_credential_secret(
    secret_value: str,
    *,
    auto_refresh: bool = True,
    redirect_uri: str = "http://localhost:5173/credentials/github/callback",
) -> GitHubRuntimeTokenResolution:
    stripped = secret_value.strip()
    if not stripped:
        raise GitHubRuntimeTokenError("github credential secret is empty")

    if not is_github_oauth_secret(stripped):
        return GitHubRuntimeTokenResolution(access_token=stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GitHubRuntimeTokenError("github oauth secret must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubRuntimeTokenError("github oauth secret must be a JSON object")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GitHubRuntimeTokenError("github oauth secret missing access_token")

    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not auto_refresh or not isinstance(refresh_token, str) or not refresh_token.strip():
        return GitHubRuntimeTokenResolution(access_token=access_token.strip())

    if not _token_expired(expires_at):
        return GitHubRuntimeTokenResolution(access_token=access_token.strip())

    try:
        client = resolve_github_oauth_client_config(redirect_uri=redirect_uri)
    except GitHubOAuthClientError as exc:
        raise GitHubRuntimeTokenError(
            "github access token expired and GitHub OAuth client is not configured for refresh"
        ) from exc

    try:
        refreshed = refresh_github_access_token(client=client, refresh_token=refresh_token)
    except GitHubOAuthClientError as exc:
        raise GitHubRuntimeTokenError(f"github token refresh failed: {exc}") from exc

    merged = GitHubOAuthTokenBundle(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or refresh_token.strip(),
        expires_at=refreshed.expires_at,
        scopes=refreshed.scopes,
        token_type=refreshed.token_type,
    )
    return GitHubRuntimeTokenResolution(
        access_token=merged.access_token,
        updated_secret=serialize_github_oauth_secret(bundle=merged),
    )


def _token_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, str) or not expires_at.strip():
        return True
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(tz=UTC) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)

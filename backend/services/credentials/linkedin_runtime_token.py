"""Resolve LinkedIn bearer tokens from stored credential secrets with optional OAuth refresh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.credentials.linkedin_oauth_client import (
    LinkedInOAuthClientError,
    LinkedInOAuthTokenBundle,
    refresh_linkedin_access_token,
    resolve_linkedin_oauth_client_config,
)

TOKEN_REFRESH_SKEW_SECONDS = 60
PROVIDER_KIND = "linkedin"


class LinkedInRuntimeTokenError(ValueError):
    """Deterministic LinkedIn runtime token resolution failure."""


@dataclass(slots=True)
class LinkedInRuntimeTokenResolution:
    access_token: str
    updated_secret: str | None = None


def _has_explicit_linkedin_shape(payload: dict[str, Any]) -> bool:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not (
        isinstance(access_token, str)
        and access_token.strip()
        and isinstance(refresh_token, str)
        and refresh_token.strip()
        and isinstance(expires_at, str)
        and expires_at.strip()
    ):
        return False
    scopes = payload.get("scopes")
    if isinstance(scopes, list):
        scope_text = " ".join(str(item) for item in scopes).lower()
        if any(marker in scope_text for marker in ("openid", "profile", "email", "w_member")):
            return True
    return True


def is_linkedin_oauth_secret(secret_value: str) -> bool:
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
    other_provider_kind = payload.get("provider_kind")
    if isinstance(other_provider_kind, str) and other_provider_kind.strip():
        return False
    if isinstance(payload.get("instance_url"), str):
        return False
    return _has_explicit_linkedin_shape(payload)


def serialize_linkedin_oauth_secret(*, bundle: LinkedInOAuthTokenBundle) -> str:
    document = {
        "provider_kind": PROVIDER_KIND,
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
        "scopes": list(bundle.scopes),
        "token_type": bundle.token_type,
    }
    return json.dumps(document, sort_keys=True)


def resolve_linkedin_credential_secret(
    secret_value: str,
    *,
    auto_refresh: bool = True,
    redirect_uri: str = "http://localhost:5173/credentials/linkedin/callback",
) -> LinkedInRuntimeTokenResolution:
    stripped = secret_value.strip()
    if not stripped:
        raise LinkedInRuntimeTokenError("linkedin credential secret is empty")

    if not is_linkedin_oauth_secret(stripped):
        return LinkedInRuntimeTokenResolution(access_token=stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LinkedInRuntimeTokenError("linkedin oauth secret must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise LinkedInRuntimeTokenError("linkedin oauth secret must be a JSON object")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise LinkedInRuntimeTokenError("linkedin oauth secret missing access_token")

    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not auto_refresh or not isinstance(refresh_token, str) or not refresh_token.strip():
        return LinkedInRuntimeTokenResolution(access_token=access_token.strip())

    if not _token_expired(expires_at):
        return LinkedInRuntimeTokenResolution(access_token=access_token.strip())

    try:
        client = resolve_linkedin_oauth_client_config(redirect_uri=redirect_uri)
    except LinkedInOAuthClientError as exc:
        raise LinkedInRuntimeTokenError(
            "linkedin access token expired and LinkedIn OAuth client is not configured for refresh"
        ) from exc

    try:
        refreshed = refresh_linkedin_access_token(client=client, refresh_token=refresh_token)
    except LinkedInOAuthClientError as exc:
        raise LinkedInRuntimeTokenError(f"linkedin token refresh failed: {exc}") from exc

    merged = LinkedInOAuthTokenBundle(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or refresh_token.strip(),
        expires_at=refreshed.expires_at,
        scopes=refreshed.scopes,
        token_type=refreshed.token_type,
    )
    return LinkedInRuntimeTokenResolution(
        access_token=merged.access_token,
        updated_secret=serialize_linkedin_oauth_secret(bundle=merged),
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

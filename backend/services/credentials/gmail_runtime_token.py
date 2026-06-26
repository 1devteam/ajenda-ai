"""Resolve Gmail bearer tokens from stored credential secrets with optional OAuth refresh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.services.tools.gmail_provider import required_gmail_scopes
from backend.services.tools.google_oauth_cli import (
    GoogleOAuthCliError,
    GoogleOAuthTokenBundle,
    refresh_access_token,
    resolve_google_oauth_client_config,
)

TOKEN_REFRESH_SKEW_SECONDS = 60


class GmailRuntimeTokenError(ValueError):
    """Deterministic Gmail runtime token resolution failure."""


@dataclass(slots=True)
class GmailRuntimeTokenResolution:
    access_token: str
    updated_secret: str | None = None


def is_gmail_oauth_secret(secret_value: str) -> bool:
    stripped = secret_value.strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and (
        isinstance(payload.get("access_token"), str) or isinstance(payload.get("refresh_token"), str)
    )


def serialize_gmail_oauth_secret(*, bundle: GoogleOAuthTokenBundle) -> str:
    document = {
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
        "scopes": list(bundle.scopes or required_gmail_scopes()),
        "token_type": bundle.token_type,
    }
    return json.dumps(document, sort_keys=True)


def resolve_gmail_credential_secret(
    secret_value: str,
    *,
    auto_refresh: bool = True,
) -> GmailRuntimeTokenResolution:
    """Return a bearer token for Gmail API calls.

    Plain bearer strings pass through unchanged. JSON OAuth bundles may refresh
    when ``auto_refresh`` is true and Google client credentials are configured.
    """

    stripped = secret_value.strip()
    if not stripped:
        raise GmailRuntimeTokenError("gmail credential secret is empty")

    if not is_gmail_oauth_secret(stripped):
        return GmailRuntimeTokenResolution(access_token=stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GmailRuntimeTokenError("gmail oauth secret must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise GmailRuntimeTokenError("gmail oauth secret must be a JSON object")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GmailRuntimeTokenError("gmail oauth secret missing access_token")

    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not auto_refresh or not isinstance(refresh_token, str) or not refresh_token.strip():
        return GmailRuntimeTokenResolution(access_token=access_token.strip())

    if not _token_expired(expires_at):
        return GmailRuntimeTokenResolution(access_token=access_token.strip())

    try:
        client = resolve_google_oauth_client_config()
    except GoogleOAuthCliError as exc:
        raise GmailRuntimeTokenError(
            "gmail access token expired and Google OAuth client is not configured for refresh"
        ) from exc

    try:
        refreshed = refresh_access_token(client=client, refresh_token=refresh_token)
    except GoogleOAuthCliError as exc:
        raise GmailRuntimeTokenError(f"gmail token refresh failed: {exc}") from exc

    merged = GoogleOAuthTokenBundle(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or refresh_token.strip(),
        expires_at=refreshed.expires_at,
        scopes=refreshed.scopes or tuple(required_gmail_scopes()),
        token_type=refreshed.token_type,
    )
    updated_secret = serialize_gmail_oauth_secret(bundle=merged)
    return GmailRuntimeTokenResolution(access_token=merged.access_token, updated_secret=updated_secret)


def _token_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, str) or not expires_at.strip():
        return True
    from datetime import UTC, datetime, timedelta

    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(tz=UTC) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)
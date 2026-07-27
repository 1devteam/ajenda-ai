"""Resolve Google Contacts bearer tokens from stored credential secrets with optional OAuth refresh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.tools.google_contacts_provider import (
    recognized_google_contacts_scopes,
    required_google_contacts_scopes,
)
from backend.services.tools.google_oauth_cli import (
    GoogleOAuthCliError,
    GoogleOAuthTokenBundle,
    refresh_access_token,
    resolve_google_oauth_client_config,
)

TOKEN_REFRESH_SKEW_SECONDS = 60
PROVIDER_KIND = "google_contacts"


class GoogleContactsRuntimeTokenError(ValueError):
    """Deterministic Google Contacts runtime token resolution failure."""


@dataclass(slots=True)
class GoogleContactsRuntimeTokenResolution:
    access_token: str
    updated_secret: str | None = None


def is_google_contacts_oauth_secret(secret_value: str) -> bool:
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
    scopes = payload.get("scopes")
    if isinstance(scopes, list):
        known = recognized_google_contacts_scopes()
        if any(any(scope in str(item) for scope in known) for item in scopes):
            return True
    return False


def serialize_google_contacts_oauth_secret(*, bundle: GoogleOAuthTokenBundle) -> str:
    document = {
        "provider_kind": PROVIDER_KIND,
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
        "scopes": list(bundle.scopes or required_google_contacts_scopes(write=True)),
        "token_type": bundle.token_type,
    }
    return json.dumps(document, sort_keys=True)


def resolve_google_contacts_credential_secret(
    secret_value: str,
    *,
    auto_refresh: bool = True,
    redirect_uri: str = "http://localhost:5173/credentials/google-contacts/callback",
) -> GoogleContactsRuntimeTokenResolution:
    stripped = secret_value.strip()
    if not stripped:
        raise GoogleContactsRuntimeTokenError("google contacts credential secret is empty")

    if not is_google_contacts_oauth_secret(stripped) and not stripped.startswith("{"):
        return GoogleContactsRuntimeTokenResolution(access_token=stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GoogleContactsRuntimeTokenError("google contacts oauth secret must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise GoogleContactsRuntimeTokenError("google contacts oauth secret must be a JSON object")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GoogleContactsRuntimeTokenError("google contacts oauth secret missing access_token")

    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not auto_refresh or not isinstance(refresh_token, str) or not refresh_token.strip():
        return GoogleContactsRuntimeTokenResolution(access_token=access_token.strip())

    if not _token_expired(expires_at):
        return GoogleContactsRuntimeTokenResolution(access_token=access_token.strip())

    try:
        client = resolve_google_oauth_client_config()
        client = type(client)(
            client_id=client.client_id,
            client_secret=client.client_secret,
            redirect_uri=redirect_uri.strip() or client.redirect_uri,
        )
    except GoogleOAuthCliError as exc:
        raise GoogleContactsRuntimeTokenError(
            "google contacts access token expired and Google OAuth client is not configured for refresh"
        ) from exc

    try:
        refreshed = refresh_access_token(client=client, refresh_token=refresh_token)
    except GoogleOAuthCliError as exc:
        raise GoogleContactsRuntimeTokenError(f"google contacts token refresh failed: {exc}") from exc

    merged = GoogleOAuthTokenBundle(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or refresh_token.strip(),
        expires_at=refreshed.expires_at,
        scopes=refreshed.scopes or tuple(required_google_contacts_scopes(write=True)),
        token_type=refreshed.token_type,
    )
    return GoogleContactsRuntimeTokenResolution(
        access_token=merged.access_token,
        updated_secret=serialize_google_contacts_oauth_secret(bundle=merged),
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

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from backend.services.credentials.gmail_runtime_token import (
    GmailRuntimeTokenError,
    is_gmail_oauth_secret,
    resolve_gmail_credential_secret,
    serialize_gmail_oauth_secret,
)
from backend.services.tools.google_oauth_cli import GoogleOAuthTokenBundle


def test_plain_bearer_secret_passes_through() -> None:
    resolution = resolve_gmail_credential_secret("plain-bearer-token", auto_refresh=False)
    assert resolution.access_token == "plain-bearer-token"
    assert resolution.updated_secret is None


def test_is_gmail_oauth_secret_detects_json_bundle() -> None:
    payload = json.dumps({"access_token": "a", "refresh_token": "r"})
    assert is_gmail_oauth_secret(payload) is True
    assert is_gmail_oauth_secret("bearer-only") is False


def test_expired_oauth_secret_refreshes_and_returns_updated_secret() -> None:
    expired_at = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    secret = json.dumps(
        {
            "access_token": "stale-access",
            "refresh_token": "refresh-123",
            "expires_at": expired_at,
        }
    )
    refreshed = GoogleOAuthTokenBundle(
        access_token="fresh-access",
        refresh_token="refresh-123",
        expires_at=(datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
        scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        token_type="Bearer",
    )
    with patch(
        "backend.services.credentials.gmail_runtime_token.refresh_access_token",
        return_value=refreshed,
    ):
        with patch(
            "backend.services.credentials.gmail_runtime_token.resolve_google_oauth_client_config",
            return_value=object(),
        ):
            resolution = resolve_gmail_credential_secret(secret, auto_refresh=True)

    assert resolution.access_token == "fresh-access"
    assert resolution.updated_secret is not None
    updated_payload = json.loads(resolution.updated_secret)
    assert updated_payload["access_token"] == "fresh-access"


def test_missing_access_token_raises() -> None:
    with pytest.raises(GmailRuntimeTokenError, match="access_token"):
        resolve_gmail_credential_secret(json.dumps({"refresh_token": "only-refresh"}))


def test_serialize_round_trip() -> None:
    bundle = GoogleOAuthTokenBundle(
        access_token="access",
        refresh_token="refresh",
        expires_at="2026-06-25T12:00:00+00:00",
        scopes=("https://www.googleapis.com/auth/gmail.send",),
        token_type="Bearer",
    )
    serialized = serialize_gmail_oauth_secret(bundle=bundle)
    assert json.loads(serialized)["access_token"] == "access"

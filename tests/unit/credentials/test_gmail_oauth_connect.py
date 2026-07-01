from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.credentials.gmail_oauth_connect import (
    GmailOAuthConnectError,
    exchange_gmail_oauth_code,
    issue_gmail_oauth_authorization,
    verify_gmail_oauth_state,
)
from backend.services.tools.google_oauth_cli import GoogleOAuthTokenBundle


def test_issue_gmail_oauth_authorization_returns_signed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "google-client-secret")

    result = issue_gmail_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="gmail-email",
        actor_id="human:test@example.com",
    )

    assert result.authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state=" in result.authorization_url
    claims = verify_gmail_oauth_state(result.state)
    assert claims.tenant_id == "tenant-1"
    assert claims.credential_id == "gmail-email"
    assert claims.actor_id == "human:test@example.com"
    assert claims.provider == "gmail"


def test_exchange_gmail_oauth_code_serializes_provider_kind_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "google-client-secret")

    issued = issue_gmail_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="gmail-email",
        actor_id="human:test@example.com",
    )

    bundle = GoogleOAuthTokenBundle(
        access_token="gmail-access",
        refresh_token="gmail-refresh",
        expires_at="2026-06-25T12:00:00+00:00",
        scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        token_type="Bearer",
    )
    monkeypatch.setattr(
        "backend.services.credentials.gmail_oauth_connect.exchange_authorization_code",
        lambda **kwargs: bundle,
    )

    secret_value = exchange_gmail_oauth_code(code="auth-code", state=issued.state)

    assert '"provider_kind": "gmail"' in secret_value
    assert '"access_token": "gmail-access"' in secret_value


def test_verify_gmail_oauth_state_rejects_wrong_provider() -> None:
    from backend.services.credentials.oauth_state import sign_oauth_state

    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "gmail-email",
            "actor_id": "human:test@example.com",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "linkedin",
        }
    )
    with pytest.raises(GmailOAuthConnectError, match="provider mismatch"):
        verify_gmail_oauth_state(state)
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.credentials.google_contacts_oauth_connect import (
    GoogleContactsOAuthConnectError,
    exchange_google_contacts_oauth_code,
    issue_google_contacts_oauth_authorization,
    verify_google_contacts_oauth_state,
)
from backend.services.tools.gmail_provider import GOOGLE_OAUTH_TOKEN_URL
from backend.services.tools.google_contacts_provider import GOOGLE_CONTACTS_SCOPE


def test_issue_google_contacts_oauth_authorization_returns_signed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "google-client-secret")

    result = issue_google_contacts_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="google-contacts-read",
        actor_id="human:test@example.com",
    )

    assert result.authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    from urllib.parse import unquote

    decoded = unquote(result.authorization_url)
    assert "https://www.googleapis.com/auth/contacts" in decoded
    assert "contacts.other.readonly" in decoded
    assert "select_account" in result.authorization_url
    assert "openid" not in result.authorization_url  # identity scopes belong to login, not connectors
    claims = verify_google_contacts_oauth_state(result.state)
    assert claims.tenant_id == "tenant-1"
    assert claims.provider == "google_contacts"


def test_exchange_google_contacts_oauth_code_serializes_provider_kind_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "google-client-secret")

    issued = issue_google_contacts_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="google-contacts-read",
        actor_id="human:test@example.com",
    )

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "contacts-access",
                "refresh_token": "contacts-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": GOOGLE_CONTACTS_SCOPE,
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr("backend.services.tools.google_oauth_cli.httpx.Client", lambda **kwargs: fake_client)

    secret_value = exchange_google_contacts_oauth_code(code="auth-code", state=issued.state)

    assert '"provider_kind": "google_contacts"' in secret_value
    assert '"access_token": "contacts-access"' in secret_value
    fake_client.post.assert_called_once()
    assert fake_client.post.call_args.args[0] == GOOGLE_OAUTH_TOKEN_URL


def test_verify_google_contacts_oauth_state_rejects_wrong_provider() -> None:
    from backend.services.credentials.oauth_state import sign_oauth_state

    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "google-contacts-read",
            "actor_id": "human:test@example.com",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "gmail",
        }
    )
    with pytest.raises(GoogleContactsOAuthConnectError, match="provider mismatch"):
        verify_google_contacts_oauth_state(state)

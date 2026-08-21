from __future__ import annotations

from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest

from backend.services.credentials.google_docs_oauth_connect import (
    GoogleDocsOAuthConnectError,
    exchange_google_docs_oauth_code,
    issue_google_docs_oauth_authorization,
    verify_google_docs_oauth_state,
)
from backend.services.tools.gmail_provider import GOOGLE_OAUTH_TOKEN_URL
from backend.services.tools.google_docs_provider import GOOGLE_DOCS_READONLY_SCOPE


def _configure_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CONNECTOR_CLIENT_ID", "connector-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CONNECTOR_CLIENT_SECRET", "connector-client-secret")


def test_docs_authorization_is_independent_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_google(monkeypatch)
    result = issue_google_docs_oauth_authorization(
        tenant_id="tenant-1", credential_id="google-docs", actor_id="user:member-1"
    )
    assert GOOGLE_DOCS_READONLY_SCOPE in unquote(result.authorization_url)
    assert "select_account" in result.authorization_url
    assert "openid" not in result.authorization_url
    assert verify_google_docs_oauth_state(result.state).provider == "google_docs"


def test_docs_exchange_serializes_registration_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_google(monkeypatch)
    issued = issue_google_docs_oauth_authorization(
        tenant_id="tenant-1", credential_id="google-docs", actor_id="user:member-1"
    )

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "docs-access",
                "refresh_token": "docs-refresh",
                "expires_in": 3600,
                "scope": GOOGLE_DOCS_READONLY_SCOPE,
            }

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.post.return_value = Response()
    monkeypatch.setattr("backend.services.tools.google_oauth_cli.httpx.Client", lambda **kwargs: client)

    secret = exchange_google_docs_oauth_code(code="auth-code", state=issued.state)
    assert '"provider_kind": "google_docs"' in secret
    assert '"access_token": "docs-access"' in secret
    assert client.post.call_args.args[0] == GOOGLE_OAUTH_TOKEN_URL


def test_docs_state_rejects_other_provider() -> None:
    from backend.services.credentials.oauth_state import sign_oauth_state

    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "google-docs",
            "actor_id": "user:member-1",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "gmail",
        }
    )
    with pytest.raises(GoogleDocsOAuthConnectError, match="provider mismatch"):
        verify_google_docs_oauth_state(state)

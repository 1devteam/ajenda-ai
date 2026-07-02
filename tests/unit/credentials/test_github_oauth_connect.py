from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.credentials.github_oauth_client import GITHUB_OAUTH_TOKEN_URL
from backend.services.credentials.github_oauth_connect import (
    GitHubOAuthConnectError,
    exchange_github_oauth_code,
    issue_github_oauth_authorization,
    verify_github_oauth_state,
)


def test_issue_github_oauth_authorization_returns_signed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_SECRET", "github-client-secret")

    result = issue_github_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="github-read",
        actor_id="human:test@example.com",
    )

    assert result.authorization_url.startswith("https://github.com/login/oauth/authorize")
    assert "read%3Auser" in result.authorization_url or "read:user" in result.authorization_url
    claims = verify_github_oauth_state(result.state)
    assert claims.tenant_id == "tenant-1"
    assert claims.provider == "github"


def test_exchange_github_oauth_code_serializes_provider_kind_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_SECRET", "github-client-secret")

    issued = issue_github_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="github-read",
        actor_id="human:test@example.com",
    )

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "github-access",
                "refresh_token": "github-refresh",
                "expires_in": 3600,
                "token_type": "bearer",
                "scope": "read:user",
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr("backend.services.credentials.github_oauth_client.httpx.Client", lambda **kwargs: fake_client)

    secret_value = exchange_github_oauth_code(code="auth-code", state=issued.state)

    assert '"provider_kind": "github"' in secret_value
    assert '"access_token": "github-access"' in secret_value
    fake_client.post.assert_called_once()
    assert fake_client.post.call_args.args[0] == GITHUB_OAUTH_TOKEN_URL


def test_verify_github_oauth_state_rejects_wrong_provider() -> None:
    from backend.services.credentials.oauth_state import sign_oauth_state

    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "github-read",
            "actor_id": "human:test@example.com",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "linkedin",
        }
    )
    with pytest.raises(GitHubOAuthConnectError, match="provider mismatch"):
        verify_github_oauth_state(state)

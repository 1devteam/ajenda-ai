from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.credentials.linkedin_oauth_client import (
    LINKEDIN_OAUTH_TOKEN_URL,
)
from backend.services.credentials.linkedin_oauth_connect import (
    LinkedInOAuthConnectError,
    exchange_linkedin_oauth_code,
    issue_linkedin_oauth_authorization,
    verify_linkedin_oauth_state,
)


def test_issue_linkedin_oauth_authorization_returns_signed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_ID", "linkedin-client-id")
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_SECRET", "linkedin-client-secret")

    result = issue_linkedin_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="linkedin-read",
        actor_id="human:test@example.com",
    )

    assert result.authorization_url.startswith("https://www.linkedin.com/oauth/v2/authorization")
    assert "state=" in result.authorization_url
    claims = verify_linkedin_oauth_state(result.state)
    assert claims.tenant_id == "tenant-1"
    assert claims.credential_id == "linkedin-read"
    assert claims.actor_id == "human:test@example.com"
    assert claims.provider == "linkedin"


def test_exchange_linkedin_oauth_code_serializes_provider_kind_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_ID", "linkedin-client-id")
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_SECRET", "linkedin-client-secret")

    issued = issue_linkedin_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="linkedin-read",
        actor_id="human:test@example.com",
    )

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "linkedin-access",
                "refresh_token": "linkedin-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "openid profile email",
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr("backend.services.credentials.linkedin_oauth_client.httpx.Client", lambda **kwargs: fake_client)

    secret_value = exchange_linkedin_oauth_code(code="auth-code", state=issued.state)

    assert '"provider_kind": "linkedin"' in secret_value
    assert '"access_token": "linkedin-access"' in secret_value
    fake_client.post.assert_called_once()
    assert fake_client.post.call_args.args[0] == LINKEDIN_OAUTH_TOKEN_URL


def test_verify_linkedin_oauth_state_rejects_wrong_provider() -> None:
    from backend.services.credentials.oauth_state import sign_oauth_state

    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "linkedin-read",
            "actor_id": "human:test@example.com",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "salesforce",
        }
    )
    with pytest.raises(LinkedInOAuthConnectError, match="provider mismatch"):
        verify_linkedin_oauth_state(state)

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.credentials.salesforce_oauth_client import (
    SalesforceOAuthClientConfig,
    SalesforceOAuthError,
    _post_token,
    salesforce_token_url,
)
from backend.services.credentials.salesforce_oauth_connect import (
    SalesforceOAuthConnectError,
    exchange_salesforce_oauth_code,
    issue_salesforce_oauth_authorization,
    verify_salesforce_oauth_state,
)


def test_issue_salesforce_oauth_authorization_returns_signed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_ID", "sf-client-id")
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_SECRET", "sf-client-secret")

    result = issue_salesforce_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="salesforce-read",
        actor_id="human:test@example.com",
    )

    assert result.authorization_url.startswith("https://login.salesforce.com/services/oauth2/authorize")
    claims = verify_salesforce_oauth_state(result.state)
    assert claims.tenant_id == "tenant-1"
    assert claims.credential_id == "salesforce-read"
    assert claims.provider == "salesforce"


def test_exchange_salesforce_oauth_code_returns_instance_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_ID", "sf-client-id")
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_SECRET", "sf-client-secret")

    issued = issue_salesforce_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="salesforce-read",
        actor_id="human:test@example.com",
    )

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "sf-access",
                "refresh_token": "sf-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "api refresh_token",
                "instance_url": "https://mycompany.my.salesforce.com",
            }

        text = ""

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr(
        "backend.services.credentials.salesforce_oauth_client.httpx.Client", lambda **kwargs: fake_client
    )

    connect_secret = exchange_salesforce_oauth_code(code="auth-code", state=issued.state)

    assert '"provider_kind": "salesforce"' in connect_secret.secret_value
    assert connect_secret.trusted_destination_hosts == ("mycompany.my.salesforce.com",)
    token_url = salesforce_token_url(login_url="https://login.salesforce.com")
    fake_client.post.assert_called_once()
    assert fake_client.post.call_args.args[0] == token_url


def test_verify_salesforce_oauth_state_rejects_tampered_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_ID", "sf-client-id")
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_SECRET", "sf-client-secret")

    issued = issue_salesforce_oauth_authorization(
        tenant_id="tenant-1",
        credential_id="salesforce-read",
        actor_id="human:test@example.com",
    )
    tampered = f"{issued.state}x"
    with pytest.raises(SalesforceOAuthConnectError, match=r"malformed|signature mismatch"):
        verify_salesforce_oauth_state(tampered)


def test_salesforce_token_error_does_not_echo_provider_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        status_code = 400
        text = "synthetic-sensitive-provider-detail"

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.post.return_value = _FakeResponse()
    monkeypatch.setattr(
        "backend.services.credentials.salesforce_oauth_client.httpx.Client", lambda **_kwargs: fake_client
    )

    with pytest.raises(SalesforceOAuthError) as exc_info:
        _post_token(
            client=SalesforceOAuthClientConfig(
                client_id="client",
                client_secret="secret",
                redirect_uri="http://test.invalid/callback",
                login_url="https://test.invalid",
            ),
            payload={"grant_type": "refresh_token"},
            timeout_seconds=1.0,
        )

    assert "HTTP 400" in str(exc_info.value)
    assert "synthetic-sensitive-provider-detail" not in str(exc_info.value)

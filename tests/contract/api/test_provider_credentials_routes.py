from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.account import router as account_router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.services.credentials.management_service import ProviderCredentialCreateResult, ProviderCredentialSummary


def _build_client(*, roles: tuple[str, ...] = ("tenant_owner",)) -> tuple[TestClient, uuid.UUID]:
    tenant_id = uuid.uuid4()
    app = FastAPI()

    principal = UserPrincipal(
        subject_id="human:test@example.com",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.USER,
        roles=roles,
        permissions=frozenset(),
        email="test@example.com",
    )

    @app.middleware("http")
    async def _inject_principal(request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = principal
        return await call_next(request)

    app.include_router(account_router, prefix="/v1")

    def override_tenant_id() -> uuid.UUID:
        return tenant_id

    def override_db():
        session = MagicMock()
        yield session

    app.dependency_overrides[get_request_tenant_id] = override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = override_db
    return TestClient(app, raise_server_exceptions=False), tenant_id


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
def test_create_provider_credential_returns_metadata_only(mock_service_cls: MagicMock) -> None:
    client, tenant_id = _build_client()
    summary = ProviderCredentialSummary(
        credential_id="hubspot-crm",
        tenant_id=str(tenant_id),
        provider="external_crm",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["crm.research"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["hubspot-crm-ingress"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials",
        json={
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "integration": "hubspot",
            "secret_value": "pak-secret",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["credential"]["credential_id"] == "hubspot-crm"
    assert "secret" not in body["credential"]
    assert "pak-secret" not in response.text


@patch("backend.api.routes.provider_credentials.issue_gmail_oauth_authorization")
def test_gmail_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.gmail_oauth_connect import GmailOAuthAuthorizeResult

    mock_issue.return_value = GmailOAuthAuthorizeResult(
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/gmail/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/gmail/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["state"] == "signed-state-token"


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_gmail_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_gmail_oauth_state")
def test_gmail_oauth_connect_registers_credential(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="gmail-email",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="gmail",
    )
    mock_exchange.return_value = '{"access_token":"oauth-access","refresh_token":"oauth-refresh"}'
    summary = ProviderCredentialSummary(
        credential_id="gmail-email",
        tenant_id=str(tenant_id),
        provider="external_email",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["gtm.email_send"],
        allowed_side_effect_classes=["external_send"],
        trusted_destination_hosts=["gmail.googleapis.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/gmail/oauth/connect",
        json={"code": "auth-code", "state": "signed-state-token", "credential_id": "gmail-email"},
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "gmail-email"
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.issue_linkedin_oauth_authorization")
def test_linkedin_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.linkedin_oauth_connect import LinkedInOAuthAuthorizeResult

    mock_issue.return_value = LinkedInOAuthAuthorizeResult(
        authorization_url="https://www.linkedin.com/oauth/v2/authorization?client_id=test",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/linkedin/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/linkedin/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://www.linkedin.com/")
    assert body["state"] == "signed-state-token"


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_linkedin_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_linkedin_oauth_state")
def test_linkedin_oauth_connect_registers_credential(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="linkedin-read",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="linkedin",
    )
    mock_exchange.return_value = '{"provider_kind":"linkedin","access_token":"oauth-access"}'
    summary = ProviderCredentialSummary(
        credential_id="linkedin-read",
        tenant_id=str(tenant_id),
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["linkedin.profile_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["api.linkedin.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/linkedin/oauth/connect",
        json={"code": "auth-code", "state": "signed-state-token", "credential_id": "linkedin-read"},
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "linkedin-read"
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.issue_salesforce_oauth_authorization")
def test_salesforce_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.salesforce_oauth_connect import SalesforceOAuthAuthorizeResult

    mock_issue.return_value = SalesforceOAuthAuthorizeResult(
        authorization_url="https://login.salesforce.com/services/oauth2/authorize?client_id=test",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/salesforce/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/salesforce/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert "salesforce.com" in body["authorization_url"]
    assert body["state"] == "signed-state-token"


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_salesforce_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_salesforce_oauth_state")
def test_salesforce_oauth_connect_registers_credential_with_instance_host(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims
    from backend.services.credentials.salesforce_oauth_connect import SalesforceOAuthConnectSecret

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="salesforce-read",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="salesforce",
    )
    mock_exchange.return_value = SalesforceOAuthConnectSecret(
        secret_value='{"provider_kind":"salesforce","access_token":"oauth-access"}',
        trusted_destination_hosts=("mycompany.my.salesforce.com",),
    )
    summary = ProviderCredentialSummary(
        credential_id="salesforce-read",
        tenant_id=str(tenant_id),
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["salesforce.soql_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["mycompany.my.salesforce.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/salesforce/oauth/connect",
        json={"code": "auth-code", "state": "signed-state-token", "credential_id": "salesforce-read"},
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "salesforce-read"
    assert response.json()["credential"]["trusted_destination_hosts"] == ["mycompany.my.salesforce.com"]
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.issue_google_calendar_oauth_authorization")
def test_google_calendar_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.google_calendar_oauth_connect import GoogleCalendarOAuthAuthorizeResult

    mock_issue.return_value = GoogleCalendarOAuthAuthorizeResult(
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/google-calendar/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/google-calendar/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["state"] == "signed-state-token"


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_google_calendar_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_google_calendar_oauth_state")
def test_google_calendar_oauth_connect_registers_credential(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="google-calendar-read",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="google_calendar",
    )
    mock_exchange.return_value = '{"provider_kind":"google_calendar","access_token":"oauth-access"}'
    summary = ProviderCredentialSummary(
        credential_id="google-calendar-read",
        tenant_id=str(tenant_id),
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["google_calendar.events_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["www.googleapis.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/google-calendar/oauth/connect",
        json={"code": "auth-code", "state": "signed-state-token", "credential_id": "google-calendar-read"},
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "google-calendar-read"
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.issue_github_oauth_authorization")
def test_github_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.github_oauth_connect import GitHubOAuthAuthorizeResult

    mock_issue.return_value = GitHubOAuthAuthorizeResult(
        authorization_url="https://github.com/login/oauth/authorize?client_id=test",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/github/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/github/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://github.com/")
    assert body["state"] == "signed-state-token"


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_github_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_github_oauth_state")
def test_github_oauth_connect_registers_credential(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="github-read",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="github",
    )
    mock_exchange.return_value = '{"provider_kind":"github","access_token":"oauth-access"}'
    summary = ProviderCredentialSummary(
        credential_id="github-read",
        tenant_id=str(tenant_id),
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["github.repo_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["api.github.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/github/oauth/connect",
        json={"code": "auth-code", "state": "signed-state-token", "credential_id": "github-read"},
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "github-read"
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.issue_google_contacts_oauth_authorization")
def test_google_contacts_oauth_authorize_url_returns_signed_state(mock_issue: MagicMock) -> None:
    from backend.services.credentials.google_contacts_oauth_connect import GoogleContactsOAuthAuthorizeResult

    mock_issue.return_value = GoogleContactsOAuthAuthorizeResult(
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth?scope=contacts.readonly",
        state="signed-state-token",
        redirect_uri="http://localhost:5173/credentials/google-contacts/callback",
    )
    client, _tenant_id = _build_client()
    response = client.get("/v1/account/provider-credentials/google-contacts/oauth/authorize-url")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["state"] == "signed-state-token"
    assert body["redirect_uri"].endswith("/credentials/google-contacts/callback")


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
@patch("backend.api.routes.provider_credentials.exchange_google_contacts_oauth_code")
@patch("backend.api.routes.provider_credentials.verify_google_contacts_oauth_state")
def test_google_contacts_oauth_connect_registers_credential(
    mock_verify: MagicMock,
    mock_exchange: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    from backend.services.credentials.oauth_state import OAuthStateClaims

    client, tenant_id = _build_client()
    mock_verify.return_value = OAuthStateClaims(
        tenant_id=str(tenant_id),
        credential_id="google-contacts-read",
        actor_id="human:test@example.com",
        nonce="nonce",
        issued_at=1_700_000_000,
        provider="google_contacts",
    )
    mock_exchange.return_value = (
        '{"provider_kind":"google_contacts","access_token":"oauth-access","refresh_token":"oauth-refresh"}'
    )
    summary = ProviderCredentialSummary(
        credential_id="google-contacts-read",
        tenant_id=str(tenant_id),
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        allowed_actions=["provider.external_read"],
        allowed_side_effect_classes=["external_read"],
        trusted_destination_hosts=["people.googleapis.com", "www.googleapis.com"],
        uses_platform_master_key=False,
        platform_master_warning=None,
        created_at="2026-06-25T00:00:00+00:00",
        updated_at="2026-06-25T00:00:00+00:00",
    )
    mock_service_cls.return_value.register.return_value = ProviderCredentialCreateResult(
        summary=summary,
        secret_returned_once=False,
        warning=None,
    )

    response = client.post(
        "/v1/account/provider-credentials/google-contacts/oauth/connect",
        json={
            "code": "auth-code",
            "state": "signed-state-token",
            "credential_id": "google-contacts-read",
        },
    )
    assert response.status_code == 201
    assert response.json()["credential"]["credential_id"] == "google-contacts-read"
    assert "oauth-access" not in response.text


@patch("backend.api.routes.provider_credentials.ProviderCredentialManagementService")
def test_viewer_cannot_create_provider_credential(mock_service_cls: MagicMock) -> None:
    client, _tenant_id = _build_client(roles=("viewer",))
    response = client.post(
        "/v1/account/provider-credentials",
        json={
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "secret_value": "pak-secret",
        },
    )
    assert response.status_code == 403
    mock_service_cls.return_value.register.assert_not_called()

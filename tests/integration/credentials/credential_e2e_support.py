from __future__ import annotations

import json
import os
import socket
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository
from backend.workers.handlers.tool_invoke import tool_invoke_handler
from backend.services.credentials.gmail_runtime_token import (
    GmailRuntimeTokenError,
    is_gmail_oauth_secret,
    resolve_gmail_credential_secret,
)
from backend.services.credentials.github_runtime_token import (
    GitHubRuntimeTokenError,
    is_github_oauth_secret,
    resolve_github_credential_secret,
)
from backend.services.credentials.google_calendar_runtime_token import (
    GoogleCalendarRuntimeTokenError,
    is_google_calendar_oauth_secret,
    resolve_google_calendar_credential_secret,
)
from backend.services.credentials.linkedin_runtime_token import (
    LinkedInRuntimeTokenError,
    is_linkedin_oauth_secret,
    resolve_linkedin_credential_secret,
)
from backend.services.credentials.salesforce_runtime_token import (
    SalesforceRuntimeTokenError,
    is_salesforce_oauth_secret,
    resolve_salesforce_credential_secret,
)
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from tests.integration.standalone.github_e2e_support import resolve_github_credential_secret_for_e2e
from tests.integration.standalone.gmail_e2e_support import (
    resolve_gmail_access_token_for_e2e,
    resolve_gmail_credential_secret_for_e2e,
)
from tests.integration.standalone.google_calendar_e2e_support import (
    resolve_google_calendar_credential_secret_for_e2e,
)
from tests.integration.standalone.hubspot_e2e_support import resolve_hubspot_access_token
from tests.integration.standalone.linkedin_e2e_support import resolve_linkedin_credential_secret_for_e2e
from tests.integration.standalone.salesforce_e2e_support import resolve_salesforce_credential_secret_for_e2e


def auth_headers(*, tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def provision_operational_tenant(client: TestClient, *, prefix: str = "cred-live") -> tuple[str, str]:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "Credential Live Co", "email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup.status_code == 201, signup.text
    tenant_id = signup.json()["tenant_id"]
    token = signup.json()["verification_token"]
    verify = client.post(
        "/v1/onboarding/verify-email",
        json={"token": token},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert verify.status_code == 200, verify.text
    bootstrap_key = verify.json()["api_key"]
    promote = client.post(
        "/v1/onboarding/promote-bootstrap-key",
        headers=auth_headers(tenant_id=tenant_id, api_key=bootstrap_key),
    )
    assert promote.status_code == 200, promote.text
    return tenant_id, promote.json()["api_key"]


def assert_not_simulated(payload: dict) -> None:
    assert payload.get("status") != "simulated"
    assert "simulated" not in str(payload.get("reason", "")).lower()
    if "real" in payload:
        assert payload.get("real") is True


@pytest.fixture
def credential_live_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")


@pytest.fixture
def hubspot_live_adapter_settings(monkeypatch: pytest.MonkeyPatch) -> str:
    token = resolve_hubspot_access_token()
    if not token:
        pytest.skip("No HubSpot token: set AJENDA_E2E_HUBSPOT_PAK or authenticate `hs account auth`")

    adapter_host = os.environ.get("AJENDA_E2E_ADAPTER_HOST", "127.0.0.1:8443")
    try:
        host, _, port = adapter_host.partition(":")
        socket.create_connection((host, int(port or "8443")), timeout=2).close()
    except OSError:
        pytest.skip(
            f"HubSpot CRM ingress not reachable at {adapter_host} — run: docker compose up -d hubspot-crm-ingress"
        )

    monkeypatch.setenv("AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST", adapter_host)
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS", "true")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_TLS_VERIFY", "false")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return token


@pytest.fixture
def gmail_live_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = resolve_gmail_access_token_for_e2e()
    if not token:
        pytest.skip("No Gmail token: run scripts/google/gmail_cli_auth.py auth or set AJENDA_E2E_GMAIL_TOKEN")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return token


@pytest.fixture
def gmail_live_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = resolve_gmail_credential_secret_for_e2e()
    if not secret:
        pytest.skip(
            "No Gmail credential: run scripts/google/gmail_cli_auth.py auth or set "
            "AJENDA_E2E_GMAIL_SECRET / AJENDA_E2E_GMAIL_TOKEN"
        )
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return secret


def _force_expired_oauth_secret(secret_value: str) -> str | None:
    if not secret_value.strip().startswith("{"):
        return None
    try:
        payload = json.loads(secret_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        return None
    payload["expires_at"] = "2000-01-01T00:00:00+00:00"
    return json.dumps(payload, sort_keys=True)


def refresh_live_oauth_secret(secret_value: str, *, integration: str) -> str | None:
    """Force-refresh an OAuth JSON secret when a live provider call returns 401/403."""
    forced = _force_expired_oauth_secret(secret_value)
    if forced is None:
        return None

    from backend.app.config import get_settings

    settings = get_settings()
    try:
        if integration == "gmail" and is_gmail_oauth_secret(forced):
            resolution = resolve_gmail_credential_secret(
                forced,
                auto_refresh=True,
                redirect_uri=settings.gmail_oauth_redirect_uri,
            )
        elif integration == "salesforce" and is_salesforce_oauth_secret(forced):
            resolution = resolve_salesforce_credential_secret(
                forced,
                auto_refresh=True,
                redirect_uri=settings.salesforce_oauth_redirect_uri,
            )
        elif integration == "linkedin" and is_linkedin_oauth_secret(forced):
            resolution = resolve_linkedin_credential_secret(
                forced,
                auto_refresh=True,
                redirect_uri=settings.linkedin_oauth_redirect_uri,
            )
        elif integration == "google_calendar" and is_google_calendar_oauth_secret(forced):
            resolution = resolve_google_calendar_credential_secret(
                forced,
                auto_refresh=True,
                redirect_uri=settings.google_calendar_oauth_redirect_uri,
            )
        elif integration == "github" and is_github_oauth_secret(forced):
            resolution = resolve_github_credential_secret(
                forced,
                auto_refresh=True,
                redirect_uri=settings.github_oauth_redirect_uri,
            )
        else:
            return None
    except (
        GmailRuntimeTokenError,
        SalesforceRuntimeTokenError,
        LinkedInRuntimeTokenError,
        GoogleCalendarRuntimeTokenError,
        GitHubRuntimeTokenError,
    ):
        return None

    updated = resolution.updated_secret or forced
    if updated == secret_value:
        return None
    return updated


def update_tenant_credential_secret(
    session: Session,
    *,
    tenant_id: str,
    credential_id: str,
    secret_value: str,
) -> None:
    repo = ProviderRuntimeCredentialRepository(session)
    row = repo.get_for_tenant(tenant_id=tenant_id, credential_id=credential_id)
    if row is None:
        raise ValueError(f"credential not found: {credential_id}")
    protector = RuntimeCredentialSecretProtector()
    row.secret_ciphertext = protector.encrypt_secret(secret_value)
    session.add(row)
    session.commit()


def invoke_live_tool_with_oauth_refresh_retry(
    *,
    task: ExecutionTask,
    context: dict[str, Any],
    secret_value: str,
    integration: str,
    tenant_id: str,
    credential_id: str,
    session_factory: Callable[[], Session],
    unauthorized_markers: tuple[str, ...] = ("HTTP 401", "HTTP 403"),
) -> dict[str, Any]:
    """Invoke tool handler; on 401/403 attempt OAuth refresh once, then fail closed."""
    try:
        return tool_invoke_handler(task, context)
    except ValueError as exc:
        message = str(exc)
        if not any(marker in message for marker in unauthorized_markers):
            raise
        refreshed = refresh_live_oauth_secret(secret_value, integration=integration)
        if refreshed is None:
            pytest.fail(f"Live provider unauthorized and OAuth refresh unavailable: {exc}")
        worker_session = session_factory()
        try:
            update_tenant_credential_secret(
                worker_session,
                tenant_id=tenant_id,
                credential_id=credential_id,
                secret_value=refreshed,
            )
        finally:
            worker_session.close()
        try:
            return tool_invoke_handler(task, context)
        except ValueError as retry_exc:
            retry_message = str(retry_exc)
            if any(marker in retry_message for marker in unauthorized_markers):
                pytest.fail(f"Live provider still unauthorized after OAuth refresh: {retry_exc}")
            raise





@pytest.fixture
def linkedin_live_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = resolve_linkedin_credential_secret_for_e2e()
    if not secret:
        pytest.skip(
            "No LinkedIn credential: set AJENDA_E2E_LINKEDIN_TOKEN or ~/.ajenda/linkedin-oauth.json"
        )
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_ID", os.environ.get("AJENDA_LINKEDIN_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_SECRET", os.environ.get("AJENDA_LINKEDIN_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return secret


@pytest.fixture
def google_calendar_live_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = resolve_google_calendar_credential_secret_for_e2e()
    if not secret:
        pytest.skip(
            "No Google Calendar credential: set AJENDA_E2E_GOOGLE_CALENDAR_SECRET or "
            "~/.ajenda/google-calendar-oauth.json or ~/.ajenda/google-oauth.yml with calendar.readonly"
        )
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return secret


@pytest.fixture
def github_live_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = resolve_github_credential_secret_for_e2e()
    if not secret:
        pytest.skip(
            "No GitHub credential: set AJENDA_E2E_GITHUB_SECRET or AJENDA_E2E_GITHUB_TOKEN or "
            "~/.ajenda/github-oauth.json"
        )
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_ID", os.environ.get("AJENDA_GITHUB_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_GITHUB_CLIENT_SECRET", os.environ.get("AJENDA_GITHUB_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return secret


@pytest.fixture
def salesforce_live_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = resolve_salesforce_credential_secret_for_e2e()
    if not secret:
        pytest.skip(
            "No Salesforce credential: set AJENDA_E2E_SALESFORCE_SECRET or "
            "AJENDA_E2E_SALESFORCE_TOKEN + AJENDA_E2E_SALESFORCE_INSTANCE_HOST "
            "or ~/.ajenda/salesforce-oauth.json"
        )
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_ID", os.environ.get("AJENDA_SALESFORCE_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_SALESFORCE_CLIENT_SECRET", os.environ.get("AJENDA_SALESFORCE_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return secret

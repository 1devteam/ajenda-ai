from __future__ import annotations

import os
import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.integration.standalone.gmail_e2e_support import resolve_gmail_access_token_for_e2e
from tests.integration.standalone.hubspot_e2e_support import resolve_hubspot_access_token


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
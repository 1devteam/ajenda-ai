"""Gmail OAuth authorize-url + connect over HTTP with real Postgres."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.credentials.gmail_oauth_connect import verify_gmail_oauth_state
from backend.services.credentials.linkedin_oauth_connect import (
    LinkedInOAuthConnectError,
    verify_linkedin_oauth_state,
)
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def test_gmail_oauth_authorize_url_returns_signed_state_over_http(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "integration-google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "integration-google-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-oauth-http")
        response = client.get(
            "/v1/account/provider-credentials/gmail/oauth/authorize-url",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["state"]
    assert "." in body["state"]
    claims = verify_gmail_oauth_state(body["state"])
    assert claims.tenant_id == tenant_id
    assert claims.credential_id == "gmail-email"


@patch("backend.api.routes.provider_credentials.exchange_gmail_oauth_code")
def test_gmail_oauth_connect_registers_credential_over_http(
    mock_exchange,
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "integration-google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "integration-google-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    mock_exchange.return_value = (
        '{"access_token":"oauth-access","refresh_token":"oauth-refresh","expires_at":"2099-01-01T00:00:00+00:00"}'
    )

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-oauth-connect")
        authorize = client.get(
            "/v1/account/provider-credentials/gmail/oauth/authorize-url?credential_id=gmail-email",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert authorize.status_code == 200, authorize.text
        state = authorize.json()["state"]

        connect = client.post(
            "/v1/account/provider-credentials/gmail/oauth/connect",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={"code": "integration-auth-code", "state": state, "credential_id": "gmail-email"},
        )
        assert connect.status_code == 201, connect.text
        credential = connect.json()["credential"]
        assert credential["credential_id"] == "gmail-email"
        assert credential["provider"] == "external_email"
        assert "oauth-access" not in connect.text

        listed = client.get(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert listed.status_code == 200
        assert any(item["credential_id"] == "gmail-email" for item in listed.json()["credentials"])


@patch("backend.api.routes.provider_credentials.exchange_linkedin_oauth_code")
def test_linkedin_ui_runtime_trace_is_durable_and_reconstructable_over_http(
    mock_exchange,
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare browser-style input and API facts against the exported trace."""

    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_ID", "integration-linkedin-client-id")
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_SECRET", "integration-linkedin-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    mock_exchange.return_value = '{"provider_kind":"linkedin","access_token":"integration-linkedin-access"}'
    local_interaction_id = "00000000-0000-0000-0000-000000000321"

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="linkedin-ui-runtime")
        headers = auth_headers(tenant_id=tenant_id, api_key=api_key)
        clicked = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=headers,
            json={
                "event_id": local_interaction_id,
                "local_interaction_id": local_interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.action_clicked",
                "producer_sequence": 1,
                "occurred_at": "2026-10-21T00:00:00+00:00",
            },
        )
        assert clicked.status_code == 201, clicked.text
        receipt = clicked.json()
        assert receipt["acknowledgement"] == "persisted"
        interaction_id = receipt["server_interaction_id"]

        # A retry returns the same committed fact and cannot create another
        # interaction. This is independently observable at the HTTP boundary.
        retry = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=headers,
            json={
                "event_id": local_interaction_id,
                "local_interaction_id": local_interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.action_clicked",
                "producer_sequence": 1,
                "occurred_at": "2026-10-21T00:00:00+00:00",
            },
        )
        assert retry.status_code == 201, retry.text
        assert retry.json()["duplicate"] is True
        assert retry.json()["server_interaction_id"] == interaction_id

        for event_id, phase, sequence in (
            ("00000000-0000-0000-0000-000000000322", "ui.handler_entered", 2),
            ("00000000-0000-0000-0000-000000000323", "ui.request_attempted", 3),
        ):
            event = client.post(
                "/v1/account/provider-credentials/runtime-interactions/events",
                headers=headers,
                json={
                    "event_id": event_id,
                    "local_interaction_id": local_interaction_id,
                    "server_interaction_id": interaction_id,
                    "action_id": "credential.linkedin.oauth.connect",
                    "phase": phase,
                    "producer_sequence": sequence,
                    "occurred_at": "2026-10-21T00:00:00+00:00",
                },
            )
            assert event.status_code == 201, event.text

        request_headers = {
            **headers,
            "X-Ajenda-UI-Local-Interaction-Id": local_interaction_id,
            "X-Ajenda-UI-Interaction-Id": interaction_id,
        }
        authorize = client.get(
            "/v1/account/provider-credentials/linkedin/oauth/authorize-url?credential_id=linkedin-read",
            headers=request_headers,
        )
        assert authorize.status_code == 200, authorize.text
        state = authorize.json()["state"]
        assert verify_linkedin_oauth_state(state).interaction_id == interaction_id

        redirect = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=headers,
            json={
                "event_id": "00000000-0000-0000-0000-000000000324",
                "local_interaction_id": local_interaction_id,
                "server_interaction_id": interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.redirect_assigned",
                "producer_sequence": 4,
                "occurred_at": "2026-10-21T00:00:01+00:00",
            },
        )
        assert redirect.status_code == 201, redirect.text

        connect = client.post(
            "/v1/account/provider-credentials/linkedin/oauth/connect",
            headers=headers,
            json={"code": "integration-auth-code", "state": state, "credential_id": "linkedin-read"},
        )
        assert connect.status_code == 201, connect.text

        artifact = client.get(
            f"/v1/account/provider-credentials/linkedin/oauth/runtime-evidence/{interaction_id}",
            headers=headers,
        )
        assert artifact.status_code == 200, artifact.text
        body = artifact.json()
        assert body["terminal_state"] == "completed"
        phases = {item["phase"] for item in body["events"]}
        assert {
            "ui.action_clicked",
            "ui.handler_entered",
            "ui.request_attempted",
            "api.request_received",
            "oauth.authorization_url_issued",
            "ui.redirect_assigned",
            "api.callback_received",
            "oauth.credential_persisted",
        } <= phases
        assert all(item["status"] == "observed" for item in body["coverage"])
        assert body["contradictions"] == []
        assert body["first_divergence"] is None
        assert body["provenance"]["artifact_type"] == "graft_ui_runtime_interaction_evidence"
        assert body["provenance"]["artifact_schema_version"] == "1.0.0"
        assert body["provenance"]["sha256"].startswith("sha256:")
        assert "integration-auth-code" not in artifact.text
        assert "integration-linkedin-access" not in artifact.text
        assert "integration-linkedin-client-secret" not in artifact.text

        other_tenant_id, other_api_key = provision_operational_tenant(client, prefix="linkedin-ui-runtime-other")
        conflicting_event = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=auth_headers(tenant_id=other_tenant_id, api_key=other_api_key),
            json={
                "event_id": local_interaction_id,
                "local_interaction_id": local_interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.action_clicked",
                "producer_sequence": 1,
                "occurred_at": "2026-10-21T00:00:00+00:00",
            },
        )
        assert conflicting_event.status_code == 409
        cross_tenant = client.get(
            f"/v1/account/provider-credentials/linkedin/oauth/runtime-evidence/{interaction_id}",
            headers=auth_headers(tenant_id=other_tenant_id, api_key=other_api_key),
        )
        assert cross_tenant.status_code == 404


@patch("backend.api.routes.provider_credentials.exchange_linkedin_oauth_code")
def test_linkedin_ui_runtime_trace_marks_provider_exchange_failure_without_exposing_oauth_data(
    mock_exchange,
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_ID", "integration-linkedin-client-id")
    monkeypatch.setenv("AJENDA_LINKEDIN_CLIENT_SECRET", "integration-linkedin-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    mock_exchange.side_effect = LinkedInOAuthConnectError("provider exchange rejected")
    local_interaction_id = "00000000-0000-0000-0000-000000000331"

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="linkedin-ui-runtime-failure")
        headers = auth_headers(tenant_id=tenant_id, api_key=api_key)
        persisted = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=headers,
            json={
                "event_id": local_interaction_id,
                "local_interaction_id": local_interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.action_clicked",
                "producer_sequence": 1,
                "occurred_at": "2026-10-21T00:00:00+00:00",
            },
        )
        assert persisted.status_code == 201, persisted.text
        interaction_id = persisted.json()["server_interaction_id"]
        for event_id, phase, sequence in (
            ("00000000-0000-0000-0000-000000000332", "ui.handler_entered", 2),
            ("00000000-0000-0000-0000-000000000333", "ui.request_attempted", 3),
        ):
            event = client.post(
                "/v1/account/provider-credentials/runtime-interactions/events",
                headers=headers,
                json={
                    "event_id": event_id,
                    "local_interaction_id": local_interaction_id,
                    "server_interaction_id": interaction_id,
                    "action_id": "credential.linkedin.oauth.connect",
                    "phase": phase,
                    "producer_sequence": sequence,
                    "occurred_at": "2026-10-21T00:00:00+00:00",
                },
            )
            assert event.status_code == 201, event.text
        authorize = client.get(
            "/v1/account/provider-credentials/linkedin/oauth/authorize-url?credential_id=linkedin-read",
            headers={
                **headers,
                "X-Ajenda-UI-Local-Interaction-Id": local_interaction_id,
                "X-Ajenda-UI-Interaction-Id": interaction_id,
            },
        )
        assert authorize.status_code == 200, authorize.text
        state = authorize.json()["state"]
        redirect = client.post(
            "/v1/account/provider-credentials/runtime-interactions/events",
            headers=headers,
            json={
                "event_id": "00000000-0000-0000-0000-000000000334",
                "local_interaction_id": local_interaction_id,
                "server_interaction_id": interaction_id,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": "ui.redirect_assigned",
                "producer_sequence": 4,
                "occurred_at": "2026-10-21T00:00:01+00:00",
            },
        )
        assert redirect.status_code == 201, redirect.text
        failed = client.post(
            "/v1/account/provider-credentials/linkedin/oauth/connect",
            headers=headers,
            json={"code": "deliberately-rejected-code", "state": state, "credential_id": "linkedin-read"},
        )
        assert failed.status_code == 400

        artifact = client.get(
            f"/v1/account/provider-credentials/linkedin/oauth/runtime-evidence/{interaction_id}", headers=headers
        )
        assert artifact.status_code == 200, artifact.text
        body = artifact.json()
        assert body["terminal_state"] == "failed"
        assert body["contradictions"] == []
        assert body["first_divergence"] is None
        assert "oauth.exchange_failed" in {event["phase"] for event in body["events"]}
        credential_stage = next(item for item in body["coverage"] if item["stage"] == "oauth.credential_persisted")
        assert credential_stage == {
            "stage": "oauth.credential_persisted",
            "applicable": True,
            "status": "observed",
            "reason": "terminal_outcome_observed",
        }
        assert "deliberately-rejected-code" not in artifact.text
        assert state not in artifact.text

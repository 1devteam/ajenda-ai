from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.main import create_app
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.workers.handlers.tool_invoke import tool_invoke_handler
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def _store_gmail_credential(session: Session, *, tenant_id: str, credential_id: str = "gmail-email") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-gmail-bearer-token")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_email",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["gtm.email_send", "gtm.email_check"],
        allowed_side_effect_classes=["external_read", "external_send"],
        trusted_destination_hosts=["gmail.googleapis.com"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def _gmail_egress_spy(*, status_code: int = 200, body: str = '{"messages":[]}') -> MagicMock:
    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
            connect_url="https://10.0.0.6/gmail/v1/users/me/messages",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.6"),
            sni_hostname="gmail.googleapis.com",
            host_header="gmail.googleapis.com",
        ),
        NetworkEgressResponse(status_code=status_code, headers={}, body_text=body, body_truncated=False),
    )
    return authority


def test_provider_credentials_api_register_list_revoke_gmail(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
) -> None:
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-cred")

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "gmail-email",
                "provider": "external_email",
                "integration": "gmail",
                "secret_value": "tenant-gmail-oauth-bearer",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()
        assert body["credential"]["credential_id"] == "gmail-email"
        assert body["credential"]["provider"] == "external_email"
        assert "gmail.googleapis.com" in body["credential"]["trusted_destination_hosts"]
        assert "tenant-gmail-oauth-bearer" not in create_resp.text

        list_resp = client.get(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert list_resp.status_code == 200
        assert any(item["credential_id"] == "gmail-email" for item in list_resp.json()["credentials"])

        revoke_resp = client.post(
            "/v1/account/provider-credentials/gmail-email/revoke",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked"] is True


def test_gmail_email_check_and_send_happy_path_via_egress_contract(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    _store_gmail_credential(pg_session, tenant_id=tenant_id)
    pg_session.commit()

    check_authority = _gmail_egress_spy(
        status_code=200,
        body='{"messages":[{"id":"msg-live-1","threadId":"thr-1","snippet":"Inbox hello"}]}',
    )
    send_authority = _gmail_egress_spy(
        status_code=200,
        body='{"id":"sent-1","threadId":"thr-2","labelIds":["SENT"]}',
    )
    combined_authority = MagicMock()

    def _route_request(**kwargs):
        if str(kwargs.get("method", "GET")).upper() == "POST":
            return send_authority.request(**kwargs)
        return check_authority.request(**kwargs)

    combined_authority.request.side_effect = _route_request
    monkeypatch.setattr(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        lambda: combined_authority,
    )
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    context = {
        "worker_id": "worker-gmail-test",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": lambda: pg_session,
    }

    check_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="gmail check",
        description="gmail check",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_check",
                "input": {"query": "in:inbox", "limit": 5},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    check_result = tool_invoke_handler(check_task, context)
    check_output = check_result["output"]
    assert check_output["emails"][0]["id"] == "msg-live-1"
    assert check_output["emails"][0]["id"] != "sim-1"
    assert "gmail.googleapis.com" in check_authority.request.call_args.kwargs["url"]

    send_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="gmail send",
        description="gmail send",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_send",
                "input": {
                    "to": "buyer@example.com",
                    "subject": "Integration test",
                    "body": "Gmail credential flow proof",
                },
                "idempotency_key": "gmail-send-1",
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.email_send"],
                    "reason": "integration test",
                    "approved_by": "integration",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    send_result = tool_invoke_handler(send_task, context)
    send_output = send_result["output"]
    assert send_output["real"] is True
    assert send_output["status"] == "sent"
    assert send_output["provider"] == "gmail_api"
    assert "gmail.googleapis.com" in send_authority.request.call_args.kwargs["url"]


def test_gmail_email_send_without_credential_fails_closed(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools.runtime_authority import ToolRuntimeAuthorityError

    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="gmail send no cred",
        description="gmail send no cred",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_send",
                "input": {
                    "to": "buyer@example.com",
                    "subject": "No credential",
                    "body": "Should not send",
                },
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.email_send"],
                    "reason": "integration test",
                    "approved_by": "integration",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    with pytest.raises(ToolRuntimeAuthorityError, match="credential denied"):
        tool_invoke_handler(
            task,
            {
                "worker_id": "worker-gmail-test",
                "tenant_id": tenant_id,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: pg_session,
            },
        )

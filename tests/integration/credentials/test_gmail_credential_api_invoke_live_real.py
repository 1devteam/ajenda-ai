"""Live Gmail path: Credentials API registration → real Gmail API (no egress mocks)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.main import create_app
from tests.integration.credentials.credential_e2e_support import (
    auth_headers,
    invoke_live_tool_with_oauth_refresh_retry,
    provision_operational_tenant,
)

pytestmark = pytest.mark.integration


def test_gmail_api_register_then_live_email_check_no_egress_mock(
    credential_live_onboarding: None,
    gmail_live_secret: str,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    tenant_id: str
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-live-api")
        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "gmail-email",
                "provider": "external_email",
                "integration": "gmail",
                "secret_value": gmail_live_secret,
            },
        )
        assert create_resp.status_code == 201, create_resp.text

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    worker_session = session_factory()
    try:
        result = invoke_live_tool_with_oauth_refresh_retry(
            task=ExecutionTask(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                mission_id=uuid.uuid4(),
                title="live api gmail check",
                description="no egress mock",
                status="running",
                metadata_json={
                    "task_type": "tool.invoke",
                    "tool_invocation": {
                        "action": "gtm.email_check",
                        "input": {"query": "in:inbox", "limit": 3},
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
            ),
            context={
                "worker_id": "worker-gmail-live-api",
                "tenant_id": tenant_id,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: worker_session,
            },
            secret_value=gmail_live_secret,
            integration="gmail",
            tenant_id=tenant_id,
            credential_id="gmail-email",
            session_factory=session_factory,
        )
        output = result["output"]
        assert output.get("emails")
        assert output["emails"][0].get("id") != "sim-1"
        assert "simulated" not in str(output).lower()
        assert output.get("real") is True
    finally:
        worker_session.close()
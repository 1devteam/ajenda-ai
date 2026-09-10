"""Live HubSpot path: Credentials API registration → real adapter ingress (no egress mocks)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.main import create_app
from backend.workers.handlers.tool_invoke import tool_invoke_handler
from tests.integration.credentials.credential_e2e_support import (
    assert_not_simulated,
    auth_headers,
    provision_operational_tenant,
)

pytestmark = [pytest.mark.integration, pytest.mark.live]


def test_hubspot_api_register_then_live_crm_research_no_egress_mock(
    credential_live_onboarding: None,
    hubspot_live_adapter_settings: str,
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
        tenant_id, api_key = provision_operational_tenant(client, prefix="hs-live-api")
        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "integration": "hubspot",
                "secret_value": hubspot_live_adapter_settings,
            },
        )
        assert create_resp.status_code == 201, create_resp.text

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    worker_session = session_factory()
    try:
        result = tool_invoke_handler(
            ExecutionTask(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                mission_id=uuid.uuid4(),
                title="live api hubspot research",
                description="no egress mock",
                status="running",
                metadata_json={
                    "task_type": "tool.invoke",
                    "tool_invocation": {
                        "action": "crm.research",
                        "input": {"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
                    },
                    "credential_reference": {
                        "schema_version": 1,
                        "credential_id": "hubspot-crm",
                        "provider": "external_crm",
                        "credential_type": "api_key",
                    },
                },
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            ),
            {
                "worker_id": "worker-hs-live-api",
                "tenant_id": tenant_id,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: worker_session,
            },
        )
        output = result["output"]
        assert_not_simulated(output)
        assert output.get("plugin_required") is True or output.get("source") in {"hubspot", "external_crm"}
    finally:
        worker_session.close()

"""Live Salesforce path: Credentials API registration → real Salesforce API (no egress mocks)."""

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

pytestmark = pytest.mark.integration


def test_salesforce_api_register_then_live_soql_read_no_egress_mock(
    credential_live_onboarding: None,
    salesforce_live_secret: str,
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
        tenant_id, api_key = provision_operational_tenant(client, prefix="sf-live-api")
        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "salesforce-read",
                "provider": "external_read_provider",
                "integration": "salesforce",
                "secret_value": salesforce_live_secret,
            },
        )
        assert create_resp.status_code == 201, create_resp.text

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    worker_session = session_factory()
    try:
        try:
            result = tool_invoke_handler(
                ExecutionTask(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    mission_id=uuid.uuid4(),
                    title="live api salesforce soql read",
                    description="no egress mock",
                    status="running",
                    metadata_json={
                        "task_type": "tool.invoke",
                        "tool_invocation": {
                            "action": "salesforce.soql_read",
                            "input": {"soql": "SELECT Id FROM User LIMIT 1"},
                        },
                        "credential_reference": {
                            "schema_version": 1,
                            "credential_id": "salesforce-read",
                            "provider": "external_read_provider",
                            "credential_type": "api_key",
                        },
                    },
                    compliance_category="operational",
                    jurisdiction="US-ALL",
                    requires_human_review=False,
                ),
                {
                    "worker_id": "worker-salesforce-live-api",
                    "tenant_id": tenant_id,
                    "lease_id": str(uuid.uuid4()),
                    "session_factory": lambda: worker_session,
                },
            )
        except ValueError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                pytest.skip(f"Salesforce live token unavailable or unauthorized: {exc}")
            raise
        output = result["output"]
        assert_not_simulated(output)
        assert output.get("real") is True
        query_result = output.get("result")
        assert isinstance(query_result, dict)
        records = query_result.get("records")
        if isinstance(records, list) and records:
            first_id = records[0].get("Id") if isinstance(records[0], dict) else None
            assert first_id != "sim-sf-1"
    finally:
        worker_session.close()
"""Live GitHub path: Credentials API registration → real GitHub API (no egress mocks)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.main import create_app
from tests.integration.credentials.credential_e2e_support import (
    assert_not_simulated,
    auth_headers,
    invoke_live_tool_with_oauth_refresh_retry,
    provision_operational_tenant,
)

pytestmark = [pytest.mark.integration, pytest.mark.live]


def test_github_api_register_then_live_repo_read_no_egress_mock(
    credential_live_onboarding: None,
    github_live_secret: str,
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
        tenant_id, api_key = provision_operational_tenant(client, prefix="gh-live-api")
        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "github-read",
                "provider": "external_read_provider",
                "integration": "github",
                "secret_value": github_live_secret,
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
                title="live api github repo read",
                description="no egress mock",
                status="running",
                metadata_json={
                    "task_type": "tool.invoke",
                    "tool_invocation": {
                        "action": "github.repo_read",
                        "input": {"owner": "1devteam", "repo": "ajenda-ai"},
                    },
                    "credential_reference": {
                        "schema_version": 1,
                        "credential_id": "github-read",
                        "provider": "external_read_provider",
                        "credential_type": "api_key",
                    },
                },
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            ),
            context={
                "worker_id": "worker-github-live-api",
                "tenant_id": tenant_id,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: worker_session,
            },
            secret_value=github_live_secret,
            integration="github",
            tenant_id=tenant_id,
            credential_id="github-read",
            session_factory=session_factory,
            unauthorized_markers=("HTTP 401", "HTTP 403", "HTTP 404"),
        )
        output = result["output"]
        assert_not_simulated(output)
        assert output.get("real") is True
        repository = output.get("repository")
        assert isinstance(repository, dict)
        assert repository.get("full_name") == "1devteam/ajenda-ai"
    finally:
        worker_session.close()

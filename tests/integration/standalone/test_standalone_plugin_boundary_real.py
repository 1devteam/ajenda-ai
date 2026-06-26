"""AR-10: standalone brain paths must not silently become plugin paths."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.services.tools.runtime_authority import ToolRuntimeAuthorityError
from backend.workers.handlers.tool_invoke import tool_invoke_handler

pytestmark = pytest.mark.integration


def _context(*, tenant_id: str, session: Session) -> dict[str, object]:
    return {
        "worker_id": "worker-boundary",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": lambda: session,
    }


def test_internal_crm_upsert_without_credential_stays_on_brain(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )
    tenant_id = str(uuid.uuid4())
    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="internal upsert",
        description="standalone boundary",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.crm_upsert",
                "input": {
                    "record_type": "contact",
                    "data": {"email": "standalone@example.com", "firstname": "Stand", "lastname": "Alone"},
                },
                "idempotency_key": f"boundary-{uuid.uuid4().hex[:8]}",
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.crm_upsert"],
                    "reason": "boundary test",
                    "approved_by": "integration",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(task, _context(tenant_id=tenant_id, session=pg_session))
    output = result["output"]
    assert output["status"] == "upserted_internal"
    assert output["source"] == "ajenda_brain"
    assert output.get("plugin_required") is False


def test_gmail_send_without_credential_reference_fails_closed(
    integration_env: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )
    tenant_id = str(uuid.uuid4())
    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="plugin send no cred",
        description="must fail closed",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_send",
                "input": {"to": "x@example.com", "subject": "x", "body": "x"},
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.email_send"],
                    "reason": "boundary test",
                    "approved_by": "integration",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    with pytest.raises(ToolRuntimeAuthorityError, match="credential denied"):
        tool_invoke_handler(task, _context(tenant_id=tenant_id, session=pg_session))

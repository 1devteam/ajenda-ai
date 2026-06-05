from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.workers.handlers.tool_invoke import tool_invoke_handler


class SessionStub:
    def close(self) -> None:
        return None


def _session_factory() -> SessionStub:
    return SessionStub()


def _task(*, tenant_id: str, metadata: dict[str, Any]) -> ExecutionTask:
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="tool task",
        description="tool task",
        status="running",
        metadata_json={"task_type": "tool.invoke", **metadata},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _context(tenant_id: str) -> dict[str, Any]:
    return {
        "worker_id": "worker",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": _session_factory,
    }


def test_tool_invoke_handler_success_returns_dispatcher_valid_evidence_output() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={"tool_invocation": {"action": "record.search", "input": {"record_type": "account", "query": "Acme"}}},
    )

    result = tool_invoke_handler(task, _context(tenant_id))

    assert result["handler"] == "tool.invoke"
    assert result["status"] == "completed"
    assert result["action"] == "record.search"
    assert result["output"]["count"] == 1
    assert result["evidence"][0]["tenant_id"] == tenant_id
    assert result["runtime_context"]["task_id"] == str(task.id)


def test_tool_invoke_handler_rejects_tenant_mismatch() -> None:
    task = _task(
        tenant_id=str(uuid.uuid4()),
        metadata={"tool_invocation": {"action": "record.search", "input": {"record_type": "account"}}},
    )

    with pytest.raises(ValueError, match="tenant mismatch"):
        tool_invoke_handler(task, _context(str(uuid.uuid4())))


@pytest.mark.parametrize(
    "metadata,match",
    [
        ({}, "tool_invocation"),
        ({"tool_invocation": {"input": {}}}, "invalid tool_invocation"),
        ({"tool_invocation": {"action": "missing.action", "input": {}}}, "unknown action"),
    ],
)
def test_tool_invoke_handler_rejects_invalid_invocations(metadata: dict[str, Any], match: str) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, metadata=metadata)

    with pytest.raises(ValueError, match=match):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_fails_side_effecting_action_without_authority() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "record.write",
                "input": {"record_type": "contact", "data": {"name": "Avery"}},
            }
        },
    )

    with pytest.raises(ValueError, match="side-effecting action requires"):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_rejects_side_effect_authorization_without_capability_or_adapter() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "record.write",
                "input": {"record_type": "contact", "data": {"name": "Avery"}},
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["record.write"],
                    "reason": "unit test authorization",
                    "approved_by": "qa",
                }
            },
        },
    )

    with pytest.raises(ValueError, match="side-effecting action requires explicit capability/adapter authority"):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_gates_http_write_methods_before_network_call() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "http.request",
                "input": {"method": "POST", "url": "https://example.com/hook", "json_body": {"ok": True}},
            }
        },
    )

    with pytest.raises(ValueError, match="side-effecting action requires"):
        tool_invoke_handler(task, _context(tenant_id))

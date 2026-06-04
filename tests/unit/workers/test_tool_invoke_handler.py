from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.services.tools.local_records import LocalRecordProvider
from backend.workers.handlers.tool_invoke import tool_invoke_handler
from backend.workers.task_dispatcher import TaskHandlerContext


def _session() -> Any:
    return SimpleNamespace(close=lambda: None)


def _context(provider: LocalRecordProvider | None = None, *, tenant_id: str = "tenant-tool") -> TaskHandlerContext:
    return {
        "worker_id": "worker-tool",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": lambda: _session(),
    }


def _task(metadata: dict[str, Any], *, tenant_id: str = "tenant-tool") -> ExecutionTask:
    return ExecutionTask(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="Tool task",
        description="Tool task",
        status="running",
        metadata_json=metadata,
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def test_tool_invoke_handler_executes_registered_action() -> None:
    task = _task(
        {"task_type": "tool.invoke", "tool_invocation": {"action": "record.search", "input": {"record_type": "lead"}}}
    )

    result = tool_invoke_handler(task, _context())

    assert result["handler"] == "tool.invoke"
    assert result["status"] == "completed"
    assert result["action"] == "record.search"
    assert result["evidence"][0]["evidence_source"] == "tool.invoke.record.search"


def test_tool_invoke_handler_rejects_missing_invocation() -> None:
    with pytest.raises(ValueError, match="tool_invocation"):
        tool_invoke_handler(_task({"task_type": "tool.invoke"}), _context())


def test_tool_invoke_handler_rejects_unknown_action() -> None:
    task = _task({"task_type": "tool.invoke", "tool_invocation": {"action": "missing.action"}})

    with pytest.raises(ValueError, match="action is not registered"):
        tool_invoke_handler(task, _context())


def test_tool_invoke_handler_rejects_tenant_mismatch() -> None:
    task = _task({"task_type": "tool.invoke", "tool_invocation": {"action": "record.search"}}, tenant_id="tenant-a")

    with pytest.raises(ValueError, match="tenant does not match"):
        tool_invoke_handler(task, _context(tenant_id="tenant-b"))


def test_tool_invoke_handler_propagates_invalid_payload() -> None:
    task = _task(
        {"task_type": "tool.invoke", "tool_invocation": {"action": "record.search", "input": {"record_type": "bad"}}}
    )

    with pytest.raises(ValueError, match="unsupported record type"):
        tool_invoke_handler(task, _context())

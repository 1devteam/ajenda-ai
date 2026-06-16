from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.workers import task_dispatcher
from backend.workers.task_dispatcher import TaskDispatcher, TaskHandlerContext


class SessionStub:
    def close(self) -> None:
        return None


def _session_factory() -> SessionStub:
    return SessionStub()


def _task(*, tenant_id: str, task_type: str = "tool.invoke") -> ExecutionTask:
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="dispatcher task",
        description="dispatcher task",
        status="running",
        metadata_json={"task_type": task_type},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _dispatcher(*, tenant_id: str) -> TaskDispatcher:
    return TaskDispatcher(
        session_factory=_session_factory,  # type: ignore[arg-type]
        queue=object(),  # type: ignore[arg-type]
        worker_id="worker-1",
        tenant_id=tenant_id,
    )


def _patch_common_dispatcher_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    task: ExecutionTask,
    complete_error: Exception | None = RuntimeError("completion materialization failed"),
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"complete": [], "fail": [], "block": []}

    def load_task(self: TaskDispatcher, task_id: uuid.UUID) -> ExecutionTask | None:
        assert task_id == task.id
        return task

    def heartbeat(self: TaskDispatcher, lease_id: uuid.UUID, stop: object) -> None:
        return None

    def complete(
        self: TaskDispatcher,
        *,
        lease_id: uuid.UUID,
        task: ExecutionTask,
        result: dict[str, Any] | None = None,
        output_reason: str | None = None,
    ) -> None:
        calls["complete"].append({"lease_id": lease_id, "task": task, "result": result, "output_reason": output_reason})
        if complete_error is not None:
            raise complete_error

    def fail(self: TaskDispatcher, *, lease_id: uuid.UUID, reason: str) -> None:
        calls["fail"].append({"lease_id": lease_id, "reason": reason})

    def block_completion_failure(
        self: TaskDispatcher,
        *,
        lease_id: uuid.UUID,
        task: ExecutionTask,
        result: dict[str, Any],
        output_reason: str | None,
        reason: str,
        side_effect_class: str | None,
    ) -> None:
        calls["block"].append(
            {
                "lease_id": lease_id,
                "task": task,
                "result": result,
                "output_reason": output_reason,
                "reason": reason,
                "side_effect_class": side_effect_class,
            }
        )

    monkeypatch.setattr(TaskDispatcher, "_load_task", load_task)
    monkeypatch.setattr(TaskDispatcher, "_heartbeat_loop", heartbeat)
    monkeypatch.setattr(TaskDispatcher, "_complete", complete)
    monkeypatch.setattr(TaskDispatcher, "_fail", fail)
    monkeypatch.setattr(TaskDispatcher, "_block_completion_failure", block_completion_failure)
    return calls


def test_side_effecting_tool_invoke_completion_failure_blocks_instead_of_normal_fail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    handler_calls: list[str] = []

    def handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        handler_calls.append(str(task.id))
        return {
            "handler": "tool.invoke",
            "status": "completed",
            "action": "webhook.dispatch",
            "requested_action": "webhook.dispatch",
            "provider": "webhook",
            "side_effect_class": "external_send",
            "output": {"delivery_id": "delivery-1"},
            "evidence": [{"ok": True}],
        }

    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"tool.invoke": handler})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"tool.invoke": "tool action completed"})
    calls = _patch_common_dispatcher_paths(monkeypatch, task=task)
    lease_id = uuid.uuid4()

    caplog.set_level(logging.CRITICAL, logger="ajenda.task_dispatcher")
    _dispatcher(tenant_id=tenant_id).execute(task_id=task.id, lease_id=lease_id)

    assert handler_calls == [str(task.id)]
    assert len(calls["complete"]) == 1
    assert calls["fail"] == []
    assert len(calls["block"]) == 1
    assert calls["block"][0]["side_effect_class"] == "external_send"
    assert calls["block"][0]["reason"] == "completion materialization failed"
    assert any(record.message == "task_dispatch_completion_failed_after_side_effect" for record in caplog.records)


def test_handler_exception_still_uses_normal_fail_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    handler_calls: list[str] = []

    def handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        handler_calls.append(str(task.id))
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"tool.invoke": handler})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"tool.invoke": "tool action completed"})
    calls = _patch_common_dispatcher_paths(monkeypatch, task=task, complete_error=None)

    _dispatcher(tenant_id=tenant_id).execute(task_id=task.id, lease_id=uuid.uuid4())

    assert handler_calls == [str(task.id)]
    assert calls["complete"] == []
    assert calls["block"] == []
    assert len(calls["fail"]) == 1
    assert calls["fail"][0]["reason"] == "handler exploded"


def test_non_side_effecting_tool_invoke_completion_failure_preserves_normal_fail_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)

    def handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {
            "handler": "tool.invoke",
            "status": "completed",
            "action": "record.search",
            "requested_action": "record.search",
            "provider": "local_records",
            "side_effect_class": "none",
            "output": {"count": 1},
            "evidence": [{"ok": True}],
        }

    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"tool.invoke": handler})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"tool.invoke": "tool action completed"})
    calls = _patch_common_dispatcher_paths(monkeypatch, task=task)

    _dispatcher(tenant_id=tenant_id).execute(task_id=task.id, lease_id=uuid.uuid4())

    assert len(calls["complete"]) == 1
    assert calls["block"] == []
    assert len(calls["fail"]) == 1
    assert calls["fail"][0]["reason"] == "completion materialization failed"

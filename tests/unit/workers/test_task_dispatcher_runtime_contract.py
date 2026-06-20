from __future__ import annotations

import logging
import uuid
from typing import Any, cast
from unittest.mock import patch

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.workers import task_dispatcher
from backend.workers.task_dispatcher import TaskDispatcher, TaskHandler, TaskHandlerContext


def _task(*, task_type: object = "default") -> ExecutionTask:
    metadata: dict[str, Any] = {}
    if task_type != "missing":
        metadata["task_type"] = task_type
    return ExecutionTask(
        tenant_id=str(uuid.uuid4()),
        mission_id=uuid.uuid4(),
        title="runtime contract task",
        description="runtime contract task",
        status="running",
        metadata_json=metadata,
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _dispatcher() -> TaskDispatcher:
    return TaskDispatcher(
        session_factory=cast(Any, lambda: None),
        queue=cast(Any, object()),
        worker_id="worker-runtime-contract",
        tenant_id="tenant-runtime-contract",
    )


def _disable_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    def heartbeat_loop(self: TaskDispatcher, lease_id: uuid.UUID, stop: object) -> None:
        return None

    monkeypatch.setattr(TaskDispatcher, "_heartbeat_loop", heartbeat_loop)


def test_execute_fails_invalid_task_type_without_starting_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    lease_id = uuid.uuid4()
    reasons: list[str] = []

    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type=123))
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda self, *, lease_id, reason: reasons.append(reason),
    )
    monkeypatch.setattr(
        TaskDispatcher,
        "_complete",
        lambda *args, **kwargs: pytest.fail("invalid task_type must not complete"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {})

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=lease_id)

    assert reasons == ["task metadata task_type must be a string"]


def test_execute_fails_when_no_registered_handler_or_default(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    reasons: list[str] = []

    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type="unhandled"))
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda self, *, lease_id, reason: reasons.append(reason),
    )
    monkeypatch.setattr(
        TaskDispatcher,
        "_complete",
        lambda *args, **kwargs: pytest.fail("unhandled task must not complete"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {})

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert reasons == ["no handler registered for task_type='unhandled'"]


def test_execute_fails_invalid_handler_result_without_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    reasons: list[str] = []

    def invalid_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "bad", "status": "failed"}

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type="bad"))
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda self, *, lease_id, reason: reasons.append(reason),
    )
    monkeypatch.setattr(
        TaskDispatcher,
        "_complete",
        lambda *args, **kwargs: pytest.fail("invalid handler result must not complete"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"bad": cast(TaskHandler, invalid_handler)})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {})

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert reasons == ['task handler result status must be "completed"']


def test_execute_completes_non_persisted_result_without_serializability_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = _dispatcher()
    completions: list[dict[str, Any]] = []

    def default_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "default", "status": "completed", "transient": {object()}}

    def complete(self: TaskDispatcher, **kwargs: Any) -> None:
        completions.append(kwargs)

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type="default"))
    monkeypatch.setattr(TaskDispatcher, "_complete", complete)
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda *args, **kwargs: pytest.fail("non-persisted transient result must not fail"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"default": cast(TaskHandler, default_handler)})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {})

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert len(completions) == 1
    assert completions[0]["result"] is None
    assert completions[0]["output_reason"] is None


def test_execute_passes_persisted_output_and_reason_to_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    completions: list[dict[str, Any]] = []
    result = {"handler": "persist", "status": "completed", "value": "ok"}

    def persist_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return result

    def complete(self: TaskDispatcher, **kwargs: Any) -> None:
        completions.append(kwargs)

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type="persist"))
    monkeypatch.setattr(TaskDispatcher, "_complete", complete)
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda *args, **kwargs: pytest.fail("valid persisted result must not fail"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"persist": cast(TaskHandler, persist_handler)})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"persist": "persist completed"})

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert len(completions) == 1
    assert completions[0]["result"] == result
    assert completions[0]["output_reason"] == "persist completed"


def test_dispatcher_executes_tool_invoke_and_persists_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    task = ExecutionTask(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="tool task",
        description="tool task",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {"action": "record.search", "input": {"record_type": "account", "query": "Acme"}},
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    completed: dict[str, Any] = {}

    def complete(self: TaskDispatcher, **kwargs: Any) -> None:
        completed.update(kwargs)

    monkeypatch.setattr(TaskDispatcher, "_heartbeat_loop", lambda self, lease_id, stop: None)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(TaskDispatcher, "_complete", complete)
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, **kwargs: pytest.fail(f"unexpected fail: {kwargs}"))

    dispatcher = TaskDispatcher(
        session_factory=lambda: type("Session", (), {"close": lambda self: None})(),
        queue=object(),
        worker_id="worker",
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    assert completed["lease_id"] == lease_id
    assert completed["output_reason"] == "tool action completed"
    assert completed["result"]["handler"] == "tool.invoke"
    assert completed["result"]["output"]["count"] == 1


def test_dispatcher_fails_malformed_tool_invoke_through_failure_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid.uuid4())
    lease_id = uuid.uuid4()
    task = _task(task_type="tool.invoke")
    task.tenant_id = tenant_id
    task.metadata_json = {"task_type": "tool.invoke"}
    failures: list[str] = []

    monkeypatch.setattr(TaskDispatcher, "_heartbeat_loop", lambda self, lease_id, stop: None)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(
        TaskDispatcher, "_complete", lambda self, **kwargs: pytest.fail("malformed task should not complete")
    )
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, *, lease_id, reason: failures.append(reason))

    dispatcher = TaskDispatcher(
        session_factory=lambda: object(), queue=object(), worker_id="worker", tenant_id=tenant_id
    )
    dispatcher.execute(task_id=uuid.uuid4(), lease_id=lease_id)

    assert failures == ["tool.invoke requires metadata_json.tool_invocation object"]


def test_execute_blocks_side_effecting_tool_invoke_completion_failure_without_normal_fail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    task = _task(task_type="tool.invoke")
    task.id = task_id
    task.tenant_id = tenant_id
    handler_calls = 0
    blocked: list[dict[str, Any]] = []

    def side_effecting_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        nonlocal handler_calls
        handler_calls += 1
        return {
            "handler": "tool.invoke",
            "status": "completed",
            "schema_version": 1,
            "action": "calendar.create_event",
            "provider": "google_calendar",
            "side_effect_class": "external_write",
            "output": {"event_id": "evt-1"},
            "evidence": [],
            "records_inspected": [],
            "records_changed": ["evt-1"],
            "summary": "created event",
        }

    def complete_raises(self: TaskDispatcher, **kwargs: Any) -> None:
        raise RuntimeError("completion evidence write failed")

    def block_completion_failure(self: TaskDispatcher, **kwargs: Any) -> None:
        blocked.append(kwargs)

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(TaskDispatcher, "_complete", complete_raises)
    monkeypatch.setattr(TaskDispatcher, "_block_completion_failure", block_completion_failure)
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, **kwargs: pytest.fail(f"unexpected fail: {kwargs}"))
    monkeypatch.setattr(
        task_dispatcher, "_HANDLER_REGISTRY", {"tool.invoke": cast(TaskHandler, side_effecting_handler)}
    )
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"tool.invoke": "tool action completed"})

    dispatcher = TaskDispatcher(
        session_factory=lambda: object(),
        queue=object(),
        worker_id="worker",
        tenant_id=tenant_id,
    )

    # Ensure logger state is clean (some prior tests in the suite configure logging or set propagate)
    side_effect_logger = logging.getLogger("ajenda.task_dispatcher")
    side_effect_logger.propagate = True
    side_effect_logger.setLevel(logging.NOTSET)

    captured_critical: list[dict[str, Any]] = []

    def _capture_critical(msg: str, *args: Any, **kwargs: Any) -> None:
        if msg == "task_dispatch_completion_failed_after_side_effect":
            extra = kwargs.get("extra", {})
            captured_critical.append(extra)
        # call original so other logging works if needed
        original_critical(msg, *args, **kwargs)

    side_logger = task_dispatcher.logger
    original_critical = side_logger.critical

    with patch.object(side_logger, "critical", _capture_critical):
        dispatcher.execute(task_id=task_id, lease_id=lease_id)

    assert handler_calls == 1
    assert blocked == [
        {
            "lease_id": lease_id,
            "task_id": task_id,
            "task_type": "tool.invoke",
            "side_effect_class": "external_write",
            "reason": "completion evidence write failed",
        }
    ]
    assert len(captured_critical) == 1
    rec = captured_critical[0]
    assert rec["task_id"] == str(task_id)
    assert rec["lease_id"] == str(lease_id)
    assert rec["task_type"] == "tool.invoke"
    assert rec["side_effect_class"] == "external_write"


def test_execute_preserves_normal_failure_for_handler_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    failures: list[str] = []

    def exploding_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        raise RuntimeError("handler exploded")

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: _task(task_type="explode"))
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"explode": cast(TaskHandler, exploding_handler)})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {})
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, *, lease_id, reason: failures.append(reason))
    monkeypatch.setattr(
        TaskDispatcher,
        "_block_completion_failure",
        lambda *args, **kwargs: pytest.fail("handler failure must not use completion-failure block path"),
    )
    monkeypatch.setattr(
        TaskDispatcher,
        "_complete",
        lambda *args, **kwargs: pytest.fail("handler exception must not complete"),
    )

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert failures == ["handler exploded"]


def test_execute_preserves_normal_failure_for_non_side_effecting_tool_completion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(task_type="tool.invoke")
    task.tenant_id = tenant_id
    failures: list[str] = []

    def read_only_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {
            "handler": "tool.invoke",
            "status": "completed",
            "schema_version": 1,
            "action": "record.search",
            "provider": "local_records",
            "side_effect_class": "internal_read",
            "output": {"count": 1},
            "evidence": [],
            "records_inspected": ["acct-1"],
            "records_changed": [],
            "summary": "searched records",
        }

    def complete_raises(self: TaskDispatcher, **kwargs: Any) -> None:
        raise RuntimeError("completion failed")

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(TaskDispatcher, "_complete", complete_raises)
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, *, lease_id, reason: failures.append(reason))
    monkeypatch.setattr(
        TaskDispatcher,
        "_block_completion_failure",
        lambda *args, **kwargs: pytest.fail("read-only completion failure should follow existing fail path"),
    )
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", {"tool.invoke": cast(TaskHandler, read_only_handler)})
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {"tool.invoke": "tool action completed"})

    dispatcher = TaskDispatcher(
        session_factory=lambda: object(),
        queue=object(),
        worker_id="worker",
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert failures == ["completion failed"]

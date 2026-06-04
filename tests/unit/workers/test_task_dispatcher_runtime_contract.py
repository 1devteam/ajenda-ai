from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

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
    dispatcher.session_factory = lambda: SimpleNamespace(close=lambda: None)
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
    dispatcher.session_factory = lambda: SimpleNamespace(close=lambda: None)
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
    dispatcher.session_factory = lambda: SimpleNamespace(close=lambda: None)
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


def test_execute_completes_tool_invoke_and_persists_result(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    dispatcher.session_factory = lambda: SimpleNamespace(close=lambda: None)
    completions: list[dict[str, Any]] = []
    task = _task(task_type="tool.invoke")
    task.metadata_json["tool_invocation"] = {"action": "record.search", "input": {"record_type": "lead"}}
    task.tenant_id = dispatcher.tenant_id

    def complete(self: TaskDispatcher, **kwargs: Any) -> None:
        completions.append(kwargs)

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(TaskDispatcher, "_complete", complete)
    monkeypatch.setattr(
        TaskDispatcher,
        "_fail",
        lambda *args, **kwargs: pytest.fail("valid tool.invoke task must not fail"),
    )

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert len(completions) == 1
    assert completions[0]["output_reason"] == "tool action completed"
    assert completions[0]["result"]["handler"] == "tool.invoke"
    assert completions[0]["result"]["action"] == "record.search"


def test_execute_fails_malformed_tool_invoke_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _dispatcher()
    dispatcher.session_factory = lambda: SimpleNamespace(close=lambda: None)
    reasons: list[str] = []
    task = _task(task_type="tool.invoke")
    task.tenant_id = dispatcher.tenant_id
    task.metadata_json["tool_invocation"] = {"action": "record.search", "input": {"record_type": "invoice"}}

    _disable_heartbeat(monkeypatch)
    monkeypatch.setattr(TaskDispatcher, "_load_task", lambda self, task_id: task)
    monkeypatch.setattr(TaskDispatcher, "_fail", lambda self, *, lease_id, reason: reasons.append(reason))
    monkeypatch.setattr(
        TaskDispatcher,
        "_complete",
        lambda *args, **kwargs: pytest.fail("invalid tool.invoke must not complete"),
    )

    dispatcher.execute(task_id=uuid.uuid4(), lease_id=uuid.uuid4())

    assert reasons == ["unsupported record type: invoice"]

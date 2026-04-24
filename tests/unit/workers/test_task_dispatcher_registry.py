from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.workers import task_dispatcher
from backend.workers.task_dispatcher import TaskHandlerContext, register_handler


def _task(*, task_type: object = "default") -> ExecutionTask:
    metadata: dict[str, Any] = {}
    if task_type != "missing":
        metadata["task_type"] = task_type
    return ExecutionTask(
        tenant_id=str(uuid.uuid4()),
        mission_id=uuid.uuid4(),
        title="registry task",
        description="registry task",
        status="running",
        metadata_json=metadata,
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def test_register_handler_rejects_blank_task_type() -> None:
    with pytest.raises(ValueError, match="task_type must be a non-empty string"):
        register_handler("   ")


def test_register_handler_rejects_duplicate_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    registry: dict[str, task_dispatcher.TaskHandler] = {}
    output_types: set[str] = set()
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", registry)
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_PERSISTING_TASK_TYPES", output_types)

    def first_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "first"}

    def second_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "second"}

    register_handler("custom")(first_handler)

    with pytest.raises(ValueError, match="task handler already registered"):
        register_handler("custom")(second_handler)

    assert registry["custom"] is first_handler


def test_register_handler_tracks_output_persisting_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    registry: dict[str, task_dispatcher.TaskHandler] = {}
    output_types: set[str] = set()
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", registry)
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_PERSISTING_TASK_TYPES", output_types)

    def handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "output"}

    register_handler("output-task", persists_output=True)(handler)

    assert registry["output-task"] is handler
    assert output_types == {"output-task"}


def test_task_type_for_task_defaults_when_missing() -> None:
    task = _task(task_type="missing")

    assert task_dispatcher._task_type_for_task(task) == "default"


def test_task_type_for_task_normalizes_metadata_value() -> None:
    task = _task(task_type="  echo  ")

    assert task_dispatcher._task_type_for_task(task) == "echo"


def test_task_type_for_task_rejects_blank_metadata_value() -> None:
    task = _task(task_type="   ")

    with pytest.raises(ValueError, match="task_type must be a non-empty string"):
        task_dispatcher._task_type_for_task(task)


def test_task_type_for_task_rejects_non_string_metadata_value() -> None:
    task = _task(task_type=123)

    with pytest.raises(ValueError, match="task metadata task_type must be a string"):
        task_dispatcher._task_type_for_task(task)

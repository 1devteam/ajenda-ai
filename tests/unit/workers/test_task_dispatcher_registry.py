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


def test_register_handler_rejects_blank_output_reason() -> None:
    with pytest.raises(ValueError, match="output_reason must be a non-empty string"):
        register_handler("custom", output_reason="   ")


def test_register_handler_rejects_duplicate_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    registry: dict[str, task_dispatcher.TaskHandler] = {}
    output_reasons: dict[str, str] = {}
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", registry)
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", output_reasons)

    def first_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "first"}

    def second_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "second"}

    register_handler("custom")(first_handler)

    with pytest.raises(ValueError, match="task handler already registered"):
        register_handler("custom")(second_handler)

    assert registry["custom"] is first_handler


def test_register_handler_tracks_output_reason_by_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    registry: dict[str, task_dispatcher.TaskHandler] = {}
    output_reasons: dict[str, str] = {}
    monkeypatch.setattr(task_dispatcher, "_HANDLER_REGISTRY", registry)
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", output_reasons)

    def handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "output"}

    register_handler("output-task", output_reason="output task completed")(handler)

    assert registry["output-task"] is handler
    assert output_reasons == {"output-task": "output task completed"}


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


def test_validate_handler_result_accepts_canonical_completed_result() -> None:
    assert task_dispatcher._validate_handler_result({"handler": "echo", "status": "completed"}) == {
        "handler": "echo",
        "status": "completed",
    }


@pytest.mark.parametrize("result", [None, [], "completed"])
def test_validate_handler_result_rejects_non_object_result(result: object) -> None:
    with pytest.raises(ValueError, match="task handler must return a result object"):
        task_dispatcher._validate_handler_result(result)


def test_validate_handler_result_rejects_non_string_keys() -> None:
    with pytest.raises(ValueError, match="task handler result keys must be strings"):
        task_dispatcher._validate_handler_result({"handler": "echo", "status": "completed", 1: "bad"})


@pytest.mark.parametrize(
    "result",
    [
        {"status": "completed"},
        {"handler": "", "status": "completed"},
        {"handler": 123, "status": "completed"},
    ],
)
def test_validate_handler_result_requires_non_empty_handler(result: object) -> None:
    with pytest.raises(ValueError, match='must include non-empty "handler"'):
        task_dispatcher._validate_handler_result(result)


@pytest.mark.parametrize(
    "result",
    [
        {"handler": "echo"},
        {"handler": "echo", "status": ""},
        {"handler": "echo", "status": 123},
    ],
)
def test_validate_handler_result_requires_non_empty_status(result: object) -> None:
    with pytest.raises(ValueError, match='must include non-empty "status"'):
        task_dispatcher._validate_handler_result(result)


@pytest.mark.parametrize("status", ["blocked", "failed", " complete ", "unknown"])
def test_validate_handler_result_rejects_non_completed_status(status: str) -> None:
    with pytest.raises(ValueError, match='status must be "completed"'):
        task_dispatcher._validate_handler_result({"handler": "echo", "status": status})


def test_validate_handler_result_allows_non_json_serializable_non_persisted_payload() -> None:
    assert (
        task_dispatcher._validate_handler_result(
            {"handler": "default", "status": "completed", "transient": {object()}},
            require_json_serializable=False,
        )["handler"]
        == "default"
    )


def test_validate_handler_result_rejects_non_json_serializable_persisted_payload() -> None:
    with pytest.raises(ValueError, match="must be JSON serializable"):
        task_dispatcher._validate_handler_result(
            {"handler": "echo", "status": "completed", "bad": {object()}},
            require_json_serializable=True,
        )

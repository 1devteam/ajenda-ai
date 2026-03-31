import pytest

from backend.runtime.state_machine import InvalidTransitionError, StateMachine
from backend.runtime.transitions import transition_task
from backend.domain.execution_task import ExecutionTask


def test_valid_task_transition_passes() -> None:
    StateMachine.ensure_task_transition("planned", "queued")


def test_invalid_task_transition_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        StateMachine.ensure_task_transition("planned", "completed")


def test_valid_fleet_transition_passes() -> None:
    StateMachine.ensure_fleet_transition("planned", "provisioning")


def test_transition_helper_mutates_via_validator() -> None:
    task = ExecutionTask(tenant_id="tenant-a", mission_id=None, title="x", description="y")  # type: ignore[arg-type]
    transition_task(task, __import__("backend.domain.enums", fromlist=["ExecutionTaskState"]).ExecutionTaskState.QUEUED)
    assert task.status == "queued"

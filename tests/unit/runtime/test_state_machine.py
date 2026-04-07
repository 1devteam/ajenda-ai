"""Unit tests for StateMachine and transition helpers."""
from __future__ import annotations

import pytest
from backend.runtime.state_machine import InvalidTransitionError, StateMachine
from backend.runtime.transitions import transition_task
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.enums import ExecutionTaskState


def test_valid_task_transition_passes() -> None:
    """planned -> queued is a valid task transition."""
    StateMachine.ensure_task_transition("planned", "queued")


def test_invalid_task_transition_raises() -> None:
    """planned -> completed is an invalid task transition."""
    with pytest.raises(InvalidTransitionError):
        StateMachine.ensure_task_transition("planned", "completed")


def test_valid_fleet_transition_passes() -> None:
    """planned -> provisioning is a valid fleet transition."""
    StateMachine.ensure_fleet_transition("planned", "provisioning")


def test_transition_helper_mutates_via_validator() -> None:
    """transition_task updates the task status field via the state machine."""
    task = ExecutionTask(
        tenant_id="tenant-a",
        mission_id=None,  # type: ignore[arg-type]
        title="x",
        description="y",
        status=ExecutionTaskState.PLANNED.value,  # explicit — SQLAlchemy defaults are flush-time only
    )
    transition_task(task, ExecutionTaskState.QUEUED)
    assert task.status == "queued"


def test_recovering_transitions_are_registered() -> None:
    """running -> recovering and recovering -> queued are valid transitions."""
    StateMachine.ensure_task_transition("running", "recovering")
    StateMachine.ensure_task_transition("recovering", "queued")
    StateMachine.ensure_task_transition("recovering", "dead_lettered")


def test_recovering_to_completed_is_invalid() -> None:
    """recovering -> completed is not a valid transition."""
    with pytest.raises(InvalidTransitionError):
        StateMachine.ensure_task_transition("recovering", "completed")

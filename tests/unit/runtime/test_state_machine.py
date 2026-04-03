"""Unit tests for StateMachine and transition helpers.

SQLAlchemy column defaults only fire on DB INSERT, not Python __init__.
Tests that exercise transition logic must set status explicitly.
"""
from __future__ import annotations
import pytest
from backend.runtime.state_machine import InvalidTransitionError, StateMachine
from backend.runtime.transitions import transition_task
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask


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


def test_transition_helper_mutates_task_status() -> None:
    """transition_task() validates the transition and mutates task.status."""
    # Must set status explicitly — SQLAlchemy defaults only fire on DB INSERT.
    task = ExecutionTask(
        tenant_id="tenant-a",
        mission_id=None,  # type: ignore[arg-type]
        title="x",
        description="y",
        status=ExecutionTaskState.PLANNED.value,
    )
    transition_task(task, ExecutionTaskState.QUEUED)
    assert task.status == "queued"


def test_transition_helper_rejects_invalid_transition() -> None:
    """transition_task() raises InvalidTransitionError on an illegal transition."""
    task = ExecutionTask(
        tenant_id="tenant-a",
        mission_id=None,  # type: ignore[arg-type]
        title="x",
        description="y",
        status=ExecutionTaskState.PLANNED.value,
    )
    with pytest.raises(InvalidTransitionError):
        transition_task(task, ExecutionTaskState.COMPLETED)


def test_recovering_is_reachable_from_running() -> None:
    """running -> recovering is a valid transition (Phase 3 addition)."""
    StateMachine.ensure_task_transition("running", "recovering")


def test_recovering_can_return_to_queued() -> None:
    """recovering -> queued is a valid transition for retry after recovery."""
    StateMachine.ensure_task_transition("recovering", "queued")

from __future__ import annotations

from backend.runtime.state_machine import StateMachine


def test_claimed_to_queued_is_legal() -> None:
    StateMachine.ensure_task_transition("claimed", "queued")


def test_running_to_recovering_to_queued_is_legal() -> None:
    StateMachine.ensure_task_transition("running", "recovering")
    StateMachine.ensure_task_transition("recovering", "queued")


def test_recovering_to_dead_lettered_is_legal() -> None:
    StateMachine.ensure_task_transition("recovering", "dead_lettered")

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.runtime.transitions import (
    transition_agent,
    transition_branch,
    transition_fleet,
    transition_lease,
    transition_task,
)


def test_transition_task_updates_status(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_ensure(current: str, target: str) -> None:
        calls.append((current, target))

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_task_transition", _fake_ensure)

    task = SimpleNamespace(status="queued")
    result = transition_task(task, SimpleNamespace(value="running"))

    assert result is task
    assert task.status == "running"
    assert calls == [("queued", "running")]


def test_transition_fleet_updates_status(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_ensure(current: str, target: str) -> None:
        calls.append((current, target))

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_fleet_transition", _fake_ensure)

    fleet = SimpleNamespace(status="idle")
    result = transition_fleet(fleet, SimpleNamespace(value="active"))

    assert result is fleet
    assert fleet.status == "active"
    assert calls == [("idle", "active")]


def test_transition_agent_updates_status(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_ensure(current: str, target: str) -> None:
        calls.append((current, target))

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_agent_transition", _fake_ensure)

    agent = SimpleNamespace(status="idle")
    result = transition_agent(agent, SimpleNamespace(value="busy"))

    assert result is agent
    assert agent.status == "busy"
    assert calls == [("idle", "busy")]


def test_transition_branch_updates_status(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_ensure(current: str, target: str) -> None:
        calls.append((current, target))

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_branch_transition", _fake_ensure)

    branch = SimpleNamespace(status="queued")
    result = transition_branch(branch, SimpleNamespace(value="running"))

    assert result is branch
    assert branch.status == "running"
    assert calls == [("queued", "running")]


def test_transition_lease_updates_status(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_ensure(current: str, target: str) -> None:
        calls.append((current, target))

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_lease_transition", _fake_ensure)

    lease = SimpleNamespace(status="active")
    result = transition_lease(lease, SimpleNamespace(value="expired"))

    assert result is lease
    assert lease.status == "expired"
    assert calls == [("active", "expired")]


def test_transition_task_propagates_invalid_transition(monkeypatch) -> None:
    def _boom(current: str, target: str) -> None:
        raise ValueError("invalid transition")

    monkeypatch.setattr("backend.runtime.transitions.StateMachine.ensure_task_transition", _boom)

    task = SimpleNamespace(status="queued")

    with pytest.raises(ValueError, match="invalid transition"):
        transition_task(task, SimpleNamespace(value="completed"))

    assert task.status == "queued"

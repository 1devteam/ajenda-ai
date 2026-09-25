from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.workers import worker_loop
from backend.workers.worker_loop import WorkerLoop


class SessionStub:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _loop(*, session: SessionStub | None = None) -> WorkerLoop:
    session = session or SessionStub()
    return WorkerLoop(
        session_factory=cast(Any, lambda: session),
        queue=cast(Any, object()),
        worker_id="worker-loop-contract",
        tenant_id="tenant-loop-contract",
        poll_interval_seconds=0.01,
    )


def test_claim_and_start_returns_none_when_queue_has_no_task(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def claim_next_task(self, *, tenant_id: str, worker_id: str) -> None:
            return None

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    assert loop._claim_and_start_task() is None
    assert session.rolled_back is True
    assert session.closed is True


def test_worker_loop_runs_bounded_tenant_scoped_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    object.__setattr__(loop, "_last_recovery", 0.0)
    calls: list[str] = []

    class MaintainerStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            calls.append("init")

        def recover_expired_leases(self) -> SimpleNamespace:
            calls.append("recover")
            return SimpleNamespace(expired_lease_count=1, requeued_task_count=1, dead_lettered_count=0)

    monkeypatch.setattr(worker_loop, "RuntimeMaintainer", MaintainerStub)
    monkeypatch.setattr(worker_loop.time, "monotonic", lambda: 100.0)

    loop._maybe_recover_expired_leases("tenant-loop-contract")

    assert calls == ["init", "recover"]
    assert session.closed is True


def test_claim_and_start_heartbeats_and_starts_claimed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    calls: list[str] = []

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def claim_next_task(self, *, tenant_id: str, worker_id: str) -> object:
            calls.append(f"claim:{tenant_id}:{worker_id}")
            return SimpleNamespace(id=task_id, metadata_json={"worker_lease_id": str(lease_id)})

        def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            calls.append(f"heartbeat:{tenant_id}:{lease_id}:{worker_id}")

        def start_execution(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            calls.append(f"start:{tenant_id}:{lease_id}:{worker_id}")

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    assert loop._claim_and_start_task() == (task_id, lease_id)
    assert calls == [
        "claim:tenant-loop-contract:worker-loop-contract",
        f"heartbeat:tenant-loop-contract:{lease_id}:worker-loop-contract",
        f"start:tenant-loop-contract:{lease_id}:worker-loop-contract",
    ]
    assert session.committed is True
    assert session.closed is True


def test_claim_and_start_returns_none_on_missing_lease_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def claim_next_task(self, *, tenant_id: str, worker_id: str) -> object:
            return SimpleNamespace(id=uuid.uuid4(), metadata_json={})

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    assert loop._claim_and_start_task() is None
    assert session.rolled_back is True
    assert session.closed is True


def test_run_claimed_task_delegates_to_task_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    class DispatcherStub:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["worker_id"] == "worker-loop-contract"
            assert kwargs["tenant_id"] == "tenant-loop-contract"

        def execute(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
            calls.append((task_id, lease_id))

    monkeypatch.setattr(worker_loop, "TaskDispatcher", DispatcherStub)
    monkeypatch.setattr(
        WorkerLoop,
        "_fail_once",
        lambda *args, **kwargs: pytest.fail("dispatcher success must not call fail compensation"),
    )

    loop._run_claimed_task(task_id=task_id, lease_id=lease_id)

    assert calls == [(task_id, lease_id)]


def test_run_claimed_task_compensates_when_dispatcher_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    failures: list[tuple[uuid.UUID, str]] = []

    class DispatcherStub:
        def __init__(self, **kwargs: object) -> None:
            pass

        def execute(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
            raise RuntimeError("dispatcher exploded")

    monkeypatch.setattr(worker_loop, "TaskDispatcher", DispatcherStub)
    monkeypatch.setattr(
        WorkerLoop,
        "_fail_once",
        lambda self, *, lease_id, reason: failures.append((lease_id, reason)),
    )

    loop._run_claimed_task(task_id=task_id, lease_id=lease_id)

    assert failures == [(lease_id, "dispatcher exploded")]


def test_fail_once_calls_runtime_fail_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    lease_id = uuid.uuid4()
    calls: list[tuple[str, uuid.UUID, str, str]] = []

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def fail(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str, reason: str) -> None:
            calls.append((tenant_id, lease_id, worker_id, reason))

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    loop._fail_once(lease_id=lease_id, reason="dispatcher exploded")

    assert calls == [("tenant-loop-contract", lease_id, "worker-loop-contract", "dispatcher exploded")]
    assert session.committed is True
    assert session.closed is True


def test_fail_once_rolls_back_when_runtime_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def fail(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str, reason: str) -> None:
            raise RuntimeError("fail rejected")

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    loop._fail_once(lease_id=uuid.uuid4(), reason="dispatcher exploded")

    assert session.rolled_back is True
    assert session.closed is True


def test_claim_and_start_releases_unstarted_claim_when_heartbeat_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    releases: list[tuple[uuid.UUID, str]] = []

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def claim_next_task(self, *, tenant_id: str, worker_id: str) -> object:
            return SimpleNamespace(id=task_id, metadata_json={"worker_lease_id": str(lease_id)})

        def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            raise RuntimeError("queue heartbeat rejected")

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)
    monkeypatch.setattr(
        WorkerLoop,
        "_release_unstarted_claim_once",
        lambda self, *, lease_id, reason: releases.append((lease_id, reason)),
    )

    assert loop._claim_and_start_task() is None

    assert session.rolled_back is True
    assert releases == [(lease_id, "queue heartbeat rejected")]


def test_claim_and_start_does_not_release_after_successful_start_if_late_commit_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CommitRaisingSession(SessionStub):
        def commit(self) -> None:
            self.committed = True
            raise RuntimeError("late commit failed")

    session = CommitRaisingSession()
    loop = _loop(session=session)
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def claim_next_task(self, *, tenant_id: str, worker_id: str) -> object:
            return SimpleNamespace(id=task_id, metadata_json={"worker_lease_id": str(lease_id)})

        def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            return None

        def start_execution(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            return None

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)
    monkeypatch.setattr(
        WorkerLoop,
        "_release_unstarted_claim_once",
        lambda *args, **kwargs: pytest.fail("started tasks must not be requeued by claim/start compensation"),
    )

    assert loop._claim_and_start_task() is None

    assert session.committed is True
    assert session.rolled_back is True


def test_release_unstarted_claim_once_calls_runtime_release_and_keeps_loop_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    lease_id = uuid.uuid4()
    calls: list[tuple[str, uuid.UUID, str]] = []

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def release(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            calls.append((tenant_id, lease_id, worker_id))

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    loop._release_unstarted_claim_once(lease_id=lease_id, reason="heartbeat failed")

    assert calls == [("tenant-loop-contract", lease_id, "worker-loop-contract")]
    assert session.committed is True
    assert session.closed is True


def test_release_unstarted_claim_once_fails_closed_when_runtime_rejects_stale_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SessionStub()
    loop = _loop(session=session)
    lease_id = uuid.uuid4()
    attempted: list[uuid.UUID] = []

    class RuntimeStub:
        def __init__(self, session_arg: object, queue_arg: object) -> None:
            pass

        def release(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> None:
            attempted.append(lease_id)
            raise ValueError("lease is not current task claim")

    monkeypatch.setattr(worker_loop, "WorkerRuntimeService", RuntimeStub)

    loop._release_unstarted_claim_once(lease_id=lease_id, reason="late heartbeat failure")

    assert attempted == [lease_id]
    assert session.rolled_back is True
    assert session.committed is False
    assert session.closed is True

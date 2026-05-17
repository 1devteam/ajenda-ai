from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.system_status_service import SystemStatusService


class _FakeDatabaseRuntime:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        return self.ready


class _FakeQueue:
    def __init__(self, *, ready: bool = True, fails: bool = False) -> None:
        self.ready = ready
        self.fails = fails
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        if self.fails:
            raise RuntimeError("redis://:secret@redis:6379/0")
        return self.ready


def test_health_is_lightweight_and_does_not_probe_dependencies() -> None:
    session = MagicMock()
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue()

    result = SystemStatusService(session=session, database_runtime=database_runtime, queue_adapter=queue).health()

    assert result == {"database": "unchecked", "runtime": "ok", "queue": "unchecked"}
    session.execute.assert_not_called()
    assert database_runtime.pings == 0
    assert queue.pings == 0


def test_readiness_reports_ready_when_database_and_queue_ping() -> None:
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue()

    result = SystemStatusService(database_runtime=database_runtime, queue_adapter=queue).readiness()

    assert result == {"database": "ready", "queue": "ready", "dependencies": "ready"}
    assert database_runtime.pings == 1
    assert queue.pings == 1


@pytest.mark.parametrize(
    ("database_runtime", "queue", "expected"),
    (
        (
            _FakeDatabaseRuntime(ready=False),
            _FakeQueue(),
            {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"},
        ),
        (
            _FakeDatabaseRuntime(),
            _FakeQueue(ready=False),
            {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"},
        ),
        (
            _FakeDatabaseRuntime(),
            _FakeQueue(fails=True),
            {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"},
        ),
        (None, _FakeQueue(), {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}),
        (_FakeDatabaseRuntime(), None, {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"}),
    ),
)
def test_readiness_reports_sanitized_dependency_failures(database_runtime, queue, expected) -> None:
    assert SystemStatusService(database_runtime=database_runtime, queue_adapter=queue).readiness() == expected


def test_status_requires_session() -> None:
    with pytest.raises(RuntimeError, match="requires a database session"):
        SystemStatusService(session=None).status(tenant_id="tenant-a")

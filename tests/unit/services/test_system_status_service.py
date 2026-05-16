from __future__ import annotations

from backend.services.system_status_service import SystemStatusService


class _FakeDatabaseRuntime:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        return self.ready


class _FakeSession:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        return None


class _FakeQueue:
    def __init__(self, *, ready: bool = True, fails: bool = False) -> None:
        self.ready = ready
        self.fails = fails
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        if self.fails:
            raise RuntimeError("queue failure redis://:pass@redis:6379/0")
        return self.ready


def test_service_class_exists() -> None:
    assert SystemStatusService is not None


def test_health_is_lightweight_and_does_not_probe_dependencies() -> None:
    database_runtime = _FakeDatabaseRuntime(ready=False)
    session = _FakeSession()
    queue = _FakeQueue(fails=True)

    result = SystemStatusService(session=session, database_runtime=database_runtime, queue_adapter=queue).health()

    assert result == {"database": "unchecked", "runtime": "ok", "queue": "unchecked"}
    assert database_runtime.pings == 0
    assert session.calls == 0
    assert queue.pings == 0


def test_readiness_reports_ready_when_database_and_queue_are_ready() -> None:
    database_runtime = _FakeDatabaseRuntime()
    session = _FakeSession()
    queue = _FakeQueue()

    result = SystemStatusService(session=session, database_runtime=database_runtime, queue_adapter=queue).readiness()

    assert result == {"database": "ready", "queue": "ready", "dependencies": "ready"}
    assert database_runtime.pings == 1
    assert session.calls == 0
    assert queue.pings == 1


def test_readiness_reports_database_failure_without_exception_details() -> None:
    database_runtime = _FakeDatabaseRuntime(ready=False)
    session = _FakeSession()

    result = SystemStatusService(session=session, database_runtime=database_runtime, queue_adapter=_FakeQueue()).readiness()

    assert result == {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}
    assert database_runtime.pings == 1
    assert session.calls == 0
    assert "postgresql://" not in str(result)


def test_readiness_reports_queue_failure_without_exception_details() -> None:
    result = SystemStatusService(database_runtime=_FakeDatabaseRuntime(), queue_adapter=_FakeQueue(fails=True)).readiness()

    assert result == {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"}
    assert "redis://" not in str(result)

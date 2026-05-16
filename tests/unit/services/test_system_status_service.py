from __future__ import annotations

from backend.db.session import SKIP_COMMIT_SESSION_INFO_KEY
from backend.services.system_status_service import SystemStatusService


class _FakeSession:
    def __init__(self, *, fails: bool = False, rollback_fails: bool = False) -> None:
        self.fails = fails
        self.rollback_fails = rollback_fails
        self.calls = 0
        self.rollbacks = 0
        self.info: dict[str, bool] = {}

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.fails:
            raise RuntimeError("database failure postgresql://user:pass@db/name")
        return None

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.rollback_fails:
            raise RuntimeError("rollback failure postgresql://user:pass@db/name")


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
    session = _FakeSession(fails=True)
    queue = _FakeQueue(fails=True)

    result = SystemStatusService(session, queue).health()

    assert result == {"database": "unchecked", "runtime": "ok", "queue": "unchecked"}
    assert session.calls == 0
    assert queue.pings == 0


def test_readiness_reports_ready_when_database_and_queue_are_ready() -> None:
    session = _FakeSession()
    queue = _FakeQueue()

    result = SystemStatusService(session, queue).readiness()

    assert result == {"database": "ready", "queue": "ready", "dependencies": "ready"}
    assert session.calls == 1
    assert session.rollbacks == 0
    assert SKIP_COMMIT_SESSION_INFO_KEY not in session.info
    assert queue.pings == 1


def test_readiness_reports_database_failure_without_exception_details() -> None:
    session = _FakeSession(fails=True)

    result = SystemStatusService(session, _FakeQueue()).readiness()

    assert result == {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}
    assert session.rollbacks == 1
    assert session.info[SKIP_COMMIT_SESSION_INFO_KEY] is True
    assert "postgresql://" not in str(result)


def test_readiness_suppresses_rollback_failure_without_exception_details() -> None:
    session = _FakeSession(fails=True, rollback_fails=True)

    result = SystemStatusService(session, _FakeQueue()).readiness()

    assert result == {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}
    assert session.rollbacks == 1
    assert session.info[SKIP_COMMIT_SESSION_INFO_KEY] is True
    assert "postgresql://" not in str(result)


def test_readiness_reports_queue_failure_without_exception_details() -> None:
    result = SystemStatusService(_FakeSession(), _FakeQueue(fails=True)).readiness()

    assert result == {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"}
    assert "redis://" not in str(result)

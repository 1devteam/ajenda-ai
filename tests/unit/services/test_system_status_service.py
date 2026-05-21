from __future__ import annotations

from backend.services.system_status_service import SystemStatusService


class _HealthyDependency:
    def ping(self) -> bool:
        return True


class _UnhealthyDependency:
    def ping(self) -> bool:
        return False


class _ExplodingDependency:
    def ping(self) -> bool:
        raise RuntimeError("redis://secret@host")


class _MissingPingDependency:
    pass


def test_health_is_lightweight_liveness() -> None:
    assert SystemStatusService(session=None).health() == {"status": "ok"}


def test_readiness_reports_component_truth_when_dependencies_ready() -> None:
    payload = SystemStatusService(session=None).readiness(
        database_runtime=_HealthyDependency(),
        queue_adapter=_HealthyDependency(),
    )

    assert payload == {
        "status": "ready",
        "dependencies": {"database": {"status": "ready"}, "queue": {"status": "ready"}},
        "reason": None,
    }


def test_readiness_sanitizes_failures() -> None:
    payload = SystemStatusService(session=None).readiness(
        database_runtime=_ExplodingDependency(),
        queue_adapter=_UnhealthyDependency(),
    )

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "DEPENDENCY_UNAVAILABLE"
    assert payload["dependencies"] == {
        "database": {"status": "unavailable", "reason": "DATABASE_UNAVAILABLE"},
        "queue": {"status": "unavailable", "reason": "QUEUE_UNAVAILABLE"},
    }
    assert "redis://" not in str(payload)


def test_readiness_fails_closed_when_dependency_missing_or_invalid() -> None:
    payload = SystemStatusService(session=None).readiness(
        database_runtime=None,
        queue_adapter=_MissingPingDependency(),
    )
    assert payload == {
        "status": "unavailable",
        "dependencies": {
            "database": {"status": "unavailable", "reason": "DATABASE_UNAVAILABLE"},
            "queue": {"status": "unavailable", "reason": "QUEUE_UNAVAILABLE"},
        },
        "reason": "DEPENDENCY_UNAVAILABLE",
    }

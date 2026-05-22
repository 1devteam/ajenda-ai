from unittest.mock import Mock

from backend.metrics.prometheus_exporter import readiness_dependency_samples
from backend.services.system_status_service import SystemStatusService


def _readiness_values() -> dict[str, int]:
    return dict(readiness_dependency_samples())


def test_metrics_default_to_unavailable_before_readiness() -> None:
    values = _readiness_values()
    assert values["database"] == 0
    assert values["queue"] == 0


def test_service_class_exists() -> None:
    assert SystemStatusService is not None


def test_health_is_liveness_only() -> None:
    service = SystemStatusService(session=None)
    assert service.health() == {"status": "ok"}


def test_readiness_ready_when_dependencies_ping() -> None:
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = True

    status_code, payload = SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert status_code == 200
    assert payload == {
        "status": "ready",
        "dependencies": {
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
        },
    }


def test_readiness_unavailable_when_database_fails() -> None:
    db = Mock()
    db.ping.return_value = False
    queue = Mock()
    queue.ping.return_value = True

    status_code, payload = SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "DATABASE_UNAVAILABLE"


def test_readiness_unavailable_when_queue_fails() -> None:
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = False

    status_code, payload = SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "QUEUE_UNAVAILABLE"


def test_readiness_skips_none_dependencies() -> None:
    status_code, payload = SystemStatusService(session=None).readiness(database_runtime=None, queue_adapter=None)

    assert status_code == 200
    assert payload == {
        "status": "ready",
        "dependencies": {
            "database": {"status": "skipped"},
            "queue": {"status": "skipped"},
        },
    }


def test_readiness_metrics_set_ready_when_dependencies_ready() -> None:
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = True

    SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert _readiness_values()["database"] == 1
    assert _readiness_values()["queue"] == 1


def test_readiness_metrics_set_database_unavailable_to_zero() -> None:
    db = Mock()
    db.ping.return_value = False
    queue = Mock()
    queue.ping.return_value = True

    SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert _readiness_values()["database"] == 0
    assert _readiness_values()["queue"] == 1


def test_readiness_metrics_set_queue_unavailable_to_zero() -> None:
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = False

    SystemStatusService(session=None).readiness(database_runtime=db, queue_adapter=queue)

    assert _readiness_values()["database"] == 1
    assert _readiness_values()["queue"] == 0


def test_readiness_metrics_treat_skipped_dependencies_as_ready() -> None:
    SystemStatusService(session=None).readiness(database_runtime=None, queue_adapter=None)

    assert _readiness_values()["database"] == 1
    assert _readiness_values()["queue"] == 1

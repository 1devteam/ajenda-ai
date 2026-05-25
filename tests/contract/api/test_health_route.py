from unittest.mock import Mock

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.metrics.prometheus_exporter import readiness_dependency_samples


class _FailIfCalled:
    def ping(self) -> bool:
        raise AssertionError("dependency ping should not be called for health")


def test_health_route_returns_ok() -> None:
    app = create_app()
    app.state.database_runtime = _FailIfCalled()
    app.state.queue_adapter = _FailIfCalled()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_readiness_dependency_failure() -> None:
    app = create_app()
    db = Mock()
    db.ping.return_value = False
    queue = Mock()
    queue.ping.return_value = True

    with TestClient(app) as client:
        app.state.database_runtime = db
        app.state.queue_adapter = queue
        response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["reason"] == "DATABASE_UNAVAILABLE"


def test_root_readiness_sanitizes_exception() -> None:
    app = create_app()
    db = Mock()
    db.ping.side_effect = RuntimeError("postgresql://user:secret@db:5432/app")
    queue = Mock()
    queue.ping.return_value = True

    with TestClient(app) as client:
        app.state.database_runtime = db
        app.state.queue_adapter = queue
        response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["reason"] == "DATABASE_UNAVAILABLE"


def test_health_does_not_update_readiness_metrics() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.get("/readiness")
        before = dict(readiness_dependency_samples())
        response = client.get("/health")
        after = dict(readiness_dependency_samples())

    assert response.status_code == 200
    assert after == before


def test_root_and_system_readiness_share_normalized_contract() -> None:
    app = create_app()
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = True

    with TestClient(app) as client:
        app.state.database_runtime = db
        app.state.queue_adapter = queue
        root_response = client.get("/readiness")
        system_response = client.get("/v1/system/readiness")

    assert root_response.status_code == 200
    assert system_response.status_code == 200
    expected_payload = {
        "status": "ready",
        "dependencies": {
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
        },
        "reason": None,
    }
    assert root_response.json() == expected_payload
    assert system_response.json() == expected_payload

from fastapi.testclient import TestClient
from unittest.mock import Mock

from backend.main import create_app


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
    app.state.database_runtime = db
    app.state.queue_adapter = queue

    with TestClient(app) as client:
        response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["reason"] == "DATABASE_UNAVAILABLE"


def test_root_readiness_sanitizes_exception() -> None:
    app = create_app()
    db = Mock()
    db.ping.side_effect = RuntimeError("postgresql://user:secret@db:5432/app")
    queue = Mock()
    queue.ping.return_value = True
    app.state.database_runtime = db
    app.state.queue_adapter = queue

    with TestClient(app) as client:
        response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["reason"] == "DATABASE_UNAVAILABLE"

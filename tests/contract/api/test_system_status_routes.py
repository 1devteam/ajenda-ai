from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.system import router
from backend.main import create_app


def test_system_status_routes_register() -> None:
    app = FastAPI()
    app.include_router(router)
    routes = {route.path for route in app.routes}
    assert "/system/health" in routes
    assert "/system/readiness" in routes
    assert "/system/status" in routes


def test_system_health_is_liveness_only() -> None:
    app = FastAPI()
    app.state.database_runtime = Mock()
    app.state.queue_adapter = Mock()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    app.state.database_runtime.ping.assert_not_called()
    app.state.queue_adapter.ping.assert_not_called()


def test_system_readiness_sanitizes_dependency_exception() -> None:
    app = FastAPI()
    db = Mock()
    db.ping.side_effect = RuntimeError("postgresql://user:secret@db:5432/app")
    queue = Mock()
    queue.ping.return_value = True
    app.state.database_runtime = db
    app.state.queue_adapter = queue
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/system/readiness")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": {"status": "unavailable"},
            "queue": {"status": "ready"},
        },
        "reason": "DATABASE_UNAVAILABLE",
    }


def test_metrics_exposes_readiness_dependency_status_after_readiness_check() -> None:
    app = create_app()
    db = Mock()
    db.ping.side_effect = RuntimeError("postgresql://user:secret@db:5432/app")
    queue = Mock()
    queue.ping.return_value = True

    with TestClient(app) as client:
        app.state.database_runtime = db
        app.state.queue_adapter = queue
        readiness = client.get("/readiness")
        metrics = client.get("/v1/observability/metrics")

    assert readiness.status_code == 503
    assert metrics.status_code == 200
    assert 'ajenda_readiness_dependency_status{dependency="database"} 0' in metrics.text
    assert 'ajenda_readiness_dependency_status{dependency="queue"} 1' in metrics.text
    assert "postgresql://user:secret@db:5432/app" not in metrics.text

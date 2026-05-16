from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.system import router
from backend.app.dependencies.db import get_database_runtime
from backend.app.dependencies.services import get_queue_adapter


class _FakeDatabaseRuntime:
    def __init__(self, *, ready: bool = True, secret: str = "postgresql://user:pass@db/name") -> None:
        self.ready = ready
        self.secret = secret
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        return self.ready


class _FakeQueue:
    def __init__(self, *, ready: bool = True, fails: bool = False, secret: str = "redis://:pass@redis:6379/0") -> None:
        self.ready = ready
        self.fails = fails
        self.secret = secret
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        if self.fails:
            raise RuntimeError(f"queue unavailable at {self.secret}")
        return self.ready


def _build_app(
    database_runtime: _FakeDatabaseRuntime | None = None,
    queue: _FakeQueue | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    if database_runtime is not None:
        app.dependency_overrides[get_database_runtime] = lambda: database_runtime

    if queue is not None:
        app.dependency_overrides[get_queue_adapter] = lambda: queue

    return app


def test_system_status_routes_register() -> None:
    app = FastAPI()
    app.include_router(router)
    routes = {route.path for route in app.routes}
    assert "/system/health" in routes
    assert "/system/readiness" in routes
    assert "/system/status" in routes


def test_system_health_is_lightweight_and_does_not_call_db_or_queue() -> None:
    database_runtime = _FakeDatabaseRuntime(ready=False)
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/system/health")

    assert response.status_code == 200
    assert response.json() == {"database": "unchecked", "runtime": "ok", "queue": "unchecked"}
    assert database_runtime.pings == 0
    assert queue.pings == 0


def test_system_readiness_includes_database_and_queue_components() -> None:
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue()
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 200
    assert response.json() == {"database": "ready", "queue": "ready", "dependencies": "ready"}
    assert database_runtime.pings == 1
    assert queue.pings == 1


def test_system_readiness_returns_503_for_database_failure_without_leaking_secret() -> None:
    database_runtime = _FakeDatabaseRuntime(ready=False)
    queue = _FakeQueue()
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 503
    assert response.json() == {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}
    assert database_runtime.pings == 1
    assert "postgresql://user:pass" not in response.text


def test_system_readiness_returns_503_for_queue_failure_without_leaking_secret() -> None:
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 503
    assert response.json() == {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"}
    assert database_runtime.pings == 1
    assert "redis://:pass" not in response.text

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.health import router
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


def test_health_route_returns_ok_without_db_or_queue_dependencies() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_route_returns_ready_when_db_and_queue_are_reachable() -> None:
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue()
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert database_runtime.pings == 1
    assert queue.pings == 1


def test_readiness_route_returns_503_when_database_is_unavailable_without_leaking_secret() -> None:
    database_runtime = _FakeDatabaseRuntime(ready=False)
    queue = _FakeQueue()
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable", "queue": "ready"}
    assert database_runtime.pings == 1
    assert "postgresql://user:pass" not in response.text


def test_readiness_route_returns_503_when_queue_is_unavailable_without_leaking_secret() -> None:
    database_runtime = _FakeDatabaseRuntime()
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(database_runtime, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "ready", "queue": "unavailable"}
    assert database_runtime.pings == 1
    assert "redis://:pass" not in response.text

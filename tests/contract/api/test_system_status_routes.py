from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.system import router
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter


class _FakeSession:
    def __init__(self, *, fails: bool = False, secret: str = "postgresql://user:pass@db/name") -> None:
        self.fails = fails
        self.secret = secret
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.fails:
            raise RuntimeError(f"database unavailable at {self.secret}")
        return None


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


def _build_app(session: _FakeSession | None = None, queue: _FakeQueue | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    if session is not None:

        def _override_db():
            yield session

        app.dependency_overrides[get_db_session] = _override_db

    if queue is not None:

        def _override_queue():
            return queue

        app.dependency_overrides[get_queue_adapter] = _override_queue

    return app


def test_system_status_routes_register() -> None:
    app = FastAPI()
    app.include_router(router)
    routes = {route.path for route in app.routes}
    assert "/system/health" in routes
    assert "/system/readiness" in routes
    assert "/system/status" in routes


def test_system_health_is_lightweight_and_does_not_call_db_or_queue() -> None:
    session = _FakeSession(fails=True)
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/system/health")

    assert response.status_code == 200
    assert response.json() == {"database": "unchecked", "runtime": "ok", "queue": "unchecked"}
    assert session.calls == 0
    assert queue.pings == 0


def test_system_readiness_includes_database_and_queue_components() -> None:
    session = _FakeSession()
    queue = _FakeQueue()
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 200
    assert response.json() == {"database": "ready", "queue": "ready", "dependencies": "ready"}


def test_system_readiness_returns_503_for_database_failure_without_leaking_secret() -> None:
    session = _FakeSession(fails=True)
    queue = _FakeQueue()
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 503
    assert response.json() == {"database": "unavailable", "queue": "ready", "dependencies": "not_ready"}
    assert "postgresql://user:pass" not in response.text


def test_system_readiness_returns_503_for_queue_failure_without_leaking_secret() -> None:
    session = _FakeSession()
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/system/readiness")

    assert response.status_code == 503
    assert response.json() == {"database": "ready", "queue": "unavailable", "dependencies": "not_ready"}
    assert "redis://:pass" not in response.text

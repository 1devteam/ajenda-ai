from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.health import router
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


def test_health_route_returns_ok_without_db_or_queue_dependencies() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_route_returns_ready_when_db_and_queue_are_reachable() -> None:
    session = _FakeSession()
    queue = _FakeQueue()
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert session.calls == 1
    assert queue.pings == 1


def test_readiness_route_returns_503_when_database_is_unavailable_without_leaking_secret() -> None:
    session = _FakeSession(fails=True)
    queue = _FakeQueue()
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable", "queue": "ready"}
    assert "postgresql://user:pass" not in response.text


def test_readiness_route_returns_503_when_queue_is_unavailable_without_leaking_secret() -> None:
    session = _FakeSession()
    queue = _FakeQueue(fails=True)
    client = TestClient(_build_app(session, queue), raise_server_exceptions=False)

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "ready", "queue": "unavailable"}
    assert "redis://:pass" not in response.text

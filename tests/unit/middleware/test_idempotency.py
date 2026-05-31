"""Unit tests for IdempotencyMiddleware."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from backend.middleware.idempotency import IdempotencyMiddleware, _store
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter

_call_count = 0


def create_resource(request: Request) -> JSONResponse:
    global _call_count
    _call_count += 1
    return JSONResponse(
        {
            "created": True,
            "call": _call_count,
            "tenant_id": getattr(request.state, "tenant_id", None),
            "principal_id": getattr(getattr(request.state, "principal", None), "subject_id", None),
        },
        status_code=201,
    )


def get_resource(request: Request) -> JSONResponse:
    return JSONResponse({"resource": "data"})


def make_app(
    *,
    tenant_id: str = "tenant-a",
    principal_id: str = "user-a",
    rate_limit_max_requests: int | None = None,
) -> FastAPI:
    app = FastAPI()

    app.post("/resources")(create_resource)
    app.put("/resources")(create_resource)
    app.post("/other-resources")(create_resource)
    app.get("/resources")(get_resource)

    if rate_limit_max_requests is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=RateLimiter(max_requests=rate_limit_max_requests, window_seconds=60),
        )

    app.add_middleware(IdempotencyMiddleware)

    @app.middleware("http")
    async def inject_scope(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = type("Principal", (), {"subject_id": principal_id})()
        return await call_next(request)

    return app


@pytest.fixture(autouse=True)
def reset_state():
    global _call_count
    _call_count = 0
    _store._store.clear()
    yield
    _store._store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(make_app(), raise_server_exceptions=False)


class TestIdempotencyMiddleware:
    def test_first_request_passes_through(self, client: TestClient) -> None:
        key = str(uuid.uuid4())
        response = client.post("/resources", headers={"Idempotency-Key": key})
        assert response.status_code == 201
        assert response.json()["created"] is True
        assert response.headers.get("idempotency-replayed") == "false"

    def test_duplicate_request_is_replayed(self, client: TestClient) -> None:
        key = str(uuid.uuid4())
        first = client.post("/resources", headers={"Idempotency-Key": key})
        second = client.post("/resources", headers={"Idempotency-Key": key})

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["call"] == first.json()["call"]
        assert second.headers.get("idempotency-replayed") == "true"

    def test_duplicate_request_replays_before_rate_limit(self) -> None:
        key = str(uuid.uuid4())
        client = TestClient(make_app(rate_limit_max_requests=1), raise_server_exceptions=False)

        first = client.post("/resources", headers={"Idempotency-Key": key})
        replay = client.post("/resources", headers={"Idempotency-Key": key})
        new_request = client.post("/resources", headers={"Idempotency-Key": str(uuid.uuid4())})

        assert first.status_code == 201
        assert first.headers.get("idempotency-replayed") == "false"
        assert replay.status_code == 201
        assert replay.headers.get("idempotency-replayed") == "true"
        assert replay.json()["call"] == first.json()["call"]
        assert new_request.status_code == 429

    def test_invalid_key_returns_400(self, client: TestClient) -> None:
        response = client.post("/resources", headers={"Idempotency-Key": "not-a-uuid"})
        assert response.status_code == 400
        assert "Idempotency-Key" in response.json()["detail"]

    def test_get_request_passes_through_without_idempotency(self, client: TestClient) -> None:
        response = client.get("/resources")
        assert response.status_code == 200
        assert "idempotency-replayed" not in response.headers

    def test_no_key_passes_through(self, client: TestClient) -> None:
        response = client.post("/resources")
        assert response.status_code == 201
        assert "idempotency-replayed" not in response.headers

    def test_different_keys_are_independent(self, client: TestClient) -> None:
        key1 = str(uuid.uuid4())
        key2 = str(uuid.uuid4())
        r1 = client.post("/resources", headers={"Idempotency-Key": key1})
        r2 = client.post("/resources", headers={"Idempotency-Key": key2})
        assert r1.json()["call"] != r2.json()["call"]

    def test_same_key_is_scoped_by_tenant_and_principal(self) -> None:
        key = str(uuid.uuid4())
        tenant_a = TestClient(make_app(tenant_id="tenant-a", principal_id="user-a"), raise_server_exceptions=False)
        tenant_b = TestClient(make_app(tenant_id="tenant-b", principal_id="user-a"), raise_server_exceptions=False)
        user_b = TestClient(make_app(tenant_id="tenant-a", principal_id="user-b"), raise_server_exceptions=False)

        first = tenant_a.post("/resources", headers={"Idempotency-Key": key})
        second = tenant_b.post("/resources", headers={"Idempotency-Key": key})
        third = user_b.post("/resources", headers={"Idempotency-Key": key})

        assert first.headers.get("idempotency-replayed") == "false"
        assert second.headers.get("idempotency-replayed") == "false"
        assert third.headers.get("idempotency-replayed") == "false"
        assert second.json()["tenant_id"] == "tenant-b"
        assert third.json()["principal_id"] == "user-b"

    def test_same_key_is_scoped_by_path(self, client: TestClient) -> None:
        key = str(uuid.uuid4())
        first = client.post("/resources", headers={"Idempotency-Key": key})
        second = client.post("/other-resources", headers={"Idempotency-Key": key})

        assert first.headers.get("idempotency-replayed") == "false"
        assert second.headers.get("idempotency-replayed") == "false"
        assert first.json()["call"] != second.json()["call"]

    def test_same_key_is_scoped_by_method(self, client: TestClient) -> None:
        key = str(uuid.uuid4())
        first = client.post("/resources", headers={"Idempotency-Key": key})
        second = client.put("/resources", headers={"Idempotency-Key": key})

        assert first.headers.get("idempotency-replayed") == "false"
        assert second.headers.get("idempotency-replayed") == "false"
        assert first.json()["call"] != second.json()["call"]

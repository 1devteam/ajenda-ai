"""Unit tests for IdempotencyMiddleware.

Verifies:
- First request is passed through and stored
- Duplicate request is replayed from store
- Non-UUID keys are rejected with 400
- GET requests pass through without idempotency logic
- Idempotency-Replayed header is set correctly
"""
from __future__ import annotations

import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.middleware.idempotency import IdempotencyMiddleware, _store


_call_count = 0


def create_resource(request: Request) -> JSONResponse:
    global _call_count
    _call_count += 1
    return JSONResponse({"created": True, "call": _call_count}, status_code=201)


def get_resource(request: Request) -> JSONResponse:
    return JSONResponse({"resource": "data"})


def make_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/resources", create_resource, methods=["POST"]),
            Route("/resources", get_resource, methods=["GET"]),
        ]
    )
    app.add_middleware(IdempotencyMiddleware)
    return app


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global call counter and idempotency store between tests."""
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
        # The handler should only have been called once
        assert second.json()["call"] == first.json()["call"]
        assert second.headers.get("idempotency-replayed") == "true"

    def test_invalid_key_returns_400(self, client: TestClient) -> None:
        response = client.post("/resources", headers={"Idempotency-Key": "not-a-uuid"})
        assert response.status_code == 400
        assert "Idempotency-Key" in response.json()["detail"]

    def test_get_request_passes_through_without_idempotency(self, client: TestClient) -> None:
        """GET requests must never be subject to idempotency logic."""
        response = client.get("/resources")
        assert response.status_code == 200
        # No idempotency headers on GET
        assert "idempotency-replayed" not in response.headers

    def test_no_key_passes_through(self, client: TestClient) -> None:
        """Requests without Idempotency-Key are passed through normally."""
        response = client.post("/resources")
        assert response.status_code == 201
        assert "idempotency-replayed" not in response.headers

    def test_different_keys_are_independent(self, client: TestClient) -> None:
        key1 = str(uuid.uuid4())
        key2 = str(uuid.uuid4())
        r1 = client.post("/resources", headers={"Idempotency-Key": key1})
        r2 = client.post("/resources", headers={"Idempotency-Key": key2})
        # Both should hit the handler — different keys, different buckets
        assert r1.json()["call"] != r2.json()["call"]

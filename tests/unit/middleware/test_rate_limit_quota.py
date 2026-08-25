"""Unit tests for API quota enforcement in RateLimitMiddleware."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from backend.middleware.rate_limit import RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter
from backend.services.quota_enforcement import QuotaExceededError

_handler_calls = 0


def test_rate_limit_returns_402_on_quota_exceeded_before_handler(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    global _handler_calls
    _handler_calls = 0

    session = MagicMock()
    database_runtime = MagicMock()
    database_runtime.session_factory.return_value = session
    activate_tenant_session = MagicMock()
    monkeypatch.setattr("backend.middleware.rate_limit.activate_tenant_session", activate_tenant_session)

    quota_svc = MagicMock()
    quota_svc.check_api_call_quota.side_effect = QuotaExceededError(
        field="api_calls_per_month",
        limit=1000,
        current=1000,
        plan="free",
    )

    def _fake_quota_enforcement_service(_session):
        return quota_svc

    monkeypatch.setattr(quota_module, "QuotaEnforcementService", _fake_quota_enforcement_service)

    app = FastAPI()
    tenant_id = str(uuid.uuid4())

    @app.get("/v1/test")
    async def test_route() -> JSONResponse:
        global _handler_calls
        _handler_calls += 1
        return JSONResponse({"ok": True})

    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(max_requests=100, window_seconds=60),
    )
    app.state.database_runtime = database_runtime

    @app.middleware("http")
    async def inject_scope(request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = type("Principal", (), {"subject_id": "user-1"})()
        request.state.tenant = type("Tenant", (), {"plan": "free"})()
        return await call_next(request)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/test")

    assert response.status_code == 402
    body = response.json()
    assert body["detail"]["code"] == "QUOTA_EXCEEDED"
    assert body["detail"]["field"] == "api_calls_per_month"
    assert _handler_calls == 0
    quota_svc.record_api_call.assert_not_called()
    activate_tenant_session.assert_called_once_with(session, tenant_id)
    session.rollback.assert_called_once()


def test_rate_limit_records_api_call_after_successful_handler(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    session = MagicMock()
    database_runtime = MagicMock()
    database_runtime.session_factory.return_value = session
    activate_tenant_session = MagicMock()
    monkeypatch.setattr("backend.middleware.rate_limit.activate_tenant_session", activate_tenant_session)

    quota_svc = MagicMock()

    def _fake_quota_enforcement_service(_session):
        return quota_svc

    monkeypatch.setattr(quota_module, "QuotaEnforcementService", _fake_quota_enforcement_service)

    app = FastAPI()
    tenant_id = str(uuid.uuid4())

    @app.get("/v1/test")
    async def test_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(max_requests=100, window_seconds=60),
    )
    app.state.database_runtime = database_runtime

    @app.middleware("http")
    async def inject_scope(request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = type("Principal", (), {"subject_id": "user-1"})()
        request.state.tenant = type("Tenant", (), {"plan": "free"})()
        return await call_next(request)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/test")

    assert response.status_code == 200
    quota_svc.check_api_call_quota.assert_called_once()
    quota_svc.record_api_call.assert_called_once()
    assert activate_tenant_session.call_args_list == [call(session, tenant_id), call(session, tenant_id)]
    assert session.commit.call_count == 2

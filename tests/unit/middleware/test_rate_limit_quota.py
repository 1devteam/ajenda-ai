"""Unit tests for API quota classification in RateLimitMiddleware."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from backend.auth.principal import MachinePrincipal, PrincipalType, UserPrincipal
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter
from backend.services.quota_enforcement import QuotaExceededError

_handler_calls = 0


def _machine_principal(tenant_id: str) -> MachinePrincipal:
    return MachinePrincipal(
        subject_id="machine:key-1",
        tenant_id=tenant_id,
        principal_type=PrincipalType.MACHINE,
        key_id="key-1",
    )


def _user_principal(tenant_id: str) -> UserPrincipal:
    return UserPrincipal(
        subject_id="user:member-1",
        tenant_id=tenant_id,
        principal_type=PrincipalType.USER,
        email="user@example.com",
    )


def _build_app(*, tenant_id: str, principal: object, status_code: int = 200) -> tuple[FastAPI, TestClient, MagicMock]:
    app = FastAPI()
    database_runtime = MagicMock()
    database_runtime.session_factory.return_value = MagicMock()
    app.state.database_runtime = database_runtime

    @app.get("/v1/test")
    async def test_route() -> JSONResponse:
        global _handler_calls
        _handler_calls += 1
        return JSONResponse({"ok": status_code < 400}, status_code=status_code)

    @app.get("/v1/onboarding/promote-bootstrap-key")
    async def onboarding_route() -> JSONResponse:
        global _handler_calls
        _handler_calls += 1
        return JSONResponse({"ok": True})

    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(max_requests=100, window_seconds=60),
    )

    @app.middleware("http")
    async def inject_scope(request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = principal
        request.state.tenant = type("Tenant", (), {"plan": "free"})()
        return await call_next(request)

    return app, TestClient(app, raise_server_exceptions=False), database_runtime


def test_api_key_request_returns_402_on_quota_exceeded_before_handler(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    global _handler_calls
    _handler_calls = 0
    tenant_id = str(uuid.uuid4())
    principal = _machine_principal(tenant_id)
    app, client, database_runtime = _build_app(tenant_id=tenant_id, principal=principal)
    session = database_runtime.session_factory.return_value

    activate_tenant_session = MagicMock()
    monkeypatch.setattr("backend.middleware.rate_limit.activate_tenant_session", activate_tenant_session)

    quota_svc = MagicMock()
    quota_svc.check_api_call_quota.side_effect = QuotaExceededError(
        field="api_calls_per_month",
        limit=1000,
        current=1000,
        plan="free",
    )
    monkeypatch.setattr(quota_module, "QuotaEnforcementService", lambda _session: quota_svc)

    response = client.get("/v1/test")

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"
    assert _handler_calls == 0
    quota_svc.record_api_call.assert_not_called()
    activate_tenant_session.assert_called_once_with(session, tenant_id)
    session.rollback.assert_called_once()


def test_api_key_request_records_one_call_after_success(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    global _handler_calls
    _handler_calls = 0
    tenant_id = str(uuid.uuid4())
    principal = _machine_principal(tenant_id)
    app, client, database_runtime = _build_app(tenant_id=tenant_id, principal=principal)
    session = database_runtime.session_factory.return_value

    activate_tenant_session = MagicMock()
    monkeypatch.setattr("backend.middleware.rate_limit.activate_tenant_session", activate_tenant_session)
    quota_svc = MagicMock()
    monkeypatch.setattr(quota_module, "QuotaEnforcementService", lambda _session: quota_svc)

    response = client.get("/v1/test")

    assert response.status_code == 200
    assert _handler_calls == 1
    quota_svc.check_api_call_quota.assert_called_once()
    quota_svc.record_api_call.assert_called_once()
    assert activate_tenant_session.call_args_list == [call(session, tenant_id), call(session, tenant_id)]
    assert session.commit.call_count == 2


def test_oidc_user_request_does_not_check_or_record_api_call_quota(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    global _handler_calls
    _handler_calls = 0
    tenant_id = str(uuid.uuid4())
    principal = _user_principal(tenant_id)
    _, client, _ = _build_app(tenant_id=tenant_id, principal=principal)

    quota_svc = MagicMock()
    quota_svc.check_api_call_quota.side_effect = QuotaExceededError(
        field="api_calls_per_month",
        limit=1000,
        current=1000,
        plan="free",
    )
    monkeypatch.setattr(quota_module, "QuotaEnforcementService", lambda _session: quota_svc)

    response = client.get("/v1/test")

    assert response.status_code == 200
    assert _handler_calls == 1
    quota_svc.check_api_call_quota.assert_not_called()
    quota_svc.record_api_call.assert_not_called()


def test_failed_api_key_request_is_admitted_but_not_recorded(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    tenant_id = str(uuid.uuid4())
    principal = _machine_principal(tenant_id)
    _, client, _ = _build_app(tenant_id=tenant_id, principal=principal, status_code=422)

    quota_svc = MagicMock()
    monkeypatch.setattr(quota_module, "QuotaEnforcementService", lambda _session: quota_svc)

    response = client.get("/v1/test")

    assert response.status_code == 422
    quota_svc.check_api_call_quota.assert_called_once()
    quota_svc.record_api_call.assert_not_called()


def test_onboarding_machine_request_is_control_plane_and_not_billable(monkeypatch) -> None:
    from backend.services import quota_enforcement as quota_module

    tenant_id = str(uuid.uuid4())
    principal = _machine_principal(tenant_id)
    _, client, _ = _build_app(tenant_id=tenant_id, principal=principal)

    quota_svc = MagicMock()
    monkeypatch.setattr(quota_module, "QuotaEnforcementService", lambda _session: quota_svc)

    response = client.get("/v1/onboarding/promote-bootstrap-key")

    assert response.status_code == 200
    quota_svc.check_api_call_quota.assert_not_called()
    quota_svc.record_api_call.assert_not_called()

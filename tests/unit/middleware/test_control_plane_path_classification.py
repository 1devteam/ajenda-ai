from __future__ import annotations

import asyncio
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.public_paths import is_public_path, is_tenant_exempt_path


def _request(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace()),
    }
    request = Request(scope)
    request.state.tenant_id = None
    request.state.principal = None
    return request


async def _call_next(request: Request) -> Response:
    return JSONResponse({"ok": True})


def test_admin_is_tenant_exempt_but_authentication_required() -> None:
    path = "/v1/admin/tenants"
    assert is_tenant_exempt_path(path) is True
    assert is_public_path(path) is False

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    response = asyncio.run(middleware.dispatch(_request(path), _call_next))

    assert response.status_code == 401


def test_global_recovery_is_tenant_exempt_but_authentication_required() -> None:
    path = "/v1/operations/recovery"
    assert is_tenant_exempt_path(path) is True
    assert is_public_path(path) is False

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    response = asyncio.run(middleware.dispatch(_request(path), _call_next))

    assert response.status_code == 401


def test_health_remains_authentication_public() -> None:
    assert is_public_path("/health") is True
    assert is_tenant_exempt_path("/health") is True

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.auth.jwt_validator import JwtValidationError
from backend.middleware.auth_context import AuthContextMiddleware


def _request(
    path: str = "/runtime/private",
    headers: dict[str, str] | None = None,
    *,
    tenant_id: str | None = None,
    app_state: object | None = None,
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "app": SimpleNamespace(state=app_state or SimpleNamespace()),
    }
    request = Request(scope)
    request.state.tenant_id = tenant_id
    request.state.principal = None
    return request


async def _call_next(request: Request) -> Response:
    return JSONResponse(
        {
            "ok": True,
            "principal": getattr(request.state, "principal", None) is not None,
            "tenant_id": getattr(request.state, "tenant_id", None),
        }
    )


class _FakeSessionScope:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeDatabaseRuntime:
    def __init__(self, session: object) -> None:
        self._session = session

    def session_scope(self) -> _FakeSessionScope:
        return _FakeSessionScope(self._session)


class _Principal:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id


def test_private_path_without_auth_returns_401() -> None:
    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request()

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 401
    assert b"missing authentication credentials" in response.body


def test_public_path_bypasses_auth() -> None:
    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(path="/health")

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200


def test_api_key_missing_tenant_returns_400() -> None:
    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(headers={"X-Api-Key": "kid.secret"})

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 400
    assert b"X-Tenant-Id header required" in response.body


def test_malformed_api_key_returns_401() -> None:
    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Api-Key": "malformed"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(object())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 401
    assert b"malformed api key" in response.body


def test_invalid_api_key_returns_401(monkeypatch) -> None:
    class _FakeApiKeyService:
        def __init__(self, session: object) -> None:
            self.session = session

        def authenticate_machine(self, tenant_id: str, key_id: str, plaintext: str):
            return None

    monkeypatch.setattr("backend.middleware.auth_context.ApiKeyService", _FakeApiKeyService)

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Api-Key": "kid.secret"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(object())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 401
    assert b"invalid or revoked api key" in response.body


def test_valid_api_key_sets_principal(monkeypatch) -> None:
    class _FakeApiKeyService:
        def __init__(self, session: object) -> None:
            self.session = session

        def authenticate_machine(self, tenant_id: str, key_id: str, plaintext: str):
            return _Principal("tenant-a")

    monkeypatch.setattr("backend.middleware.auth_context.ApiKeyService", _FakeApiKeyService)

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Api-Key": "kid.secret"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(object())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200
    assert request.state.principal is not None


def test_cross_tenant_api_key_returns_403(monkeypatch) -> None:
    class _FakeApiKeyService:
        def __init__(self, session: object) -> None:
            self.session = session

        def authenticate_machine(self, tenant_id: str, key_id: str, plaintext: str):
            return _Principal("tenant-b")

    monkeypatch.setattr("backend.middleware.auth_context.ApiKeyService", _FakeApiKeyService)

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Api-Key": "kid.secret"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(object())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 403


def test_invalid_bearer_returns_401(monkeypatch) -> None:
    class _FakeOidcAuthenticator:
        def __init__(self, **kwargs) -> None:
            pass

        def validate_bearer_token(self, token: str):
            raise JwtValidationError("bad token")

    monkeypatch.setattr("backend.middleware.auth_context.OidcAuthenticator", _FakeOidcAuthenticator)

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"Authorization": "Bearer bad-token"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(
            settings=SimpleNamespace(
                oidc_jwks_uri="https://example.test/jwks",
                oidc_issuer="https://example.test/issuer",
                oidc_audience="ajenda-api",
            )
        ),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 401
    assert b"invalid bearer token" in response.body


def test_valid_bearer_sets_principal(monkeypatch) -> None:
    class _FakeOidcAuthenticator:
        def __init__(self, **kwargs) -> None:
            pass

        def validate_bearer_token(self, token: str):
            return SimpleNamespace(principal=_Principal("tenant-a"))

    monkeypatch.setattr("backend.middleware.auth_context.OidcAuthenticator", _FakeOidcAuthenticator)

    middleware = AuthContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"Authorization": "Bearer good-token"},
        tenant_id="tenant-a",
        app_state=SimpleNamespace(
            settings=SimpleNamespace(
                oidc_jwks_uri="https://example.test/jwks",
                oidc_issuer="https://example.test/issuer",
                oidc_audience="ajenda-api",
            )
        ),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200
    assert request.state.principal is not None

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.middleware.tenant_context import TenantContextMiddleware


def _request(
    path: str = "/runtime/private",
    headers: dict[str, str] | None = None,
    *,
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
    request.state.tenant_id = None
    request.state.tenant = None
    return request


async def _call_next(request: Request) -> Response:
    return JSONResponse(
        {
            "ok": True,
            "tenant_id": getattr(request.state, "tenant_id", None),
            "has_tenant": getattr(request.state, "tenant", None) is not None,
        }
    )


class _Tenant:
    def __init__(self, tenant_id: uuid.UUID, *, deleted: bool = False, suspended: bool = False) -> None:
        self.id = tenant_id
        self._deleted = deleted
        self._suspended = suspended

    def is_deleted(self) -> bool:
        return self._deleted

    def is_suspended(self) -> bool:
        return self._suspended


class _FakeSession:
    def close(self) -> None:
        return None


class _FakeDatabaseRuntime:
    def __init__(self, session: object) -> None:
        self._session = session

    def session_factory(self) -> object:
        return self._session


def test_public_path_bypasses_tenant_enforcement() -> None:
    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(path="/health")

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200
    assert request.state.tenant_id is None
    assert request.state.tenant is None


def test_missing_tenant_header_returns_400() -> None:
    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request()

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 400
    assert b"MISSING_TENANT_ID" in response.body


def test_invalid_tenant_header_returns_400() -> None:
    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(headers={"X-Tenant-Id": "not-a-uuid"})

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 400
    assert b"INVALID_TENANT_ID_FORMAT" in response.body


def test_no_database_runtime_still_sets_tenant_id() -> None:
    tenant_id = str(uuid.uuid4())
    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(headers={"X-Tenant-Id": tenant_id})

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200
    assert request.state.tenant_id == tenant_id
    assert request.state.tenant is None


def test_missing_tenant_in_database_returns_404(monkeypatch) -> None:
    tenant_id = uuid.uuid4()

    class _FakeTenantRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, tenant_uuid: uuid.UUID):
            return None

    monkeypatch.setattr("backend.repositories.tenant_repository.TenantRepository", _FakeTenantRepository)

    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Tenant-Id": str(tenant_id)},
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(_FakeSession())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 404
    assert b"TENANT_NOT_FOUND" in response.body


def test_deleted_tenant_returns_403(monkeypatch) -> None:
    tenant_id = uuid.uuid4()

    class _FakeTenantRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, tenant_uuid: uuid.UUID):
            return _Tenant(tenant_uuid, deleted=True)

    monkeypatch.setattr("backend.repositories.tenant_repository.TenantRepository", _FakeTenantRepository)

    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Tenant-Id": str(tenant_id)},
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(_FakeSession())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 403
    assert b"TENANT_DELETED" in response.body


def test_suspended_tenant_returns_403(monkeypatch) -> None:
    tenant_id = uuid.uuid4()

    class _FakeTenantRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, tenant_uuid: uuid.UUID):
            return _Tenant(tenant_uuid, suspended=True)

    monkeypatch.setattr("backend.repositories.tenant_repository.TenantRepository", _FakeTenantRepository)

    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Tenant-Id": str(tenant_id)},
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(_FakeSession())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 403
    assert b"TENANT_SUSPENDED" in response.body


def test_database_error_returns_503() -> None:
    class _BrokenDatabaseRuntime:
        def session_factory(self):
            raise RuntimeError("db unavailable")

    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Tenant-Id": str(uuid.uuid4())},
        app_state=SimpleNamespace(database_runtime=_BrokenDatabaseRuntime()),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 503
    assert b"DB_UNAVAILABLE" in response.body


def test_valid_tenant_sets_request_state(monkeypatch) -> None:
    tenant_id = uuid.uuid4()

    class _FakeTenantRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, tenant_uuid: uuid.UUID):
            return _Tenant(tenant_uuid)

    monkeypatch.setattr("backend.repositories.tenant_repository.TenantRepository", _FakeTenantRepository)

    middleware = TenantContextMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        headers={"X-Tenant-Id": str(tenant_id)},
        app_state=SimpleNamespace(database_runtime=_FakeDatabaseRuntime(_FakeSession())),
    )

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 200
    assert request.state.tenant_id == str(tenant_id)
    assert request.state.tenant is not None

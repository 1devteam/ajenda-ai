"""Negative cross-tenant isolation tests for all tenant-facing routes.

These tests verify the mandatory tenant isolation policy defined in:
  docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md

Every tenant-facing route must:
  1. Reject requests with no X-Tenant-Id header (400)
  2. Reject requests where the bearer token's tenant_id differs from X-Tenant-Id (403)
  3. Reject requests with no auth credentials (401)
  4. Source tenant_id from request.state (middleware-validated) not raw header

Middleware registration order mirrors production (innermost → outermost):
  RequestContext → Auth → Tenant
Execution order (Starlette reversal):
  Tenant → Auth → RequestContext → route

Tenant MUST execute before Auth so that:
  - X-Tenant-Id is validated before any auth processing
  - Cross-tenant rejections happen at the tenant boundary, not the auth boundary
"""

from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import api_keys as api_keys_module
from backend.api.routes import branch as branch_module
from backend.api.routes import mission as mission_module
from backend.api.routes import operations as operations_module
from backend.api.routes import system as system_module
from backend.api.routes import task as task_module
from backend.api.routes import webhooks as webhooks_module
from backend.api.routes import workforce as workforce_module
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())


def _token(tenant_id: str, roles: list[str] | None = None) -> str:
    """Build a minimal fake JWT whose middle segment encodes the payload."""
    payload = {"sub": "user-1", "tenant_id": tenant_id, "roles": roles or ["tenant_admin"]}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"x.{encoded}.y"


def _build_app(*routers) -> FastAPI:
    """Build a minimal FastAPI app with the production middleware stack.

    Registration order (innermost → outermost, Starlette reverses at runtime):
      RequestContext → Auth → Tenant

    Execution order (outermost → innermost):
      Tenant → Auth → RequestContext → route

    app.state.settings is set to a minimal mock so AuthContextMiddleware
    can access it for Bearer token processing without a real OIDC stack.
    The OidcAuthenticator will fail validation (expected) and return 401.
    """
    app = FastAPI()

    # Set minimal app.state so AuthContextMiddleware doesn't crash on settings access
    settings_mock = MagicMock()
    settings_mock.oidc_jwks_uri = "https://example.com/.well-known/jwks.json"
    settings_mock.oidc_issuer = "https://example.com"
    settings_mock.oidc_audience = "ajenda-api"
    app.state.settings = settings_mock

    # Innermost: request context
    app.add_middleware(RequestContextMiddleware)
    # Auth: registered before Tenant so Tenant executes first at runtime
    app.add_middleware(AuthContextMiddleware)
    # Outermost: Tenant context — executes first, validates X-Tenant-Id
    app.add_middleware(TenantContextMiddleware)

    for router in routers:
        app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Shared negative-case matrix
#
# Each entry: (route_label, method, path, json_body, valid_tenant)
# Tests are parameterised across all routes for DRY coverage.
# ---------------------------------------------------------------------------

ROUTE_CASES = [
    ("api_keys:create", "POST", "/api-keys", {"scopes": []}, TENANT_A),
    ("api_keys:revoke", "POST", "/api-keys/some-key-id/revoke", None, TENANT_A),
    ("mission:queue", "POST", f"/missions/{uuid.uuid4()}/queue", None, TENANT_A),
    ("task:queue", "POST", f"/tasks/{uuid.uuid4()}/queue", None, TENANT_A),
    (
        "workforce:provision",
        "POST",
        "/workforces/provision",
        {
            "mission_id": str(uuid.uuid4()),
            "fleet_name": "fleet-1",
            "agents": [{"display_name": "Agent", "role_name": "executor"}],
        },
        TENANT_A,
    ),
    (
        "branch:create",
        "POST",
        "/branches",
        {
            "mission_id": str(uuid.uuid4()),
            "reason": "test",
        },
        TENANT_A,
    ),
    ("operations:dead_letter", "GET", "/operations/dead-letter", None, TENANT_A),
    ("operations:retry", "POST", f"/operations/dead-letter/{uuid.uuid4()}/retry", None, TENANT_A),
    ("system:status", "GET", "/system/status", None, TENANT_A),
    (
        "webhooks:register",
        "POST",
        "/webhooks/",
        {
            "url": "https://example.com/hook",
            "event_types": ["task.completed"],
        },
        TENANT_A,
    ),
    ("webhooks:list", "GET", "/webhooks/", None, TENANT_A),
    ("webhooks:get", "GET", f"/webhooks/{uuid.uuid4()}", None, TENANT_A),
    ("webhooks:delete", "DELETE", f"/webhooks/{uuid.uuid4()}", None, TENANT_A),
    ("webhooks:deliveries", "GET", f"/webhooks/{uuid.uuid4()}/deliveries", None, TENANT_A),
]


def _all_routers():
    return [
        api_keys_module.router,
        mission_module.router,
        task_module.router,
        workforce_module.router,
        branch_module.router,
        operations_module.router,
        system_module.router,
        webhooks_module.router,
    ]


# ---------------------------------------------------------------------------
# Test: missing X-Tenant-Id → 400
#
# Tenant middleware runs first. No X-Tenant-Id → 400 before Auth processes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,method,path,body,tenant", ROUTE_CASES)
def test_missing_tenant_header_returns_400(
    label: str,
    method: str,
    path: str,
    body: dict | None,
    tenant: str,
) -> None:
    """All tenant-facing routes must return 400 when X-Tenant-Id is absent.

    Tenant middleware is outermost and rejects before Auth processes.
    """
    app = _build_app(*_all_routers())
    client = TestClient(app, raise_server_exceptions=False)
    # No X-Tenant-Id header — Tenant middleware must reject with 400
    kwargs: dict = {}
    if body is not None:
        kwargs["json"] = body

    resp = getattr(client, method.lower())(path, **kwargs)
    assert resp.status_code == 400, (
        f"[{label}] Expected 400 for missing tenant header, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()
    assert "MISSING_TENANT_ID" in str(detail) or "X-Tenant-Id" in str(detail), (
        f"[{label}] Expected MISSING_TENANT_ID in response, got: {detail}"
    )


# ---------------------------------------------------------------------------
# Test: cross-tenant bearer token → 403
#
# Tenant middleware validates UUID format and sets request.state.tenant_id.
# Auth middleware then sets request.state.principal from the Bearer token.
# Tenant middleware's cross-tenant check runs after Auth sets principal.
#
# Since TenantContextMiddleware checks principal AFTER setting tenant_id,
# and the cross-tenant check uses getattr(request.state, 'principal', None),
# we need Auth to successfully set principal. We use an API key format
# (not Bearer) to avoid OIDC validation — but API keys need a DB.
#
# Instead, we inject a principal directly via a test middleware that runs
# between Tenant and Auth, simulating a successfully authenticated principal
# from a different tenant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,method,path,body,tenant", ROUTE_CASES)
def test_cross_tenant_bearer_returns_403(
    label: str,
    method: str,
    path: str,
    body: dict | None,
    tenant: str,
) -> None:
    """All tenant-facing routes must return 403 when the authenticated principal
    belongs to a different tenant than the X-Tenant-Id header claims.

    Mocks OidcAuthenticator.validate_bearer_token to return a TENANT_B principal
    so that AuthContextMiddleware's cross-tenant check fires against the
    TENANT_A value set by TenantContextMiddleware.
    """
    from unittest.mock import patch

    from backend.auth.oidc import OidcValidationResult
    from backend.auth.principal import PrincipalType, UserPrincipal

    # Build a real UserPrincipal for TENANT_B
    tenant_b_principal = UserPrincipal(
        subject_id="user-b",
        tenant_id=TENANT_B,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )
    tenant_b_result = OidcValidationResult(
        claims={"sub": "user-b", "tenant_id": TENANT_B},
        principal=tenant_b_principal,
        provider="oidc",
    )

    app = _build_app(*_all_routers())
    client = TestClient(app, raise_server_exceptions=False)

    # Header claims TENANT_A but OIDC token is for TENANT_B → cross-tenant rejection
    kwargs: dict = {
        "headers": {
            "X-Tenant-Id": TENANT_A,
            "Authorization": f"Bearer {_token(TENANT_B)}",
        }
    }
    if body is not None:
        kwargs["json"] = body

    with patch(
        "backend.middleware.auth_context.OidcAuthenticator.validate_bearer_token",
        return_value=tenant_b_result,
    ):
        resp = getattr(client, method.lower())(path, **kwargs)

    assert resp.status_code == 403, (
        f"[{label}] Expected 403 for cross-tenant access, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()
    assert "CROSS_TENANT_REJECTED" in str(detail) or "Cross-tenant" in str(detail), (
        f"[{label}] Expected CROSS_TENANT_REJECTED in response, got: {detail}"
    )


# ---------------------------------------------------------------------------
# Test: no auth credentials → 401
#
# Tenant runs first (validates header), then Auth runs and finds no credentials.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,method,path,body,tenant", ROUTE_CASES)
def test_no_auth_credentials_returns_401(
    label: str,
    method: str,
    path: str,
    body: dict | None,
    tenant: str,
) -> None:
    """All tenant-facing routes must return 401 when no auth credentials are provided."""
    app = _build_app(*_all_routers())
    client = TestClient(app, raise_server_exceptions=False)
    kwargs: dict = {"headers": {"X-Tenant-Id": tenant}}
    if body is not None:
        kwargs["json"] = body

    resp = getattr(client, method.lower())(path, **kwargs)
    assert resp.status_code == 401, f"[{label}] Expected 401 for missing auth, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Test: invalid UUID in X-Tenant-Id → 400
#
# Tenant middleware validates UUID format before Auth processes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,method,path,body,tenant", ROUTE_CASES)
def test_invalid_tenant_uuid_returns_400(
    label: str,
    method: str,
    path: str,
    body: dict | None,
    tenant: str,
) -> None:
    """All tenant-facing routes must return 400 when X-Tenant-Id is not a valid UUID."""
    app = _build_app(*_all_routers())
    client = TestClient(app, raise_server_exceptions=False)
    # No auth needed — Tenant middleware rejects before Auth processes
    kwargs: dict = {"headers": {"X-Tenant-Id": "not-a-uuid"}}
    if body is not None:
        kwargs["json"] = body

    resp = getattr(client, method.lower())(path, **kwargs)
    assert resp.status_code == 400, (
        f"[{label}] Expected 400 for invalid UUID in tenant header, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()
    assert "INVALID_TENANT_ID_FORMAT" in str(detail) or "not a valid UUID" in str(detail), (
        f"[{label}] Expected INVALID_TENANT_ID_FORMAT in response, got: {detail}"
    )


# ---------------------------------------------------------------------------
# Test: public routes are unaffected by tenant isolation
# ---------------------------------------------------------------------------


def test_system_health_requires_no_tenant_header() -> None:
    """GET /system/health must succeed without X-Tenant-Id (public route)."""
    app = _build_app(system_module.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/system/health")
    # 200 or 500 (no DB in test) — but NOT 400 (tenant required) or 401 (auth required)
    assert resp.status_code not in (400, 401, 403), (
        f"Public health route should not require tenant/auth, got {resp.status_code}: {resp.text}"
    )


def test_system_readiness_requires_no_tenant_header() -> None:
    """GET /system/readiness must succeed without X-Tenant-Id (public route)."""
    app = _build_app(system_module.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/system/readiness")
    assert resp.status_code not in (400, 401, 403), (
        f"Public readiness route should not require tenant/auth, got {resp.status_code}: {resp.text}"
    )


def test_operations_recovery_requires_no_tenant_header() -> None:
    """POST /operations/recovery must succeed without X-Tenant-Id (cross-tenant admin op)."""
    app = _build_app(operations_module.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/operations/recovery")
    # 200 or 500 (no DB in test) — but NOT 400 (tenant required) or 401 (auth required)
    assert resp.status_code not in (400, 401, 403), (
        f"Cross-tenant recovery route should not require tenant/auth, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Test: get_request_tenant_id dependency is used (not raw Header)
#
# Override the dependency to prove the route uses the DI path, not Header().
# ---------------------------------------------------------------------------


def test_api_keys_uses_get_request_tenant_id_dependency() -> None:
    """Verify api_keys route uses get_request_tenant_id dependency, not raw Header.

    Mocks OIDC validation so Auth passes and the handler actually runs,
    proving get_request_tenant_id is called via the dependency injection path.
    """
    from unittest.mock import patch

    from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
    from backend.auth.oidc import OidcValidationResult
    from backend.auth.principal import PrincipalType, UserPrincipal

    tenant_a_principal = UserPrincipal(
        subject_id="user-a",
        tenant_id=TENANT_A,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )
    tenant_a_result = OidcValidationResult(
        claims={"sub": "user-a", "tenant_id": TENANT_A},
        principal=tenant_a_principal,
        provider="oidc",
    )

    app = _build_app(api_keys_module.router)
    captured_tenant_ids: list[uuid.UUID] = []

    def override_get_request_tenant_id() -> uuid.UUID:
        tid = uuid.UUID(TENANT_A)
        captured_tenant_ids.append(tid)
        return tid

    def override_get_tenant_db_session():
        yield MagicMock()

    app.dependency_overrides[get_request_tenant_id] = override_get_request_tenant_id
    app.dependency_overrides[get_tenant_db_session] = override_get_tenant_db_session

    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "backend.middleware.auth_context.OidcAuthenticator.validate_bearer_token",
        return_value=tenant_a_result,
    ):
        client.post(
            "/api-keys",
            headers={
                "X-Tenant-Id": TENANT_A,
                "Authorization": f"Bearer {_token(TENANT_A)}",
            },
            json={"scopes": []},
        )

    # The override was called — proving the route uses the dependency, not Header()
    assert len(captured_tenant_ids) >= 1, (
        "get_request_tenant_id dependency was not called — route may still be using raw Header()"
    )
    assert captured_tenant_ids[0] == uuid.UUID(TENANT_A)


def test_webhooks_uses_get_request_tenant_id_dependency() -> None:
    """Verify webhooks route uses get_request_tenant_id dependency, not raw Header.

    Mocks OIDC validation so Auth passes and the handler actually runs,
    proving get_request_tenant_id is called via the dependency injection path.
    """
    from unittest.mock import patch

    from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
    from backend.auth.oidc import OidcValidationResult
    from backend.auth.principal import PrincipalType, UserPrincipal

    tenant_a_principal = UserPrincipal(
        subject_id="user-a",
        tenant_id=TENANT_A,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )
    tenant_a_result = OidcValidationResult(
        claims={"sub": "user-a", "tenant_id": TENANT_A},
        principal=tenant_a_principal,
        provider="oidc",
    )

    app = _build_app(webhooks_module.router)
    captured_tenant_ids: list[uuid.UUID] = []

    def override_get_request_tenant_id() -> uuid.UUID:
        tid = uuid.UUID(TENANT_A)
        captured_tenant_ids.append(tid)
        return tid

    def override_get_tenant_db_session():
        yield MagicMock()

    app.dependency_overrides[get_request_tenant_id] = override_get_request_tenant_id
    app.dependency_overrides[get_tenant_db_session] = override_get_tenant_db_session

    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "backend.middleware.auth_context.OidcAuthenticator.validate_bearer_token",
        return_value=tenant_a_result,
    ):
        client.get(
            "/webhooks/",
            headers={
                "X-Tenant-Id": TENANT_A,
                "Authorization": f"Bearer {_token(TENANT_A)}",
            },
        )

    assert len(captured_tenant_ids) >= 1, (
        "get_request_tenant_id dependency was not called — webhooks route may still be using raw Header()"
    )

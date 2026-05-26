from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import observability as observability_module
from backend.app.dependencies.db import get_tenant_db_session
from backend.auth.oidc import OidcValidationResult
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def _token(tenant_id: str, roles: list[str] | None = None) -> str:
    payload = {"sub": "user-1", "tenant_id": tenant_id, "roles": roles or ["tenant_admin"]}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"x.{encoded}.y"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks", oidc_issuer="https://example", oidc_audience="ajenda"
    )
    app.state.database_runtime = None

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(observability_module.router, prefix="/v1")

    def _override_tenant_db_session():
        yield MagicMock()

    app.dependency_overrides[get_tenant_db_session] = _override_tenant_db_session
    return app


def test_reliability_summary_requires_tenant_and_auth() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    missing_tenant = client.get("/v1/observability/reliability/summary")
    missing_auth = client.get(
        "/v1/observability/reliability/summary",
        headers={"X-Tenant-Id": str(uuid.uuid4())},
    )

    assert missing_tenant.status_code == 400
    assert missing_auth.status_code == 401


def test_reliability_summary_cross_tenant_rejected() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    header_tenant = str(uuid.uuid4())
    token_tenant = str(uuid.uuid4())
    principal = UserPrincipal(
        subject_id="user-1",
        tenant_id=token_tenant,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )
    oidc_result = OidcValidationResult(
        claims={"sub": "user-1", "tenant_id": token_tenant},
        principal=principal,
        provider="oidc",
    )

    with patch(
        "backend.middleware.auth_context.OidcAuthenticator.validate_bearer_token",
        return_value=oidc_result,
    ):
        response = client.get(
            "/v1/observability/reliability/summary",
            headers={"X-Tenant-Id": header_tenant, "Authorization": f"Bearer {_token(token_tenant)}"},
        )

    assert response.status_code == 403


def test_reliability_summary_response_schema_contract() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    tenant_id = str(uuid.uuid4())
    principal = UserPrincipal(
        subject_id="user-1",
        tenant_id=tenant_id,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )
    oidc_result = OidcValidationResult(
        claims={"sub": "user-1", "tenant_id": tenant_id},
        principal=principal,
        provider="oidc",
    )

    with (
        patch("backend.middleware.auth_context.OidcAuthenticator.validate_bearer_token", return_value=oidc_result),
        patch("backend.api.routes.observability.require_route_permission", return_value=None),
        patch("backend.api.routes.observability.ObservabilityService") as mock_service,
    ):
        mock_service.return_value.metrics_snapshot.return_value = MagicMock(
            tasks_queued=10,
            tasks_completed=7,
            tasks_failed=2,
            dead_letter_count=1,
            lease_expirations=1,
            active_leases=3,
            released_leases=2,
        )

        response = client.get(
            "/v1/observability/reliability/summary",
            headers={"X-Tenant-Id": tenant_id, "Authorization": f"Bearer {_token(tenant_id)}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authority_class"] == "read_model"
    assert body["side_effect_class"] == "none"
    assert body["does_not_execute_runtime_work"] is True
    assert set(body["lease_health"].keys()) == {
        "active_leases",
        "expired_leases",
        "released_leases",
        "lease_expiration_rate",
    }
    assert set(body["recovery"].keys()) == {
        "recovered_tasks",
        "dead_lettered_tasks",
        "recovery_success_ratio",
    }

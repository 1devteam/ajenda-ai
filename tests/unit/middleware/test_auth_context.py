"""Unit tests for AuthContextMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.auth.jwt_validator import JwtValidationError
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def _make_principal(
    subject_id: str = "user-1",
    tenant_id: str = "tenant-a",
) -> UserPrincipal:
    return UserPrincipal(
        subject_id=subject_id,
        tenant_id=tenant_id,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
        email="a@example.com",
    )


def _app_with_mocked_state() -> FastAPI:
    app = FastAPI()

    settings = MagicMock()
    settings.oidc_jwks_uri = "https://example.com/.well-known/jwks.json"
    settings.oidc_issuer = "https://example.com"
    settings.oidc_audience = "ajenda-api"
    app.state.settings = settings
    app.state.database_runtime = MagicMock()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(AuthContextMiddleware)

    @app.get("/protected")
    def protected(request: Request) -> dict[str, str]:
        principal = request.state.principal
        return {"subject_id": principal.subject_id}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_auth_context_injects_principal_on_valid_bearer() -> None:
    app = _app_with_mocked_state()
    principal = _make_principal()

    with patch("backend.middleware.auth_context.OidcAuthenticator") as oidc_cls:
        oidc = MagicMock()
        result = MagicMock()
        result.principal = principal
        oidc.validate_bearer_token.return_value = result
        oidc_cls.return_value = oidc

        client = TestClient(app)
        response = client.get(
            "/protected",
            headers={
                "Authorization": "Bearer valid.token.here",
                "X-Tenant-Id": "tenant-a",
            },
        )

    assert response.status_code == 200
    assert response.json()["subject_id"] == "user-1"


def test_auth_context_denies_missing_auth_by_default() -> None:
    client = TestClient(_app_with_mocked_state())

    response = client.get("/protected", headers={"X-Tenant-Id": "tenant-a"})

    assert response.status_code == 401
    assert response.json()["detail"] == "missing authentication credentials"


def test_auth_context_allows_public_health_without_auth() -> None:
    client = TestClient(_app_with_mocked_state())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_context_rejects_invalid_bearer_token() -> None:
    app = _app_with_mocked_state()

    with patch("backend.middleware.auth_context.OidcAuthenticator") as oidc_cls:
        oidc = MagicMock()
        oidc.validate_bearer_token.side_effect = JwtValidationError("token expired")
        oidc_cls.return_value = oidc

        client = TestClient(app)
        response = client.get(
            "/protected",
            headers={
                "Authorization": "Bearer expired.token.here",
                "X-Tenant-Id": "tenant-a",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid bearer token"

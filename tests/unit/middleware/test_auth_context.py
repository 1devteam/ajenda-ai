"""Unit tests for AuthContextMiddleware.

These tests mock app.state.settings and app.state.database_runtime since
the middleware requires them to be present. The contract being tested is
that the middleware correctly injects a principal on valid auth and rejects
missing or invalid credentials.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware
from backend.auth.principal import PrincipalType, UserPrincipal


def _make_principal(subject_id: str = "user-1", tenant_id: str = "tenant-a") -> UserPrincipal:
    return UserPrincipal(
        subject_id=subject_id,
        tenant_id=tenant_id,
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
        email="a@example.com",
    )


def _app_with_mocked_state() -> FastAPI:
    """Build a test FastAPI app with mocked app.state for auth middleware."""
    app = FastAPI()

    # Mock settings and database_runtime on app.state
    mock_settings = MagicMock()
    mock_settings.oidc_jwks_uri = "https://example.com/.well-known/jwks.json"
    mock_settings.oidc_issuer = "https://example.com"
    mock_settings.oidc_audience = "ajenda-api"
    app.state.settings = mock_settings
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
    """AuthContextMiddleware injects a principal when a valid Bearer token is provided."""
    app = _app_with_mocked_state()
    principal = _make_principal()

    with patch("backend.middleware.auth_context.OidcAuthenticator") as mock_oidc_cls:
        mock_oidc = MagicMock()
        mock_result = MagicMock()
        mock_result.principal = principal
        mock_oidc.validate_bearer_token.return_value = mock_result
        mock_oidc_cls.return_value = mock_oidc

        client = TestClient(app)
        response = client.get(
            "/protected",
            headers={"Authorization": "Bearer valid.token.here", "X-Tenant-Id": "tenant-a"},
        )

    assert response.status_code == 200
    assert response.json()["subject_id"] == "user-1"


def test_auth_context_denies_missing_auth() -> None:
    """AuthContextMiddleware returns 401 when no authentication credentials are provided."""
    app = _app_with_mocked_state()
    client = TestClient(app)
    response = client.get("/protected", headers={"X-Tenant-Id": "tenant-a"})
    assert response.status_code == 401
    assert "missing authentication" in response.json()["detail"]


def test_auth_context_allows_public_health_without_auth() -> None:
    """AuthContextMiddleware allows the /health endpoint without authentication."""
    app = _app_with_mocked_state()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_context_rejects_invalid_bearer_token() -> None:
    """AuthContextMiddleware returns 401 when the Bearer token fails validation."""
    from backend.auth.jwt_validator import JwtValidationError
    app = _app_with_mocked_state()

    with patch("backend.middleware.auth_context.OidcAuthenticator") as mock_oidc_cls:
        mock_oidc = MagicMock()
        mock_oidc.validate_bearer_token.side_effect = JwtValidationError("token expired")
        mock_oidc_cls.return_value = mock_oidc

        client = TestClient(app)
        response = client.get(
            "/protected",
            headers={"Authorization": "Bearer expired.token.here", "X-Tenant-Id": "tenant-a"},
        )

    assert response.status_code == 401

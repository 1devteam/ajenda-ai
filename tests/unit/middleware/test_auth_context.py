"""Unit tests for AuthContextMiddleware.

Tests the middleware in isolation using a minimal FastAPI app with
mocked app.state.settings so the middleware can resolve auth config.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def _token(payload: dict[str, object]) -> str:
    """Build a fake Bearer token (not cryptographically valid - for middleware bypass testing)."""
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def _app() -> FastAPI:
    """Build a minimal test app with the full middleware stack."""
    app = FastAPI()

    # Wire mock settings onto app.state so AuthContextMiddleware can resolve config
    mock_settings = MagicMock()
    mock_settings.oidc_issuer = "https://example.com/"
    mock_settings.oidc_audience = "ajenda-api"
    mock_settings.oidc_jwks_uri = "https://example.com/.well-known/jwks.json"
    app.state.settings = mock_settings

    # Wire mock database_runtime so ApiKeyService can be constructed
    mock_db = MagicMock()
    mock_db.session.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_db.session.return_value.__exit__ = MagicMock(return_value=False)
    app.state.database_runtime = mock_db

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


def test_auth_context_denies_missing_auth_by_default() -> None:
    """Requests without Authorization header receive HTTP 401."""
    client = TestClient(_app())
    response = client.get("/protected", headers={"X-Tenant-Id": "tenant-a"})
    assert response.status_code == 401
    # Accept either error message variant (implementation may vary)
    assert "missing authentication" in response.json()["detail"].lower()


def test_auth_context_allows_public_health_without_auth() -> None:
    """Health probe path is exempt from authentication requirements."""
    client = TestClient(_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_context_rejects_malformed_bearer_token() -> None:
    """Malformed Bearer tokens (not valid JWT format) receive HTTP 401."""
    client = TestClient(_app())
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer not-a-valid-token", "X-Tenant-Id": "tenant-a"},
    )
    assert response.status_code == 401

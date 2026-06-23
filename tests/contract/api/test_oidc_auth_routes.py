"""Contract tests for OIDC customer auth routes."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.routes.auth import router
from backend.app.config import Settings, get_settings
from backend.app.dependencies.db import get_db_session
from backend.services.oidc_login_service import (
    CustomerSessionResult,
    OidcAccountNotFoundError,
    OidcMultipleTenantsError,
    OidcPublicConfig,
    OidcStartResult,
    OidcTenantChoice,
)


@pytest.fixture()
def auth_client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    def _override_db() -> Generator[MagicMock, None, None]:
        db = MagicMock(spec=Session)
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        env="test",
        session_signing_secret="s" * 40,
        session_access_ttl_seconds=3600,
    )
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def test_oidc_config_route_returns_disabled_by_default(auth_client: TestClient) -> None:
    with patch("backend.api.routes.auth.OidcLoginService") as service_cls:
        service_cls.return_value.public_config.return_value = OidcPublicConfig(
            enabled=False,
            provider="generic",
            client_id=None,
            authorization_endpoint=None,
            scopes="openid email profile",
        )
        response = auth_client.get("/v1/auth/oidc/config")

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_oidc_start_route_returns_authorization_payload(auth_client: TestClient) -> None:
    with patch("backend.api.routes.auth.OidcLoginService") as service_cls:
        service_cls.return_value.start_login.return_value = OidcStartResult(
            login_intent_id="intent-1",
            authorization_url="https://idp.example.com/authorize?client_id=test",
            expires_at="2026-06-23T00:00:00+00:00",
        )
        response = auth_client.post(
            "/v1/auth/oidc/start",
            json={
                "redirect_uri": "http://localhost:8080/auth/callback",
                "code_challenge": "a" * 43,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["login_intent_id"] == "intent-1"
    assert "authorize" in body["authorization_url"]


def test_logout_route_requires_bearer_token(auth_client: TestClient) -> None:
    response = auth_client.post("/v1/auth/logout")
    assert response.status_code == 401


def test_oidc_callback_route_returns_account_not_found(auth_client: TestClient) -> None:
    with patch("backend.api.routes.auth.OidcLoginService") as service_cls:
        service_cls.return_value.complete_login.side_effect = OidcAccountNotFoundError("no account")
        response = auth_client.post(
            "/v1/auth/oidc/callback",
            json={
                "login_intent_id": "00000000-0000-0000-0000-000000000001",
                "code": "auth-code",
                "code_verifier": "a" * 43,
                "redirect_uri": "http://localhost:8080/auth/callback",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ACCOUNT_NOT_FOUND"


def test_oidc_callback_route_returns_multiple_tenants(auth_client: TestClient) -> None:
    with patch("backend.api.routes.auth.OidcLoginService") as service_cls:
        service_cls.return_value.complete_login.side_effect = OidcMultipleTenantsError(
            "multiple active workspaces",
            tenants=(
                OidcTenantChoice(tenant_id="tenant-a", org_name="Acme", slug="acme"),
                OidcTenantChoice(tenant_id="tenant-b", org_name="Beta", slug="beta"),
            ),
        )
        response = auth_client.post(
            "/v1/auth/oidc/callback",
            json={
                "login_intent_id": "00000000-0000-0000-0000-000000000001",
                "code": "auth-code",
                "code_verifier": "a" * 43,
                "redirect_uri": "http://localhost:8080/auth/callback",
            },
        )

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "MULTIPLE_TENANTS"
    assert len(body["tenants"]) == 2


def test_oidc_refresh_route_returns_session(auth_client: TestClient) -> None:
    with patch("backend.api.routes.auth.OidcLoginService") as service_cls:
        service_cls.return_value.refresh_session.return_value = CustomerSessionResult(
            access_token="access",
            refresh_token="refresh",
            expires_in=3600,
            refresh_expires_in=604800,
            tenant_id="tenant-1",
            email="owner@example.com",
            org_name="Acme",
            slug="acme",
            plan="free",
        )
        response = auth_client.post(
            "/v1/auth/session/refresh",
            json={"refresh_token": "r" * 40},
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access"

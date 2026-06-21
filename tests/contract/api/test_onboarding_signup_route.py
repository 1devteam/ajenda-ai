"""Contract tests for public onboarding signup ingress."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.onboarding import router
from backend.app.config import Settings, get_settings
from backend.app.dependencies.db import get_db_session
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware
from backend.utils.email_canonical import CanonicalEmail


def _settings(**overrides) -> Settings:
    defaults = {
        "env": "development",
        "signup_enabled": True,
        "signup_expose_verification_token": True,
        "signup_verify_url_base": "http://localhost/verify-email",
        "email_provider": "noop",
        "signup_idempotency_required": False,
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


def _build_client(*, settings: Settings | None = None) -> TestClient:
    app = FastAPI()
    app.state.settings = settings or _settings()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.include_router(router, prefix="/v1")

    def override_db():
        session = MagicMock()
        session.commit = MagicMock()
        session.rollback = MagicMock()
        yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_settings] = lambda: app.state.settings
    return TestClient(app, raise_server_exceptions=False)


def test_signup_public_ingress_without_auth_returns_201() -> None:
    client = _build_client()
    tenant_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    receipt = MagicMock(
        tenant_id=tenant_id,
        slug="acme",
        plan="free",
        email=CanonicalEmail(raw="owner@example.com", canonical="owner@example.com"),
        status="pending_verification",
        verification_expires_at=expires_at,
        verification_token_plaintext="verify-token",
        member_id=uuid.uuid4(),
    )

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.begin_signup.return_value = receipt
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/signup",
            json={"org_name": "Acme", "email": "owner@example.com"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_verification"
    assert body["verification_token"] == "verify-token"


def test_signup_requires_idempotency_key_in_production_mode() -> None:
    client = _build_client(settings=_settings(env="production", signup_idempotency_required=True))
    response = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "Acme", "email": "owner@example.com"},
    )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


def test_missions_route_still_requires_auth() -> None:
    from backend.api.routes.mission import router as mission_router

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.include_router(mission_router, prefix="/v1")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/missions",
        headers={"X-Tenant-Id": str(uuid.uuid4())},
        json={"name": "test"},
    )
    assert response.status_code == 401

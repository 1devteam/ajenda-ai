"""Contract tests for onboarding verify-email route."""

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


def _settings() -> Settings:
    return Settings.model_construct(
        env="development",
        signup_enabled=True,
        signup_idempotency_required=False,
    )


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.settings = _settings()
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


def test_verify_email_returns_bootstrap_key() -> None:
    client = _build_client()
    tenant_id = uuid.uuid4()
    bootstrap_expires = datetime.now(UTC) + timedelta(hours=72)
    result = MagicMock(
        tenant_id=tenant_id,
        key_id="kid123",
        api_key="kid123.secret",
        bootstrap_expires_at=bootstrap_expires,
    )

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.complete_verification.return_value = result
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/verify-email",
            json={"token": "a" * 32},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["key_id"] == "kid123"
    assert body["api_key"] == "kid123.secret"


def test_verify_email_invalid_token_returns_400() -> None:
    client = _build_client()
    from backend.services.tenant_onboarding_orchestrator import InvalidVerificationTokenError

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.complete_verification.side_effect = InvalidVerificationTokenError("invalid")
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/verify-email",
            json={"token": "b" * 32},
        )

    assert response.status_code == 400

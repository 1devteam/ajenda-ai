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


def _settings(**overrides) -> Settings:
    defaults = {
        "env": "development",
        "signup_enabled": True,
        "signup_expose_verification_token": False,
        "signup_require_idempotency_key": False,
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


def _verification_result() -> MagicMock:
    return MagicMock(
        tenant_id=uuid.uuid4(),
        key_id="kid123",
        api_key="kid123.secret",
        bootstrap_expires_at=datetime.now(UTC) + timedelta(hours=72),
    )


def test_verify_email_returns_bootstrap_key_for_email_code_pair() -> None:
    client = _build_client()
    result = _verification_result()

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.complete_verification.return_value = result
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/verify-email",
            json={"email": "owner@example.com", "code": "123456"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["key_id"] == "kid123"
    assert body["api_key"] == "kid123.secret"
    orchestrator.complete_verification.assert_called_once()
    assert orchestrator.complete_verification.call_args.kwargs["email"] == "owner@example.com"
    assert orchestrator.complete_verification.call_args.kwargs["code"] == "123456"


def test_verify_email_rejects_non_six_digit_code_at_contract_boundary() -> None:
    client = _build_client()
    response = client.post(
        "/v1/onboarding/verify-email",
        json={"email": "owner@example.com", "code": "abc"},
    )
    assert response.status_code == 422


def test_verify_email_rejects_legacy_token_when_exposure_disabled() -> None:
    client = _build_client(settings=_settings(signup_expose_verification_token=False))
    response = client.post(
        "/v1/onboarding/verify-email",
        json={"token": "123456:owner@example.com"},
    )
    assert response.status_code == 422


def test_verify_email_accepts_legacy_envelope_only_when_exposed() -> None:
    client = _build_client(settings=_settings(signup_expose_verification_token=True))
    result = _verification_result()

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.complete_verification.return_value = result
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/verify-email",
            json={"token": "123456:owner@example.com"},
        )

    assert response.status_code == 200
    assert orchestrator.complete_verification.call_args.kwargs["email"] == "owner@example.com"
    assert orchestrator.complete_verification.call_args.kwargs["code"] == "123456"


def test_verify_email_invalid_code_returns_400() -> None:
    client = _build_client()
    from backend.services.tenant_onboarding_orchestrator import InvalidVerificationTokenError

    with patch("backend.api.routes.onboarding.TenantOnboardingOrchestrator") as orchestrator_cls:
        orchestrator = MagicMock()
        orchestrator.complete_verification.side_effect = InvalidVerificationTokenError("invalid verification code")
        orchestrator_cls.return_value = orchestrator

        response = client.post(
            "/v1/onboarding/verify-email",
            json={"email": "owner@example.com", "code": "654321"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid verification code"

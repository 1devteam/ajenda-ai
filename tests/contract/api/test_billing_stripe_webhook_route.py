"""Contract: Stripe webhook public ingress path.

Proves POST /v1/billing/webhook/stripe reaches the handler without
X-Tenant-Id or API credentials, and that checkout/portal remain protected.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import stripe
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.router import build_api_router
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


class _FakeTenant:
    def is_deleted(self) -> bool:
        return False

    def is_suspended(self) -> bool:
        return False


class _FakeSession:
    def close(self) -> None:
        return None

    def get(self, _model: object, _tenant_id: object) -> _FakeTenant:
        return _FakeTenant()


class _FakeDbRuntime:
    def session_factory(self) -> _FakeSession:
        return _FakeSession()

    def session_scope(self):
        yield _FakeSession()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks",
        oidc_issuer="https://example",
        oidc_audience="ajenda",
    )
    app.state.database_runtime = _FakeDbRuntime()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.include_router(build_api_router())
    return app


def test_stripe_webhook_reaches_handler_without_tenant_or_auth() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "backend.api.routes.billing.StripeBillingService.handle_webhook",
    ) as mock_handle:
        response = client.post(
            "/v1/billing/webhook/stripe",
            content=b'{"id":"evt_test"}',
            headers={"stripe-signature": "t=1,v1=test"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_handle.assert_called_once()
    call_kwargs = mock_handle.call_args.kwargs
    assert call_kwargs["payload"] == b'{"id":"evt_test"}'
    assert call_kwargs["sig_header"] == "t=1,v1=test"


def test_stripe_webhook_returns_400_on_invalid_signature() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "backend.api.routes.billing.StripeBillingService.handle_webhook",
        side_effect=stripe.SignatureVerificationError("bad", "t=1,v1=bad"),
    ):
        response = client.post(
            "/v1/billing/webhook/stripe",
            content=b"bad",
            headers={"stripe-signature": "t=1,v1=bad"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Stripe signature."


def test_stripe_webhook_requires_signature_header() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/billing/webhook/stripe",
        content=b"{}",
    )

    assert response.status_code == 422


def test_billing_checkout_still_requires_auth() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/billing/checkout",
        json={
            "plan": "starter",
            "success_url": "https://app.example.com/success",
            "cancel_url": "https://app.example.com/cancel",
        },
        headers={"X-Tenant-Id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_billing_checkout_still_requires_tenant_header() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/billing/checkout",
        json={
            "plan": "starter",
            "success_url": "https://app.example.com/success",
            "cancel_url": "https://app.example.com/cancel",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body.get("code") == "MISSING_TENANT_ID"

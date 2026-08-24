"""Integration test: end-to-end paid customer loop over HTTP.

signup → verify → promote → account reads → Stripe webhook plan sync → ability launch
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.main import create_app

pytestmark = pytest.mark.integration

_TEST_PRICE_MAP = {"starter": "price_starter_test", "pro": "price_pro_test"}
_PRICE_MAP_PATCH = "backend.services.billing_stripe_integration._build_plan_price_map"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _auth(tenant_id: str, api_key: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-Api-Key": api_key,
    }


def _configure_paid_loop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_ENV", "test")
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    monkeypatch.setenv("AJENDA_SIGNUP_VERIFY_URL_BASE", "http://localhost:5173/verify-email")
    monkeypatch.setenv("STRIPE_PRICE_STARTER", "price_starter_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_integration")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_integration")
    get_settings.cache_clear()


def _make_checkout_event(tenant_id: str, customer_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"tenant_id": tenant_id},
                "customer": customer_id,
                "subscription": "sub_paid_loop_test",
            }
        },
    }


def _subscription_payload(tenant_id: str, customer_id: str) -> dict:
    return {
        "id": "sub_paid_loop_test",
        "customer": customer_id,
        "metadata": {"tenant_id": tenant_id},
        "items": {"data": [{"price": {"id": "price_pro_test"}}]},
    }


class TestPaidCustomerLoopReal:
    def test_http_paid_customer_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
        pg_engine: object,
    ) -> None:
        _configure_paid_loop_env(monkeypatch)
        email = f"paid-loop-{uuid.uuid4().hex[:8]}@example.com"

        with TestClient(create_app()) as client:
            signup = client.post(
                "/v1/onboarding/signup",
                json={"org_name": "Paid Loop Co", "email": email},
                headers=_idem(),
            )
            assert signup.status_code == 202, signup.text
            code = signup.json()["verification_code"]
            assert code and len(code) == 6

            verify = client.post(
                "/v1/onboarding/verify-email",
                json={"email": email, "code": code},
                headers=_idem(),
            )
            assert verify.status_code == 200, verify.text
            verify_body = verify.json()
            tenant_id = verify_body["tenant_id"]
            bootstrap_key = verify_body["api_key"]

            bootstrap_billing = client.get(
                "/v1/account/billing",
                headers=_auth(tenant_id, bootstrap_key),
            )
            assert bootstrap_billing.status_code == 403

            promote = client.post(
                "/v1/onboarding/promote-bootstrap-key",
                headers={**_auth(tenant_id, bootstrap_key), **_idem()},
            )
            assert promote.status_code == 200, promote.text
            operational_key = promote.json()["api_key"]

            me = client.get("/v1/account/me", headers=_auth(tenant_id, operational_key))
            assert me.status_code == 200
            me_body = me.json()
            assert me_body["tenant"]["plan"] == "free"
            assert me_body["membership"]["email"] == email

            usage = client.get("/v1/account/usage", headers=_auth(tenant_id, operational_key))
            assert usage.status_code == 200
            assert "missions_created" in usage.json()["usage"]

            billing = client.get("/v1/account/billing", headers=_auth(tenant_id, operational_key))
            assert billing.status_code == 200
            assert billing.json()["has_billing_account"] is False

            customer_id = f"cus_{uuid.uuid4().hex[:12]}"
            event = _make_checkout_event(tenant_id, customer_id)

            with (
                patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
                patch("stripe.Webhook.construct_event", return_value=event),
                patch(
                    "stripe.Subscription.retrieve",
                    return_value=_subscription_payload(tenant_id, customer_id),
                ),
                patch(
                    "stripe.Customer.create",
                    return_value={"id": customer_id},
                ),
            ):
                webhook = client.post(
                    "/v1/billing/webhook/stripe",
                    content=b"{}",
                    headers={"stripe-signature": "t=1,v1=test"},
                )
            assert webhook.status_code == 200, webhook.text

            me_after = client.get("/v1/account/me", headers=_auth(tenant_id, operational_key))
            assert me_after.status_code == 200
            assert me_after.json()["tenant"]["plan"] == "pro"

            proof = client.post(
                "/v1/ability-runtime/proofs/calendar-read",
                headers=_auth(tenant_id, operational_key),
            )
            assert proof.status_code == 202, proof.text
            proof_body = proof.json()
            assert proof_body["action"] == "calendar.read"
            assert proof_body["task_id"]
            assert proof_body["status"] in {"queued", "QUEUED", "planned", "PLANNED"}

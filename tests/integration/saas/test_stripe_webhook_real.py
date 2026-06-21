"""Integration tests: Stripe webhook billing authority against real Postgres.

Proves the full webhook → plan sync path:
  - Realistic checkout.session.completed payload (subscription ID only)
  - TenantLifecycleService.upgrade_plan governance events
  - stripe_webhook_events deduplication receipts
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import stripe
from sqlalchemy import text

from backend.domain.governance_event import GovernanceEvent
from backend.domain.stripe_webhook_event import StripeWebhookEvent
from backend.repositories.tenant_repository import TenantRepository
from backend.services.billing_stripe_integration import (
    StripeBillingService,
    StripeWebhookProcessingError,
)

pytestmark = pytest.mark.integration

_TEST_PRICE_MAP = {"starter": "price_starter_test", "pro": "price_pro_test"}
_PRICE_MAP_PATCH = "backend.services.billing_stripe_integration._build_plan_price_map"


def _slug() -> str:
    return f"stripe-webhook-{uuid.uuid4().hex[:8]}"


def _make_checkout_event(tenant_id: uuid.UUID, customer_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"tenant_id": str(tenant_id)},
                "customer": customer_id,
                "subscription": "sub_integration_test",
            }
        },
    }


def _subscription_payload(tenant_id: uuid.UUID, price_id: str, customer_id: str) -> dict:
    return {
        "id": "sub_integration_test",
        "customer": customer_id,
        "metadata": {"tenant_id": str(tenant_id)},
        "items": {"data": [{"price": {"id": price_id}}]},
    }


@pytest.fixture(autouse=True)
def _stripe_price_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_PRICE_STARTER", "price_starter_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_integration")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_integration")
    from backend.app.config import get_settings

    get_settings.cache_clear()


class TestStripeWebhookReal:
    def test_checkout_session_with_subscription_id_updates_plan_and_emits_governance(self, pg_session) -> None:
        """Webhook with subscription ID (not line_items) upgrades tenant via lifecycle authority."""
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Stripe Webhook Co.", slug=_slug(), plan="free")
        customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        tenant.stripe_customer_id = customer_id
        pg_session.flush()

        event = _make_checkout_event(tenant.id, customer_id)
        billing = StripeBillingService(pg_session)

        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(
                "stripe.Subscription.retrieve",
                return_value=_subscription_payload(tenant.id, "price_starter_test", customer_id),
            ),
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=test")

        pg_session.flush()
        pg_session.refresh(tenant)

        assert result.outcome == "applied"
        assert tenant.plan == "starter"

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant.id), event_type="tenant_plan_changed")
            .all()
        )
        assert len(events) == 1
        assert events[0].actor == "stripe-webhook"
        assert events[0].payload_json["old_plan"] == "free"
        assert events[0].payload_json["new_plan"] == "starter"

        receipt = pg_session.get(StripeWebhookEvent, event["id"])
        assert receipt is not None
        assert receipt.outcome == "applied"
        assert receipt.tenant_id == tenant.id

    def test_duplicate_event_is_idempotent(self, pg_session) -> None:
        """Second delivery of the same event ID does not double-apply."""
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Dedup Co.", slug=_slug(), plan="free")
        customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        tenant.stripe_customer_id = customer_id
        pg_session.flush()

        event = _make_checkout_event(tenant.id, customer_id)
        billing = StripeBillingService(pg_session)

        patches = (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(
                "stripe.Subscription.retrieve",
                return_value=_subscription_payload(tenant.id, "price_starter_test", customer_id),
            ),
        )
        with patches[0], patches[1], patches[2]:
            first = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=test")
            second = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=test")

        pg_session.flush()

        assert first.outcome == "applied"
        assert second.outcome == "duplicate"

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant.id), event_type="tenant_plan_changed")
            .all()
        )
        assert len(events) == 1

        receipts = pg_session.query(StripeWebhookEvent).filter_by(event_id=event["id"]).all()
        assert len(receipts) == 1

    def test_suspended_tenant_skips_upgrade(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Suspended Stripe Co.", slug=_slug(), plan="free")
        customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        tenant.stripe_customer_id = customer_id
        pg_session.flush()
        repo.suspend(tenant.id, reason="billing")
        pg_session.flush()

        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": "customer.subscription.updated",
            "data": {
                "object": _subscription_payload(tenant.id, "price_starter_test", customer_id),
            },
        }
        billing = StripeBillingService(pg_session)

        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=test")

        pg_session.flush()
        pg_session.refresh(tenant)

        assert result.outcome == "skipped"
        assert tenant.plan == "free"

    def test_retryable_failure_rolls_back_via_session_scope(self, pg_engine) -> None:
        """Retryable errors roll back the dedup insert so Stripe can redeliver."""
        from backend.app.config import get_settings
        from backend.db.session import DatabaseRuntime

        runtime = DatabaseRuntime(get_settings())
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        tenant_id: uuid.UUID | None = None

        try:
            with pytest.raises(StripeWebhookProcessingError):
                with runtime.session_context() as session:
                    repo = TenantRepository(session)
                    tenant = repo.create(name="Retry Co.", slug=_slug(), plan="free")
                    tenant.stripe_customer_id = f"cus_{uuid.uuid4().hex[:12]}"
                    session.flush()
                    tenant_id = tenant.id

                    event = {
                        "id": event_id,
                        "type": "checkout.session.completed",
                        "data": {
                            "object": {
                                "metadata": {"tenant_id": str(tenant.id)},
                                "customer": tenant.stripe_customer_id,
                                "subscription": "sub_fail_test",
                            }
                        },
                    }
                    billing = StripeBillingService(session)
                    with (
                        patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
                        patch("stripe.Webhook.construct_event", return_value=event),
                        patch("stripe.Subscription.retrieve", side_effect=stripe.StripeError("temporary")),
                    ):
                        billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=test")
        finally:
            with pg_engine.connect() as conn:
                receipt = conn.execute(
                    text("SELECT event_id FROM stripe_webhook_events WHERE event_id = :eid"),
                    {"eid": event_id},
                ).first()
                assert receipt is None
                if tenant_id is not None:
                    tenant_row = conn.execute(
                        text("SELECT plan FROM tenants WHERE id = :tid"),
                        {"tid": tenant_id},
                    ).first()
                    assert tenant_row is None

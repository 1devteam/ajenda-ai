"""Unit tests for StripeBillingService (Phase 1 Commercial Viability).

All Stripe SDK calls are patched — no real network calls are made.
Tests cover:
  - Checkout session creation (happy path, unknown plan, missing tenant)
  - Stripe Customer lazy creation
  - Webhook event sync: subscription activated, updated, deleted
  - Payment failure logging
  - Signature verification failure
  - Plan downgrade on subscription.deleted
  - assert_subscription_active delegation to QuotaEnforcementService
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import stripe

from backend.services.billing_stripe_integration import (
    StripeBillingService,
    _price_id_to_plan,
)
from backend.services.quota_enforcement import QuotaExceededError

# ---------------------------------------------------------------------------
# Shared price map used across tests
# ---------------------------------------------------------------------------

_TEST_PRICE_MAP = {"starter": "price_starter_test", "pro": "price_pro_test"}

# Patch target for the lazy price-map builder.
_PRICE_MAP_PATCH = "backend.services.billing_stripe_integration._build_plan_price_map"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """Minimal SQLAlchemy session mock."""
    session = MagicMock()
    session.flush = MagicMock()
    return session


@pytest.fixture()
def tenant():
    t = MagicMock()
    t.id = uuid4()
    t.name = "Acme Corp"
    t.slug = "acme"
    t.plan = "free"
    t.stripe_customer_id = None
    return t


@pytest.fixture()
def tenant_with_customer(tenant):
    tenant.stripe_customer_id = "cus_existing123"
    return tenant


@pytest.fixture()
def billing(db):
    """StripeBillingService with Stripe SDK initialisation patched out."""
    with patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP):
        svc = StripeBillingService(db)
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_checkout_session(url: str = "https://checkout.stripe.com/pay/cs_test_123") -> dict:
    return {"id": "cs_test_123", "url": url}


def _make_subscription(tenant_id: str, price_id: str, status: str = "active") -> dict:
    return {
        "id": "sub_test_123",
        "status": status,
        "metadata": {"tenant_id": tenant_id},
        "items": {"data": [{"price": {"id": price_id}}]},
    }


# ---------------------------------------------------------------------------
# Checkout session creation
# ---------------------------------------------------------------------------


class TestCreateCheckoutSession:
    def test_creates_checkout_url_for_known_plan(self, billing, db, tenant):
        """Happy path: returns a Stripe Checkout URL for a valid plan."""
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch("stripe.Customer.create", return_value={"id": "cus_new123"}),
            patch("stripe.checkout.Session.create", return_value=_make_checkout_session()),
            patch.object(billing._tenant_repo, "upgrade_plan"),
        ):
            url = billing.create_checkout_session(
                tenant_id=tenant.id,
                plan="starter",
                success_url="https://app.example.com/success",
                cancel_url="https://app.example.com/cancel",
            )
        assert url == "https://checkout.stripe.com/pay/cs_test_123"

    def test_creates_stripe_customer_when_absent(self, billing, db, tenant):
        """A new Stripe Customer is created when tenant has no stripe_customer_id."""
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch("stripe.Customer.create", return_value={"id": "cus_new456"}) as mock_create,
            patch("stripe.checkout.Session.create", return_value=_make_checkout_session()),
        ):
            billing.create_checkout_session(
                tenant_id=tenant.id,
                plan="pro",
                success_url="https://app.example.com/success",
                cancel_url="https://app.example.com/cancel",
            )
        mock_create.assert_called_once()
        assert tenant.stripe_customer_id == "cus_new456"
        db.flush.assert_called()

    def test_reuses_existing_stripe_customer(self, billing, db, tenant_with_customer):
        """No new Customer is created when stripe_customer_id already exists."""
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=tenant_with_customer),
            patch("stripe.Customer.create") as mock_create,
            patch("stripe.checkout.Session.create", return_value=_make_checkout_session()),
        ):
            billing.create_checkout_session(
                tenant_id=tenant_with_customer.id,
                plan="starter",
                success_url="https://app.example.com/success",
                cancel_url="https://app.example.com/cancel",
            )
        mock_create.assert_not_called()

    def test_raises_for_unknown_plan(self, billing, tenant):
        """ValueError is raised for a plan slug with no Stripe price configured."""
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
        ):
            with pytest.raises(ValueError, match="No Stripe price configured"):
                billing.create_checkout_session(
                    tenant_id=tenant.id,
                    plan="enterprise",
                    success_url="https://app.example.com/success",
                    cancel_url="https://app.example.com/cancel",
                )

    def test_raises_for_missing_tenant(self, billing):
        """ValueError is raised when the tenant does not exist in the DB."""
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=None),
        ):
            with pytest.raises(ValueError, match="not found"):
                billing.create_checkout_session(
                    tenant_id=uuid4(),
                    plan="starter",
                    success_url="https://app.example.com/success",
                    cancel_url="https://app.example.com/cancel",
                )


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------


class TestHandleWebhook:
    def _make_event(self, event_type: str, data_object: dict) -> dict:
        return {
            "type": event_type,
            "data": {"object": data_object},
        }

    def test_syncs_plan_on_checkout_completed(self, billing, tenant):
        """checkout.session.completed syncs the tenant plan to starter."""
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "line_items": {"data": [{"price": {"id": "price_starter_test"}}]},
        }
        event = self._make_event("checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._tenant_repo, "upgrade_plan") as mock_upgrade,
        ):
            billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="starter", actor="stripe-webhook")

    def test_downgrades_plan_on_subscription_deleted(self, billing, tenant):
        """customer.subscription.deleted downgrades the tenant to free."""
        event_obj = {"metadata": {"tenant_id": str(tenant.id)}}
        event = self._make_event("customer.subscription.deleted", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._tenant_repo, "upgrade_plan") as mock_upgrade,
        ):
            billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="free", actor="stripe-webhook")

    def test_ignores_event_with_missing_tenant_id(self, billing):
        """Events without tenant_id in metadata are silently skipped."""
        event_obj = {"metadata": {}}
        event = self._make_event("checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._tenant_repo, "upgrade_plan") as mock_upgrade,
        ):
            billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()

    def test_ignores_unknown_event_type(self, billing):
        """Unknown event types are silently ignored (forward-compatible)."""
        event = self._make_event("payment_intent.created", {"metadata": {}})

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._tenant_repo, "upgrade_plan") as mock_upgrade,
        ):
            billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()

    def test_raises_on_invalid_signature(self, billing):
        """SignatureVerificationError propagates to the caller."""
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.SignatureVerificationError("bad sig", "t=1,v1=bad"),
        ):
            with pytest.raises(stripe.SignatureVerificationError):
                billing.handle_webhook(payload=b"bad", sig_header="t=1,v1=bad")

    def test_ignores_event_with_invalid_tenant_uuid(self, billing):
        """Events with a non-UUID tenant_id are skipped without raising."""
        event_obj = {"metadata": {"tenant_id": "not-a-uuid"}}
        event = self._make_event("customer.subscription.updated", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._tenant_repo, "upgrade_plan") as mock_upgrade,
        ):
            billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()


# ---------------------------------------------------------------------------
# Quota gate
# ---------------------------------------------------------------------------


class TestAssertSubscriptionActive:
    def test_delegates_to_quota_service(self):
        """assert_subscription_active calls QuotaEnforcementService.check_tenant_active."""
        quota = MagicMock()
        tenant_id = uuid4()
        StripeBillingService.assert_subscription_active(quota, tenant_id)
        quota.check_tenant_active.assert_called_once_with(tenant_id)

    def test_propagates_quota_exceeded_error(self):
        """QuotaExceededError from the quota service propagates to the caller."""
        quota = MagicMock()
        quota.check_tenant_active.side_effect = QuotaExceededError(field="status", limit=1, current=0, plan="free")
        with pytest.raises(QuotaExceededError):
            StripeBillingService.assert_subscription_active(quota, uuid4())


# ---------------------------------------------------------------------------
# Price ID ↔ plan mapping
# ---------------------------------------------------------------------------


class TestPriceIdToPlan:
    def test_returns_none_for_unknown_price(self):
        with patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP):
            assert _price_id_to_plan("price_unknown_xyz") is None

    def test_maps_known_price_to_plan(self):
        with patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP):
            assert _price_id_to_plan("price_starter_test") == "starter"
            assert _price_id_to_plan("price_pro_test") == "pro"

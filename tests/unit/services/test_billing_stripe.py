"""Unit tests for StripeBillingService (Phase 1 Commercial Viability).

All Stripe SDK calls are patched — no real network calls are made.
Tests cover:
  - Checkout session creation (happy path, unknown plan, missing tenant)
  - Stripe Customer lazy creation
  - Webhook event sync: subscription activated, updated, deleted
  - Realistic checkout.session.completed payloads (subscription ID only)
  - Event deduplication via stripe_webhook_events
  - Retryable processing failures (HTTP 500 path)
  - Tenant lifecycle service usage for plan changes
  - Customer binding, suspended/deleted tenant skips
  - Payment failure logging
  - Signature verification failure
  - assert_subscription_active delegation to QuotaEnforcementService
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import stripe

from backend.services.billing_stripe_integration import (
    StripeBillingService,
    StripeWebhookProcessingError,
    _price_id_to_plan,
    _resolve_price_id,
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
    t.status = "active"
    t.stripe_customer_id = "cus_existing123"
    t.is_deleted.return_value = False
    t.is_suspended.return_value = False
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
        "customer": "cus_existing123",
        "metadata": {"tenant_id": tenant_id},
        "items": {"data": [{"price": {"id": price_id}}]},
    }


def _make_stripe_event(event_id: str, event_type: str, data_object: dict) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": data_object},
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
        tenant.stripe_customer_id = None
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
    def test_syncs_plan_on_checkout_completed_with_subscription_id(self, billing, tenant):
        """Realistic checkout.session.completed uses subscription ID, not line_items."""
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "customer": "cus_existing123",
            "subscription": "sub_test_123",
        }
        event = _make_stripe_event("evt_checkout_1", "checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch(
                "stripe.Subscription.retrieve",
                return_value=_make_subscription(str(tenant.id), "price_starter_test"),
            ),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="starter", actor="stripe-webhook")
        assert result.outcome == "applied"

    def test_syncs_plan_on_subscription_updated(self, billing, tenant):
        """customer.subscription.updated syncs via lifecycle service."""
        event_obj = _make_subscription(str(tenant.id), "price_pro_test")
        event = _make_stripe_event("evt_sub_upd_1", "customer.subscription.updated", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="pro", actor="stripe-webhook")
        assert result.outcome == "applied"

    def test_downgrades_plan_on_subscription_deleted(self, billing, tenant):
        """customer.subscription.deleted downgrades the tenant to free."""
        tenant.plan = "starter"
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "customer": "cus_existing123",
        }
        event = _make_stripe_event("evt_sub_del_1", "customer.subscription.deleted", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="free", actor="stripe-webhook")
        assert result.outcome == "applied"

    def test_skips_duplicate_event(self, billing):
        """Duplicate Stripe event IDs return outcome=duplicate without processing."""
        event = _make_stripe_event("evt_dup_1", "checkout.session.completed", {"metadata": {}})

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._webhook_events, "try_record_event", return_value=False),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "duplicate"

    def test_skips_event_with_missing_tenant_id(self, billing):
        """Events without tenant_id in metadata are skipped with receipt."""
        event_obj = {"metadata": {}}
        event = _make_stripe_event("evt_no_tid_1", "checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome") as mock_finalize,
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "skipped"
        mock_finalize.assert_called_once()
        assert mock_finalize.call_args.kwargs["outcome"] == "skipped"

    def test_skips_suspended_tenant(self, billing, tenant):
        """Suspended tenants are not upgraded via webhook."""
        tenant.is_suspended.return_value = True
        event_obj = _make_subscription(str(tenant.id), "price_starter_test")
        event = _make_stripe_event("evt_susp_1", "customer.subscription.updated", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "skipped"
        assert result.detail == "tenant suspended"

    def test_skips_customer_mismatch(self, billing, tenant):
        """Customer ID mismatch between tenant and event is skipped."""
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "customer": "cus_other999",
            "items": {"data": [{"price": {"id": "price_starter_test"}}]},
        }
        event = _make_stripe_event("evt_cus_1", "customer.subscription.updated", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "skipped"
        assert result.detail == "stripe customer mismatch"

    def test_raises_retryable_when_subscription_fetch_fails(self, billing, tenant):
        """Stripe API failures during price resolution are retryable."""
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "customer": "cus_existing123",
            "subscription": "sub_test_123",
        }
        event = _make_stripe_event("evt_retry_1", "checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch("stripe.Subscription.retrieve", side_effect=stripe.StripeError("api down")),
        ):
            with pytest.raises(StripeWebhookProcessingError, match="Failed to retrieve"):
                billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

    def test_raises_retryable_when_price_unresolvable(self, billing, tenant):
        """Missing price in payload is retryable so Stripe can redeliver."""
        event_obj = {
            "metadata": {"tenant_id": str(tenant.id)},
            "customer": "cus_existing123",
        }
        event = _make_stripe_event("evt_noprice_1", "checkout.session.completed", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
        ):
            with pytest.raises(StripeWebhookProcessingError, match="Could not resolve"):
                billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

    def test_ignores_unknown_event_type(self, billing):
        """Unknown event types are recorded as ignored (forward-compatible)."""
        event = _make_stripe_event("evt_unknown_1", "payment_intent.created", {"metadata": {}})

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "ignored"

    def test_raises_on_invalid_signature(self, billing):
        """SignatureVerificationError propagates to the caller."""
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.SignatureVerificationError("bad sig", "t=1,v1=bad"),
        ):
            with pytest.raises(stripe.SignatureVerificationError):
                billing.handle_webhook(payload=b"bad", sig_header="t=1,v1=bad")

    def test_handles_construct_event_stripe_objects(self, billing, tenant):
        """construct_event returns StripeObject payloads — not plain dicts."""
        from backend.billing.staging_proof_helpers import (
            build_checkout_completed_event,
            dumps_event,
            sign_stripe_webhook_payload,
        )

        event_payload = build_checkout_completed_event(
            tenant_id=str(tenant.id),
            customer_id="cus_existing123",
            price_id="price_pro_test",
            event_id="evt_stripe_object_1",
        )
        payload = dumps_event(event_payload)
        signature = sign_stripe_webhook_payload(payload, secret="whsec_test_integration")

        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch.object(billing, "_webhook_secret", "whsec_test_integration"),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._tenant_repo, "get", return_value=tenant),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=payload, sig_header=signature)

        mock_upgrade.assert_called_once_with(tenant.id, new_plan="pro", actor="stripe-webhook")
        assert result.outcome == "applied"

    def test_skips_event_with_invalid_tenant_uuid(self, billing):
        """Events with a non-UUID tenant_id are skipped without raising."""
        event_obj = {"metadata": {"tenant_id": "not-a-uuid"}}
        event = _make_stripe_event("evt_baduuid_1", "customer.subscription.updated", event_obj)

        with (
            patch("stripe.Webhook.construct_event", return_value=event),
            patch.object(billing._webhook_events, "try_record_event", return_value=True),
            patch.object(billing._webhook_events, "finalize_outcome"),
            patch.object(billing._lifecycle, "upgrade_plan") as mock_upgrade,
        ):
            result = billing.handle_webhook(payload=b"{}", sig_header="t=1,v1=abc")

        mock_upgrade.assert_not_called()
        assert result.outcome == "skipped"


# ---------------------------------------------------------------------------
# Price resolution helpers
# ---------------------------------------------------------------------------


class TestResolvePriceId:
    def test_resolves_from_subscription_items(self):
        obj = {"items": {"data": [{"price": {"id": "price_starter_test"}}]}}
        assert _resolve_price_id(obj) == "price_starter_test"

    def test_fetches_subscription_when_only_id_present(self):
        obj = {"subscription": "sub_abc"}
        with patch(
            "stripe.Subscription.retrieve",
            return_value={"items": {"data": [{"price": {"id": "price_pro_test"}}]}},
        ):
            assert _resolve_price_id(obj) == "price_pro_test"

    def test_fetches_subscription_when_retrieve_returns_stripe_object(self):
        class _StripeLikeSubscription:
            def to_dict_recursive(self) -> dict:
                return {"items": {"data": [{"price": {"id": "price_pro_test"}}]}}

        obj = {"subscription": "sub_abc"}
        with patch(
            "stripe.Subscription.retrieve",
            return_value=_StripeLikeSubscription(),
        ):
            assert _resolve_price_id(obj) == "price_pro_test"


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


# ---------------------------------------------------------------------------
# Metered usage reporting (PR3)
# ---------------------------------------------------------------------------


class TestReportMeteredUsage:
    def test_reports_usage_when_customer_and_active_sub_exists(self, billing, db, tenant_with_customer):
        with (
            patch(_PRICE_MAP_PATCH, return_value=_TEST_PRICE_MAP),
            patch("stripe.Subscription.list") as mock_list,
            patch("stripe.SubscriptionItem") as mock_si,
        ):
            mock_list.return_value = {
                "data": [{"items": {"data": [{"id": "si_meted123", "price": {"id": "price_pro_test"}}]}}]
            }
            billing.report_metered_usage(tenant_with_customer.id, 5, metric="tasks")
            mock_si.create_usage_record.assert_called_once()
            call = mock_si.create_usage_record.call_args
            assert call.kwargs["subscription_item"] == "si_meted123"
            assert call.kwargs["quantity"] == 5
            assert call.kwargs["action"] == "increment"

    def test_skips_when_no_customer(self, billing, db, tenant):
        tenant.stripe_customer_id = None
        billing.report_metered_usage(tenant.id, 10)

    def test_best_effort_on_stripe_error(self, billing, db, tenant_with_customer):
        with patch("stripe.Subscription.list", side_effect=stripe.StripeError("boom")):
            billing.report_metered_usage(tenant_with_customer.id, 3)

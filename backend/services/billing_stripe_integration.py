"""Ajenda AI — Stripe Billing Integration (Phase 1 Commercial Viability).

Responsibilities:
  - Generate Stripe Checkout sessions for plan upgrades.
  - Create Stripe Customer records on first checkout (lazy creation).
  - Handle Stripe webhook events to sync subscription state into TenantPlan.
  - Enforce active-subscription gate via QuotaEnforcementService.

Design decisions:
  - Webhook handling is idempotent: events are processed only if the
    subscription metadata carries a valid tenant_id.
  - Plan changes are written via TenantRepository.upgrade_plan() so that
    the existing audit-event and governance-event machinery fires.
  - Stripe API key is configured lazily inside StripeBillingService.__init__
    rather than at module import time. This prevents test isolation failures
    caused by get_settings() reading empty env vars during test collection.
  - QuotaExceededError is re-raised as-is; the HTTP layer maps it to 402.
  - No cross-tenant operations: every method is scoped to a single tenant_id.

Security:
  - Webhook signature is verified via stripe.Webhook.construct_event before
    any payload is trusted.
  - stripe_customer_id is stored on the Tenant row (migration 0025).
"""

from __future__ import annotations

import logging
from uuid import UUID

import stripe
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.domain.tenant import Tenant
from backend.repositories.tenant_repository import TenantRepository
from backend.services.quota_enforcement import QuotaEnforcementService

logger = logging.getLogger(__name__)


def _build_plan_price_map() -> dict[str, str]:
    """Build the plan → Stripe Price ID mapping from current Settings.

    Called lazily so that test environments that patch Settings or env vars
    see the correct values without module-level side effects.
    """
    s = get_settings()
    return {
        "starter": s.STRIPE_PRICE_STARTER,
        "pro": s.STRIPE_PRICE_PRO,
    }


def _get_price_id(plan: str) -> str:
    """Return the Stripe Price ID for the given plan slug.

    Raises ValueError for unknown or non-upgradeable plans.
    """
    plan_map = _build_plan_price_map()
    price_id = plan_map.get(plan.lower())
    if not price_id:
        raise ValueError(f"No Stripe price configured for plan {plan!r}. Valid upgradeable plans: starter, pro.")
    return price_id


def _ensure_stripe_customer(tenant: Tenant, session: Session) -> str:
    """Return the Stripe Customer ID for the tenant, creating one if absent.

    Persists the new customer ID back to the Tenant row so subsequent calls
    reuse the same Stripe customer.
    """
    if tenant.stripe_customer_id:
        return tenant.stripe_customer_id

    customer = stripe.Customer.create(
        name=tenant.name,
        metadata={"tenant_id": str(tenant.id), "slug": tenant.slug},
    )
    customer_id: str = str(customer["id"])
    tenant.stripe_customer_id = customer_id
    session.flush()
    logger.info("Created Stripe customer %s for tenant %s", customer_id, tenant.id)
    return customer_id


def _price_id_to_plan(price_id: str) -> str | None:
    """Reverse-map a Stripe Price ID to a plan slug."""
    plan_map = _build_plan_price_map()
    reverse: dict[str, str] = {v: k for k, v in plan_map.items() if v}
    return reverse.get(price_id)


# ---------------------------------------------------------------------------
# Public service interface
# ---------------------------------------------------------------------------


class StripeBillingService:
    """Production-grade Stripe integration for Ajenda AI SaaS monetisation."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenant_repo = TenantRepository(session)
        # Configure Stripe SDK lazily so tests can patch settings before init.
        settings = get_settings()
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self._webhook_secret: str = settings.STRIPE_WEBHOOK_SECRET

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Generate a Stripe Checkout URL for the given tenant and plan.

        Returns the hosted checkout URL. The caller should redirect the user
        to this URL. On success, Stripe POSTs to the webhook endpoint which
        syncs the plan into the database.

        Raises:
            ValueError: if the tenant does not exist or the plan is unknown.
        """
        tenant = self._tenant_repo.get(tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found.")

        price_id = _get_price_id(plan)
        customer_id = _ensure_stripe_customer(tenant, self._session)

        checkout = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": str(tenant_id)},
            subscription_data={"metadata": {"tenant_id": str(tenant_id)}},
        )
        logger.info(
            "Created Stripe checkout session %s for tenant %s plan=%s",
            checkout["id"],
            tenant_id,
            plan,
        )
        return str(checkout["url"])

    # ------------------------------------------------------------------
    # Webhook sync
    # ------------------------------------------------------------------

    def handle_webhook(self, *, payload: bytes, sig_header: str) -> None:
        """Process a verified Stripe webhook event.

        Signature is verified before any payload is trusted. Unknown event
        types are silently ignored (forward-compatible).

        Raises:
            stripe.SignatureVerificationError: if the signature is invalid.
        """
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload,
            sig_header,
            self._webhook_secret,
        )

        event_type: str = event["type"]
        data_object = event["data"]["object"]

        if event_type in ("checkout.session.completed", "customer.subscription.updated"):
            self._sync_subscription(data_object)
        elif event_type == "customer.subscription.deleted":
            self._handle_subscription_deleted(data_object)
        elif event_type == "invoice.payment_failed":
            self._handle_payment_failed(data_object)
        else:
            logger.debug("Ignoring unhandled Stripe event type: %s", event_type)

    def _sync_subscription(self, obj: dict) -> None:  # type: ignore[type-arg]
        """Sync a Stripe subscription or checkout object into the Tenant plan."""
        metadata = obj.get("metadata") or {}
        tenant_id_str = metadata.get("tenant_id") or (
            (obj.get("subscription_data") or {}).get("metadata", {}).get("tenant_id")
        )
        if not tenant_id_str:
            logger.warning("Stripe event missing tenant_id in metadata — skipping.")
            return

        try:
            tenant_id = UUID(tenant_id_str)
        except ValueError:
            logger.error("Stripe event has invalid tenant_id %r — skipping.", tenant_id_str)
            return

        # Determine the plan slug from the Stripe price ID.
        price_id: str | None = None
        if "items" in obj:
            items = obj["items"].get("data", [])
            if items:
                price_id = items[0].get("price", {}).get("id")
        elif "line_items" in obj:
            line_items = obj["line_items"].get("data", [])
            if line_items:
                price_id = line_items[0].get("price", {}).get("id")

        new_plan = _price_id_to_plan(price_id) if price_id else None
        if not new_plan:
            logger.warning(
                "Could not map Stripe price %r to a plan slug — skipping plan sync.",
                price_id,
            )
            return

        tenant = self._tenant_repo.get(tenant_id)
        if tenant is None:
            logger.error("Stripe webhook references unknown tenant %s — skipping.", tenant_id)
            return

        if tenant.plan != new_plan:
            self._tenant_repo.upgrade_plan(tenant_id, new_plan=new_plan, actor="stripe-webhook")
            logger.info("Synced tenant %s plan: %s → %s", tenant_id, tenant.plan, new_plan)

    def _handle_subscription_deleted(self, obj: dict) -> None:  # type: ignore[type-arg]
        """Downgrade tenant to free plan when subscription is cancelled."""
        metadata = obj.get("metadata") or {}
        tenant_id_str = metadata.get("tenant_id")
        if not tenant_id_str:
            return
        try:
            tenant_id = UUID(tenant_id_str)
        except ValueError:
            return
        self._tenant_repo.upgrade_plan(tenant_id, new_plan="free", actor="stripe-webhook")
        logger.info("Subscription cancelled for tenant %s — downgraded to free.", tenant_id)

    def _handle_payment_failed(self, obj: dict) -> None:  # type: ignore[type-arg]
        """Log payment failures. Suspension is handled by subscription.deleted event."""
        customer_id = obj.get("customer")
        logger.warning("Payment failed for Stripe customer %s.", customer_id)

    # ------------------------------------------------------------------
    # Quota gate
    # ------------------------------------------------------------------

    @staticmethod
    def assert_subscription_active(
        quota_service: QuotaEnforcementService,
        tenant_id: UUID,
    ) -> None:
        """Hard gate: raise QuotaExceededError if the tenant subscription has lapsed.

        Delegates to QuotaEnforcementService.check_tenant_active() which
        already handles suspended/deleted tenants. This method is the billing
        layer's entry point into that existing enforcement chain.
        """
        quota_service.check_tenant_active(tenant_id)

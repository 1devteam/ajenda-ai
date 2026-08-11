"""Ajenda AI — Stripe Billing Integration (Phase 1 Commercial Viability).

Responsibilities:
  - Generate Stripe Checkout sessions for plan upgrades.
  - Create Stripe Customer records on first checkout (lazy creation).
  - Handle Stripe webhook events to sync subscription state into TenantPlan.
  - Enforce active-subscription gate via QuotaEnforcementService.

Design decisions:
  - Webhook handling is idempotent via stripe_webhook_events (event ID dedup).
  - Plan changes go through TenantLifecycleService.upgrade_plan() so
    tenant_plan_changed governance events are emitted.
  - Stripe API key is configured lazily inside StripeBillingService.__init__
    rather than at module import time. This prevents test isolation failures
    caused by get_settings() reading empty env vars during test collection.
  - Retryable processing failures raise StripeWebhookProcessingError so the
    HTTP layer returns 500 and Stripe retries. Benign skips return 200.
  - QuotaExceededError is re-raised as-is; the HTTP layer maps it to 402.
  - No cross-tenant operations: every method is scoped to a single tenant_id.

Security:
  - Webhook signature is verified via stripe.Webhook.construct_event before
    any payload is trusted.
  - stripe_customer_id is stored on the Tenant row (migration 0025).
  - Webhook events verify customer ID binding when both sides are known.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import stripe
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.domain.tenant import Tenant
from backend.repositories.stripe_webhook_event_repository import StripeWebhookEventRepository
from backend.repositories.tenant_repository import TenantRepository
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.tenant_lifecycle import TenantLifecycleService

logger = logging.getLogger(__name__)


class StripeWebhookProcessingError(Exception):
    """Raised when webhook processing should fail the HTTP request."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class StripeWebhookResult:
    """Structured outcome returned by handle_webhook."""

    event_id: str
    event_type: str
    outcome: str
    detail: str | None = None


def _normalize_stripe_object(obj: object) -> dict[str, Any]:
    """Convert Stripe SDK objects from construct_event into plain dicts."""
    if isinstance(obj, dict):
        return obj
    to_dict_recursive = getattr(obj, "to_dict_recursive", None)
    if callable(to_dict_recursive):
        return dict(to_dict_recursive())
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    raise StripeWebhookProcessingError(
        "Unsupported Stripe webhook payload object type",
        retryable=False,
    )


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


def _extract_customer_id(obj: dict) -> str | None:  # type: ignore[type-arg]
    """Return the Stripe customer ID from a webhook payload object."""
    customer = obj.get("customer")
    if customer is None:
        return None
    if isinstance(customer, str):
        return customer
    if isinstance(customer, dict):
        customer_id = customer.get("id")
        return str(customer_id) if customer_id else None
    return None


def _resolve_tenant_id_from_metadata(obj: dict) -> str | None:  # type: ignore[type-arg]
    """Extract tenant_id from Stripe object metadata."""
    metadata = obj.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    if tenant_id:
        return str(tenant_id)
    subscription_data = obj.get("subscription_data") or {}
    sub_metadata = subscription_data.get("metadata") or {}
    nested = sub_metadata.get("tenant_id")
    return str(nested) if nested else None


def _report_subscription_item_usage(
    *,
    subscription_item_id: str,
    quantity: int,
    timestamp: int,
) -> None:
    """Create a Stripe metered usage record (SDK stubs omit this class method)."""
    create_usage_record = getattr(stripe.SubscriptionItem, "create_usage_record", None)
    if not callable(create_usage_record):
        raise stripe.StripeError("Stripe SDK missing SubscriptionItem.create_usage_record")
    create_usage_record(
        subscription_item=subscription_item_id,
        quantity=quantity,
        timestamp=timestamp,
        action="increment",
    )


def _price_from_subscription_object(subscription: dict) -> str | None:  # type: ignore[type-arg]
    """Extract the first subscription item price ID from a subscription object."""
    items = subscription.get("items") or {}
    if not isinstance(items, dict):
        return None
    data = items.get("data") or []
    if not data:
        return None
    price = data[0].get("price")
    if isinstance(price, dict):
        price_id = price.get("id")
        return str(price_id) if price_id else None
    if isinstance(price, str):
        return price
    return None


def _resolve_price_id(obj: dict) -> str | None:  # type: ignore[type-arg]
    """Resolve the Stripe price ID from a checkout session or subscription object.

    Real Stripe checkout.session.completed payloads typically carry a subscription
    ID string rather than expanded line_items. Subscription objects carry items.
    """
    if "items" in obj:
        price_id = _price_from_subscription_object(obj)
        if price_id:
            return price_id

    line_items = obj.get("line_items")
    if isinstance(line_items, dict):
        data = line_items.get("data") or []
        if data:
            price = data[0].get("price")
            if isinstance(price, dict):
                nested_id = price.get("id")
                if nested_id:
                    return str(nested_id)
            if isinstance(price, str):
                return price

    subscription = obj.get("subscription")
    if subscription is None:
        return None
    if isinstance(subscription, dict):
        return _resolve_price_id(subscription)
    if isinstance(subscription, str):
        try:
            retrieved = stripe.Subscription.retrieve(subscription)
        except stripe.StripeError as exc:
            raise StripeWebhookProcessingError(
                f"Failed to retrieve Stripe subscription {subscription!r}: {exc}",
                retryable=True,
            ) from exc
        return _resolve_price_id(_normalize_stripe_object(retrieved))

    return None


# ---------------------------------------------------------------------------
# Public service interface
# ---------------------------------------------------------------------------


class StripeBillingService:
    """Production-grade Stripe integration for Ajenda AI SaaS monetisation."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenant_repo = TenantRepository(session)
        self._webhook_events = StripeWebhookEventRepository(session)
        self._lifecycle = TenantLifecycleService(session)
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

    def handle_webhook(self, *, payload: bytes, sig_header: str) -> StripeWebhookResult:
        """Process a verified Stripe webhook event.

        Signature is verified before any payload is trusted. Duplicate event IDs
        are ignored. Retryable failures raise StripeWebhookProcessingError.

        Raises:
            stripe.SignatureVerificationError: if the signature is invalid.
            StripeWebhookProcessingError: if processing should fail (retryable).
        """
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            self._webhook_secret,
        )

        event_id: str = str(event["id"])
        event_type: str = str(event["type"])
        data_object = _normalize_stripe_object(event["data"]["object"])

        if not self._webhook_events.try_record_event(event_id=event_id, event_type=event_type):
            logger.info("Duplicate Stripe webhook event %s — skipping.", event_id)
            return StripeWebhookResult(
                event_id=event_id,
                event_type=event_type,
                outcome="duplicate",
                detail="event already processed",
            )

        outcome, detail, tenant_id = self._dispatch_event(event_type, data_object)
        self._webhook_events.finalize_outcome(
            event_id=event_id,
            outcome=outcome,
            tenant_id=tenant_id,
            detail=detail,
        )
        return StripeWebhookResult(
            event_id=event_id,
            event_type=event_type,
            outcome=outcome,
            detail=detail,
        )

    def _dispatch_event(
        self,
        event_type: str,
        data_object: dict,  # type: ignore[type-arg]
    ) -> tuple[str, str | None, uuid.UUID | None]:
        if event_type in ("checkout.session.completed", "customer.subscription.updated"):
            return self._sync_subscription(data_object)
        if event_type == "customer.subscription.deleted":
            return self._handle_subscription_deleted(data_object)
        if event_type == "invoice.payment_failed":
            return self._handle_payment_failed(data_object)
        logger.debug("Ignoring unhandled Stripe event type: %s", event_type)
        return "ignored", f"unhandled event type {event_type}", None

    def _sync_subscription(self, obj: dict) -> tuple[str, str | None, uuid.UUID | None]:  # type: ignore[type-arg]
        """Sync a Stripe subscription or checkout object into the Tenant plan."""
        tenant_id_str = _resolve_tenant_id_from_metadata(obj)
        if not tenant_id_str:
            logger.warning("Stripe event missing tenant_id in metadata — skipping.")
            return "skipped", "missing tenant_id in metadata", None

        try:
            tenant_id = UUID(tenant_id_str)
        except ValueError:
            logger.error("Stripe event has invalid tenant_id %r — skipping.", tenant_id_str)
            return "skipped", f"invalid tenant_id {tenant_id_str!r}", None

        tenant = self._tenant_repo.get(tenant_id)
        if tenant is None:
            logger.error("Stripe webhook references unknown tenant %s — skipping.", tenant_id)
            return "skipped", f"unknown tenant {tenant_id}", tenant_id

        if tenant.is_deleted():
            logger.warning("Stripe webhook for deleted tenant %s — skipping plan sync.", tenant_id)
            return "skipped", "tenant deleted", tenant_id
        if tenant.is_suspended():
            logger.warning("Stripe webhook for suspended tenant %s — skipping plan sync.", tenant_id)
            return "skipped", "tenant suspended", tenant_id

        event_customer_id = _extract_customer_id(obj)
        if tenant.stripe_customer_id and event_customer_id and tenant.stripe_customer_id != event_customer_id:
            logger.warning(
                "Stripe customer mismatch for tenant %s: expected %s got %s — skipping.",
                tenant_id,
                tenant.stripe_customer_id,
                event_customer_id,
            )
            return "skipped", "stripe customer mismatch", tenant_id

        try:
            price_id = _resolve_price_id(obj)
        except StripeWebhookProcessingError:
            raise

        if not price_id:
            raise StripeWebhookProcessingError(
                "Could not resolve Stripe price ID from event payload",
                retryable=True,
            )

        new_plan = _price_id_to_plan(price_id)
        if not new_plan:
            logger.warning(
                "Could not map Stripe price %r to a plan slug — skipping plan sync.",
                price_id,
            )
            return "skipped", f"unknown price {price_id}", tenant_id

        if tenant.plan == new_plan:
            return "skipped", f"plan already {new_plan}", tenant_id

        self._lifecycle.upgrade_plan(tenant_id, new_plan=new_plan, actor="stripe-webhook")
        logger.info("Synced tenant %s plan: %s → %s", tenant_id, tenant.plan, new_plan)
        return "applied", f"plan changed to {new_plan}", tenant_id

    def _handle_subscription_deleted(self, obj: dict) -> tuple[str, str | None, uuid.UUID | None]:  # type: ignore[type-arg]
        """Downgrade tenant to free plan when subscription is cancelled."""
        tenant_id_str = _resolve_tenant_id_from_metadata(obj)
        if not tenant_id_str:
            return "skipped", "missing tenant_id in metadata", None

        try:
            tenant_id = UUID(tenant_id_str)
        except ValueError:
            return "skipped", f"invalid tenant_id {tenant_id_str!r}", None

        tenant = self._tenant_repo.get(tenant_id)
        if tenant is None:
            return "skipped", f"unknown tenant {tenant_id}", tenant_id

        if tenant.is_deleted() or tenant.is_suspended():
            return "skipped", f"tenant {tenant.status}", tenant_id

        event_customer_id = _extract_customer_id(obj)
        if tenant.stripe_customer_id and event_customer_id and tenant.stripe_customer_id != event_customer_id:
            return "skipped", "stripe customer mismatch", tenant_id

        if tenant.plan == "free":
            return "skipped", "plan already free", tenant_id

        self._lifecycle.upgrade_plan(tenant_id, new_plan="free", actor="stripe-webhook")
        logger.info("Subscription cancelled for tenant %s — downgraded to free.", tenant_id)
        return "applied", "plan downgraded to free", tenant_id

    def _handle_payment_failed(self, obj: dict) -> tuple[str, str | None, uuid.UUID | None]:  # type: ignore[type-arg]
        """Log payment failures for dunning. Suspension on repeated failure is
        handled via subscription.deleted in Stripe (or manual admin).
        """
        customer_id = obj.get("customer")
        logger.warning(
            "Dunning: payment failed for Stripe customer %s. Review subscription.",
            customer_id,
        )
        return "ignored", "payment failure logged", None

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

    # ------------------------------------------------------------------
    # Metered usage reporting (PR3 Billing v2)
    # ------------------------------------------------------------------

    def report_metered_usage(
        self,
        tenant_id: UUID,
        quantity: int,
        *,
        metric: str = "tasks",
    ) -> None:
        """Report incremental usage to Stripe for metered billing (best effort).

        Looks up the tenant's active subscription items via the Stripe customer,
        finds a matching metered price, and creates a usage record.

        Failures are logged only; they never block quota enforcement or task
        admission.
        """
        if quantity <= 0:
            return
        tenant = self._tenant_repo.get(tenant_id)
        if tenant is None or not tenant.stripe_customer_id:
            return
        try:
            subs = _normalize_stripe_object(
                stripe.Subscription.list(
                    customer=tenant.stripe_customer_id,
                    status="active",
                    limit=3,
                )
            )
            for sub_raw in subs.get("data", []):
                sub = sub_raw if isinstance(sub_raw, dict) else _normalize_stripe_object(sub_raw)
                items_raw = sub.get("items") or {}
                items = items_raw if isinstance(items_raw, dict) else _normalize_stripe_object(items_raw)
                for item_raw in items.get("data", []):
                    item = item_raw if isinstance(item_raw, dict) else _normalize_stripe_object(item_raw)
                    price = item.get("price", {})
                    if not isinstance(price, dict):
                        price = _normalize_stripe_object(price)
                    price_id = price.get("id")
                    if price_id and _price_id_to_plan(price_id):
                        _report_subscription_item_usage(
                            subscription_item_id=str(item["id"]),
                            quantity=quantity,
                            timestamp=int(time.time()),
                        )
                        logger.info(
                            "Reported metered %s usage +%s for tenant %s (item=%s)",
                            metric,
                            quantity,
                            tenant_id,
                            item["id"],
                        )
                        return
        except stripe.StripeError as exc:
            logger.warning("Stripe metered usage report failed for tenant %s: %s", tenant_id, exc)

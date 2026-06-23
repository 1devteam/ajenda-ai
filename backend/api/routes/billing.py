"""Ajenda AI — Billing API Routes (Phase 1 Commercial Viability).

All tenant-scoped routes use get_tenant_db_session + get_request_tenant_id
per the TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.

Routes:
  POST /billing/checkout          — Create a Stripe Checkout session.
  POST /billing/webhook/stripe    — Public Stripe webhook receiver.
  GET  /billing/portal            — Create a Stripe Customer Portal session.

The router prefix is /billing (no /v1 prefix here — the v1 APIRouter in
api/router.py applies the /v1 prefix when this router is included).
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.config import get_settings
from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.billing.staging_proof_helpers import stripe_checkout_ready
from backend.services.billing_stripe_integration import (
    StripeBillingService,
    StripeWebhookProcessingError,
)
from backend.services.quota_enforcement import QuotaExceededError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"]
    success_url: HttpUrl
    cancel_url: HttpUrl


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


# ---------------------------------------------------------------------------
# Tenant-scoped routes
# ---------------------------------------------------------------------------


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a Stripe Checkout session for a plan upgrade.",
)
def create_checkout(
    body: CheckoutRequest,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CheckoutResponse:
    """Return a Stripe Checkout URL scoped to the authenticated tenant."""
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.BILLING_MANAGE,
        tenant_id=tenant_id,
    )
    settings = get_settings()
    if not stripe_checkout_ready(
        secret_key=settings.STRIPE_SECRET_KEY,
        price_pro=settings.STRIPE_PRICE_PRO if body.plan == "pro" else settings.STRIPE_PRICE_STARTER,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Stripe checkout is not configured. Set STRIPE_SECRET_KEY (sk_test_…), "
                "STRIPE_PUBLISHABLE_KEY, and price IDs in deploy/compose/.env.staging, "
                "run bash deploy/scripts/stripe-staging-bootstrap.sh, sync to .env.prod, "
                "and restart the API."
            ),
        )
    billing = StripeBillingService(db)
    try:
        url = billing.create_checkout_session(
            tenant_id=tenant_id,
            plan=body.plan,
            success_url=str(body.success_url),
            cancel_url=str(body.cancel_url),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except stripe.StripeError as exc:
        logger.error("Stripe checkout error for tenant %s: %s", tenant_id, exc)
        detail = "Stripe checkout is unavailable. Configure STRIPE_SECRET_KEY and price IDs, then restart the API."
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    return CheckoutResponse(checkout_url=url)


@router.get(
    "/portal",
    response_model=PortalResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a Stripe Customer Portal session for subscription management.",
)
def create_portal(
    return_url: str,
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> PortalResponse:
    """Return a Stripe Customer Portal URL for the authenticated tenant."""
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.BILLING_MANAGE,
        tenant_id=tenant_id,
    )
    from backend.repositories.tenant_repository import TenantRepository

    tenant = TenantRepository(db).get(tenant_id)
    if tenant is None or not tenant.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No billing account found for this tenant. Complete a checkout first.",
        )
    try:
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url,
        )
    except stripe.StripeError as exc:
        logger.error("Stripe portal error for tenant %s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Billing portal unavailable. Please try again later.",
        ) from exc
    return PortalResponse(portal_url=str(session["url"]))


# ---------------------------------------------------------------------------
# Public Stripe webhook — no tenant header required
# ---------------------------------------------------------------------------


@router.post(
    "/webhook/stripe",
    status_code=status.HTTP_200_OK,
    summary="Stripe webhook receiver. Signature verified before processing.",
    include_in_schema=False,  # Not a public API — Stripe-internal only.
)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
    stripe_signature: str = Header(..., alias="stripe-signature"),
) -> dict[str, str]:
    """Receive and process Stripe webhook events.

    Public ingress path (no X-Tenant-Id or API credentials). Authority is
    Stripe signature verification; tenant scope is resolved from event metadata.
    Returns 400 on signature failure so Stripe retries with the correct secret.
    Returns 500 on retryable processing failures so Stripe retries delivery.
    """
    payload = await request.body()
    billing = StripeBillingService(db)
    try:
        result = billing.handle_webhook(payload=payload, sig_header=stripe_signature)
    except stripe.SignatureVerificationError as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature.",
        ) from exc
    except StripeWebhookProcessingError as exc:
        if exc.retryable:
            logger.error("Stripe webhook retryable processing failure: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stripe webhook processing failed; retry later.",
            ) from exc
        logger.warning("Stripe webhook non-retryable processing failure: %s", exc)
        return {"status": "ok", "outcome": "failed", "detail": str(exc)}
    response: dict[str, str] = {"status": "ok", "outcome": result.outcome}
    if result.detail:
        response["detail"] = result.detail
    return response

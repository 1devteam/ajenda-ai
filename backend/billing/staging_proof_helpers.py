"""Helpers for local Stripe staging bootstrap and signed webhook proof."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

_EXACT_PLACEHOLDER_VALUES = frozenset(
    {
        "sk_test_change_me",
        "pk_test_change_me",
        "whsec_test_change_me",
        "price_test_starter",
        "price_test_pro",
    }
)
_LOCAL_STAGING_PRICE_PRO = "price_local_staging_pro"
_LOCAL_STAGING_PRICE_STARTER = "price_local_staging_starter"
_LOCAL_STAGING_PRICE_PREFIX = "price_local_staging_"


def is_placeholder_stripe_value(value: str | None) -> bool:
    if not value or not str(value).strip():
        return True
    normalized = str(value).strip()
    if normalized.lower() in _EXACT_PLACEHOLDER_VALUES:
        return True
    return "CHANGE_ME" in normalized.upper()


def stripe_webhook_proof_ready(
    *,
    webhook_secret: str | None,
    price_pro: str | None,
) -> bool:
    """Return True when simulated webhook proof can run (no live Stripe API required)."""
    if is_placeholder_stripe_value(webhook_secret):
        return False
    if not str(webhook_secret).startswith("whsec_"):
        return False
    if is_placeholder_stripe_value(price_pro):
        return False
    return str(price_pro).startswith("price_")


def is_local_staging_price_id(value: str | None) -> bool:
    return bool(value and str(value).startswith(_LOCAL_STAGING_PRICE_PREFIX))


def stripe_checkout_ready(*, secret_key: str | None, price_pro: str | None) -> bool:
    """Return True when browser checkout can call the Stripe API."""
    if is_placeholder_stripe_value(secret_key):
        return False
    if not str(secret_key).startswith("sk_test_"):
        return False
    if is_placeholder_stripe_value(price_pro):
        return False
    if is_local_staging_price_id(price_pro):
        return False
    return str(price_pro).startswith("price_")


def stripe_staging_ready(
    *,
    secret_key: str | None,
    webhook_secret: str | None,
    price_pro: str | None,
) -> bool:
    """Return True when full Stripe staging (checkout + webhook proof) is configured."""
    return stripe_checkout_ready(secret_key=secret_key, price_pro=price_pro) and stripe_webhook_proof_ready(
        webhook_secret=webhook_secret,
        price_pro=price_pro,
    )


def sign_stripe_webhook_payload(payload: bytes, *, secret: str, timestamp: int | None = None) -> str:
    """Build a Stripe-Signature header value for a raw webhook JSON payload."""
    ts = int(time.time()) if timestamp is None else timestamp
    signed_payload = f"{ts}.{payload.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def build_checkout_completed_event(
    *,
    tenant_id: str,
    customer_id: str,
    price_id: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build a checkout.session.completed payload with an expanded subscription."""
    subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{uuid.uuid4().hex[:16]}",
                "object": "checkout.session",
                "metadata": {"tenant_id": tenant_id},
                "customer": customer_id,
                "subscription": {
                    "id": subscription_id,
                    "object": "subscription",
                    "customer": customer_id,
                    "metadata": {"tenant_id": tenant_id},
                    "items": {
                        "data": [
                            {
                                "id": f"si_{uuid.uuid4().hex[:12]}",
                                "price": {"id": price_id},
                            }
                        ]
                    },
                },
            }
        },
    }


def dumps_event(event: dict[str, Any]) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode("utf-8")

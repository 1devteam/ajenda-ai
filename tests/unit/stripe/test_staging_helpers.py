"""Unit tests for scripts/stripe/staging_helpers.py."""

from __future__ import annotations

import stripe

from backend.billing.staging_proof_helpers import (
    build_checkout_completed_event,
    dumps_event,
    is_placeholder_stripe_value,
    sign_stripe_webhook_payload,
    stripe_checkout_ready,
    stripe_webhook_proof_ready,
)


def test_placeholder_detection() -> None:
    assert is_placeholder_stripe_value("sk_test_CHANGE_ME")
    assert is_placeholder_stripe_value("price_test_pro")
    assert is_placeholder_stripe_value("")
    assert not is_placeholder_stripe_value("sk_test_abc123")
    assert not is_placeholder_stripe_value("price_1NabcXYZ")


def test_stripe_proof_and_checkout_readiness() -> None:
    assert stripe_webhook_proof_ready(
        webhook_secret="whsec_local_proof",
        price_pro="price_local_staging_pro",
    )
    assert stripe_checkout_ready(secret_key="sk_test_abc", price_pro="price_123")
    assert not stripe_checkout_ready(secret_key="sk_live_abc", price_pro="price_123")


def test_signed_payload_verifies_with_stripe_sdk() -> None:
    secret = "whsec_unit_test_secret"
    event = build_checkout_completed_event(
        tenant_id="00000000-0000-0000-0000-000000000099",
        customer_id="cus_unit_test",
        price_id="price_pro_test",
        event_id="evt_unit_test",
    )
    payload = dumps_event(event)
    signature = sign_stripe_webhook_payload(payload, secret=secret)

    verified = stripe.Webhook.construct_event(payload, signature, secret, tolerance=86_400)
    assert verified["id"] == "evt_unit_test"
    assert verified["type"] == "checkout.session.completed"


def test_build_checkout_completed_event_includes_expanded_subscription() -> None:
    event = build_checkout_completed_event(
        tenant_id="tenant-a",
        customer_id="cus_a",
        price_id="price_pro_test",
    )
    session = event["data"]["object"]
    assert session["metadata"]["tenant_id"] == "tenant-a"
    subscription = session["subscription"]
    assert isinstance(subscription, dict)
    assert subscription["items"]["data"][0]["price"]["id"] == "price_pro_test"

"""Unit tests for verification delivery adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.services.verification_delivery import (
    LoggingVerificationDelivery,
    NoopVerificationDelivery,
    build_verify_url,
)


def test_build_verify_url_appends_token_query() -> None:
    url = build_verify_url(base_url="https://app.ajenda.ai/verify-email", token="abc123")
    assert url == "https://app.ajenda.ai/verify-email?token=abc123"


def test_noop_delivery_returns_receipt() -> None:
    adapter = NoopVerificationDelivery()
    receipt = adapter.send_signup_verification(
        to_email="owner@example.com",
        org_name="Acme",
        verify_url="https://app.ajenda.ai/verify-email?token=abc",
        expires_at=datetime(2026, 6, 24, tzinfo=UTC),
    )
    assert receipt.provider == "noop"
    assert receipt.provider_message_id


def test_logging_delivery_returns_receipt() -> None:
    receipt = LoggingVerificationDelivery().send_signup_verification(
        to_email="owner@example.com",
        org_name="Acme",
        verify_url="https://app.ajenda.ai/verify-email?token=abc",
        expires_at=datetime(2026, 6, 24, tzinfo=UTC),
    )
    assert receipt.provider == "logging"

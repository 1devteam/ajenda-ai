"""Unit tests for verification delivery adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.services.verification_delivery import (
    LoggingVerificationDelivery,
    NoopVerificationDelivery,
    build_verify_url,
)


def test_build_verify_url_prefills_email_without_secret_code() -> None:
    url = build_verify_url(base_url="https://app.ajenda.ai/verify-email", email="owner@example.com")
    assert url == "https://app.ajenda.ai/verify-email?email=owner%40example.com"
    assert "123456" not in url


def test_noop_delivery_returns_receipt() -> None:
    adapter = NoopVerificationDelivery()
    receipt = adapter.send_signup_verification(
        to_email="owner@example.com",
        org_name="Acme",
        verification_code="123456",
        verify_url="https://app.ajenda.ai/verify-email?email=owner%40example.com",
        expires_at=datetime(2026, 6, 24, tzinfo=UTC),
    )
    assert receipt.provider == "noop"
    assert receipt.provider_message_id


def test_logging_delivery_returns_receipt_without_requiring_magic_link_secret() -> None:
    receipt = LoggingVerificationDelivery().send_signup_verification(
        to_email="owner@example.com",
        org_name="Acme",
        verification_code="123456",
        verify_url="https://app.ajenda.ai/verify-email?email=owner%40example.com",
        expires_at=datetime(2026, 6, 24, tzinfo=UTC),
    )
    assert receipt.provider == "logging"

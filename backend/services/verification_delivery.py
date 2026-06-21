"""Verification email delivery adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlencode

import httpx

from backend.app.config import Settings

logger = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    """Raised when a verification email cannot be delivered."""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    provider: str
    provider_message_id: str


@runtime_checkable
class VerificationDeliveryPort(Protocol):
    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt: ...


class NoopVerificationDelivery:
    """Test adapter that records delivery without side effects."""

    def __init__(self) -> None:
        self.last_receipt: DeliveryReceipt | None = None

    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        receipt = DeliveryReceipt(provider="noop", provider_message_id="noop-message")
        self.last_receipt = receipt
        return receipt


class LoggingVerificationDelivery:
    """Non-production adapter that logs delivery intent with redaction."""

    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        logger.info(
            "verification_email_logged",
            extra={
                "to_email_domain": to_email.split("@", 1)[-1],
                "org_name": org_name,
                "verify_url_host": _host_from_url(verify_url),
                "expires_at": expires_at.isoformat(),
            },
        )
        return DeliveryReceipt(provider="logging", provider_message_id="logged")


class ResendVerificationDelivery:
    """Production adapter using the Resend HTTP API."""

    def __init__(
        self,
        *,
        api_key: str,
        email_from: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._email_from = email_from
        self._timeout_seconds = timeout_seconds

    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        subject = f"Verify your Ajenda AI account for {org_name}"
        html = _render_signup_verify_html(
            org_name=org_name,
            verify_url=verify_url,
            expires_at=expires_at,
        )
        payload = {
            "from": self._email_from,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post("https://api.resend.com/emails", json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeliveryError("verification email delivery failed") from exc

        body = response.json()
        message_id = str(body.get("id") or "")
        if not message_id:
            raise DeliveryError("verification email delivery returned no message id")
        return DeliveryReceipt(provider="resend", provider_message_id=message_id)


def build_verify_url(*, base_url: str, token: str) -> str:
    """Build the magic-link verification URL."""
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'token': token})}"


def verification_delivery_from_settings(settings: Settings) -> VerificationDeliveryPort:
    """Construct the configured verification delivery adapter."""
    provider: Literal["logging", "noop", "resend"] = settings.email_provider
    if provider == "resend":
        return ResendVerificationDelivery(
            api_key=settings.resend_api_key,
            email_from=settings.email_from,
            timeout_seconds=settings.email_delivery_timeout_seconds,
        )
    if provider == "noop":
        return NoopVerificationDelivery()
    return LoggingVerificationDelivery()


def _host_from_url(url: str) -> str:
    if "://" not in url:
        return url
    return url.split("://", 1)[1].split("/", 1)[0]


def _render_signup_verify_html(*, org_name: str, verify_url: str, expires_at: datetime) -> str:
    expiry_text = expires_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return (
        f"<p>Welcome to Ajenda AI for <strong>{org_name}</strong>.</p>"
        f'<p><a href="{verify_url}">Verify your email</a> to activate your account.</p>'
        f"<p>This link expires at {expiry_text}.</p>"
        "<p>If you did not request this account, you can ignore this email.</p>"
    )

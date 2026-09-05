"""Verification email delivery adapters."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlencode

from backend.app.config import Settings
from backend.services.network_egress import NetworkEgressAuthority, get_default_network_egress_authority

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
        verification_code: str,
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
        verification_code: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        del to_email, org_name, verification_code, verify_url, expires_at
        receipt = DeliveryReceipt(provider="noop", provider_message_id="noop-message")
        self.last_receipt = receipt
        return receipt


class LoggingVerificationDelivery:
    """Non-production adapter that logs delivery intent without logging the code."""

    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verification_code: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        del verification_code
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
        network_egress_authority: NetworkEgressAuthority | None = None,
    ) -> None:
        self._api_key = api_key
        self._email_from = email_from
        self._timeout_seconds = timeout_seconds
        self._network_egress_authority = network_egress_authority or get_default_network_egress_authority()

    def send_signup_verification(
        self,
        *,
        to_email: str,
        org_name: str,
        verification_code: str,
        verify_url: str,
        expires_at: datetime,
    ) -> DeliveryReceipt:
        subject = f"Your Ajenda AI verification code for {org_name}"
        html = _render_signup_verify_html(
            org_name=org_name,
            verification_code=verification_code,
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
            _, response = self._network_egress_authority.request(
                method="POST",
                url="https://api.resend.com/emails",
                json_body=payload,
                headers=headers,
                timeout_seconds=self._timeout_seconds,
                allowed_hosts=["api.resend.com"],
                action_name="verification.resend",
                response_text_limit=16_384,
            )
        except Exception as exc:
            raise DeliveryError("verification email delivery failed") from exc
        if response.status_code >= 400:
            raise DeliveryError("verification email delivery failed")
        body = json.loads(response.body_text)
        message_id = str(body.get("id") or "")
        if not message_id:
            raise DeliveryError("verification email delivery returned no message id")
        return DeliveryReceipt(provider="resend", provider_message_id=message_id)


def build_verify_url(*, base_url: str, email: str) -> str:
    """Build a verification-page URL that may prefill the public email identifier.

    The verification secret is deliberately not placed in the URL.
    """
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'email': email})}"


def verification_delivery_from_settings(settings: Settings) -> VerificationDeliveryPort:
    """Construct the configured verification delivery adapter."""
    provider: Literal["logging", "noop", "resend"] = settings.email_provider
    if provider == "resend":
        return ResendVerificationDelivery(
            api_key=settings.resend_api_key,
            email_from=settings.email_from,
            timeout_seconds=settings.email_delivery_timeout_seconds,
            network_egress_authority=get_default_network_egress_authority(),
        )
    if provider == "noop":
        return NoopVerificationDelivery()
    return LoggingVerificationDelivery()


def _host_from_url(url: str) -> str:
    if "://" not in url:
        return url
    return url.split("://", 1)[1].split("/", 1)[0]


def _render_signup_verify_html(
    *,
    org_name: str,
    verification_code: str,
    verify_url: str,
    expires_at: datetime,
) -> str:
    expiry_text = expires_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return (
        f"<p>Welcome to Ajenda AI for <strong>{org_name}</strong>.</p>"
        "<p>Enter this verification code to activate your account:</p>"
        f'<p style="font-size:28px;font-weight:700;letter-spacing:6px">{verification_code}</p>'
        f'<p><a href="{verify_url}">Open Ajenda AI verification</a></p>'
        f"<p>This code expires at {expiry_text}.</p>"
        "<p>If you did not request this account, you can ignore this email.</p>"
    )

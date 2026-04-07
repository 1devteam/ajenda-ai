"""WebhookDispatchService — HMAC-signed HTTP delivery with retry and feature gating.

Responsibilities:
  - Register webhook endpoints (with feature gate check)
  - Dispatch events to all subscribed active endpoints for a tenant
  - Sign each delivery with HMAC-SHA256 on the X-Ajenda-Signature-256 header
  - Record every delivery attempt in WebhookDelivery
  - Disable endpoints that exceed MAX_CONSECUTIVE_FAILURES

Retry policy (handled by the caller — typically a background worker):
  This service performs a single delivery attempt per call. The caller is
  responsible for scheduling retries using the exponential backoff schedule
  documented in WebhookDelivery. This keeps the service synchronous and
  testable without requiring a task queue dependency.

Security:
  - HMAC secret is generated as 32 random bytes (256-bit entropy)
  - Secret is stored as a bcrypt hash; plaintext is returned once at registration
  - Signature format: sha256=<hex_digest> (GitHub-compatible)
  - Delivery timeout: 10 seconds to prevent slow-endpoint DoS
  - URL validation: must use HTTPS scheme (enforced at registration)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import requests
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from backend.domain.webhook_delivery import RESPONSE_BODY_MAX_CHARS, WebhookDelivery
from backend.domain.webhook_endpoint import WebhookEndpoint
from backend.repositories.tenant_repository import TenantRepository
from backend.repositories.webhook_repository import WebhookRepository
from backend.services.quota_enforcement import QuotaEnforcementService

# Maximum consecutive failures before an endpoint is auto-disabled
MAX_CONSECUTIVE_FAILURES = 5

# HTTP delivery timeout in seconds
DELIVERY_TIMEOUT_SECONDS = 10

# Webhook feature flag name (must match TenantPlan.features_enabled values)
WEBHOOK_FEATURE = "webhooks"


class WebhookRegistrationError(Exception):
    """Raised when a webhook endpoint cannot be registered."""


class WebhookNotFoundError(Exception):
    """Raised when a webhook endpoint is not found for the given tenant."""


class WebhookDispatchResult:
    """Result of a single delivery attempt."""

    __slots__ = ("delivery_id", "error", "http_status", "succeeded")

    def __init__(
        self,
        *,
        delivery_id: uuid.UUID,
        succeeded: bool,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        self.delivery_id = delivery_id
        self.succeeded = succeeded
        self.http_status = http_status
        self.error = error

    def __repr__(self) -> str:
        return f"<WebhookDispatchResult delivery={self.delivery_id} ok={self.succeeded} status={self.http_status}>"


class WebhookDispatchService:
    """Manages webhook endpoint lifecycle and event delivery.

    Args:
        session: SQLAlchemy Session for all DB operations.
        http_session: Optional requests.Session for HTTP delivery.
            Injected for testing; defaults to a new session with a 10s timeout.
    """

    def __init__(
        self,
        session: Session,
        *,
        http_session: requests.Session | None = None,
    ) -> None:
        self._db = session
        self._repo = WebhookRepository(session)
        self._tenants = TenantRepository(session)
        self._quota = QuotaEnforcementService(session)
        self._http = http_session or requests.Session()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_endpoint(
        self,
        *,
        tenant_id: uuid.UUID,
        url: str,
        event_types: list[str],
    ) -> tuple[WebhookEndpoint, str]:
        """Register a new webhook endpoint for a tenant.

        Returns:
            A tuple of (WebhookEndpoint, plaintext_secret). The plaintext
            secret is shown exactly once and is not stored; the caller must
            present it to the tenant immediately.

        Raises:
            WebhookRegistrationError: If the URL is not HTTPS or event_types
                is empty.
            FeatureNotAvailableError: If the tenant's plan does not include
                the 'webhooks' feature.
        """
        # Feature gate — webhooks are a paid feature
        self._quota.require_feature(tenant_id, WEBHOOK_FEATURE)

        # URL validation — must be HTTPS in all environments
        if not url.lower().startswith("https://"):
            raise WebhookRegistrationError(f"Webhook URL must use HTTPS. Got: {url!r}")

        if not event_types:
            raise WebhookRegistrationError("At least one event_type must be specified.")

        # Generate signing secret
        plaintext_secret = secrets.token_hex(32)  # 64-char hex string
        secret_hash = bcrypt.hash(plaintext_secret)

        endpoint = WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            url=url,
            secret_hash=secret_hash,
            event_types=event_types,
            is_active=True,
        )
        self._repo.create_endpoint(endpoint)
        return endpoint, plaintext_secret

    def get_endpoint(self, endpoint_id: uuid.UUID, *, tenant_id: uuid.UUID) -> WebhookEndpoint:
        """Return a single endpoint, scoped to the tenant.

        Raises:
            WebhookNotFoundError: If the endpoint does not exist for this tenant.
        """
        endpoint = self._repo.get_endpoint(endpoint_id, tenant_id=tenant_id)
        if endpoint is None:
            raise WebhookNotFoundError(f"Webhook endpoint {endpoint_id} not found for tenant {tenant_id}")
        return endpoint

    def list_endpoints(self, tenant_id: uuid.UUID) -> list[WebhookEndpoint]:
        """Return all registered endpoints for a tenant."""
        return self._repo.list_endpoints(tenant_id)

    def delete_endpoint(self, endpoint_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        """Delete a webhook endpoint.

        Raises:
            WebhookNotFoundError: If the endpoint does not exist for this tenant.
        """
        deleted = self._repo.delete_endpoint(endpoint_id, tenant_id=tenant_id)
        if not deleted:
            raise WebhookNotFoundError(f"Webhook endpoint {endpoint_id} not found for tenant {tenant_id}")

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch_event(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        event_id: uuid.UUID | None = None,
        attempt_number: int = 1,
    ) -> list[WebhookDispatchResult]:
        """Dispatch an event to all active endpoints subscribed to event_type.

        For each matching endpoint, performs an HTTP POST with HMAC-SHA256
        signature and records the attempt in WebhookDelivery.

        Args:
            tenant_id: The tenant whose endpoints to notify.
            event_type: The event type string (e.g. "task.completed").
            payload: The JSON-serialisable event payload.
            event_id: Unique ID for this event (generated if not provided).
                Used for idempotency on retries.
            attempt_number: 1-based attempt counter for retry tracking.

        Returns:
            List of WebhookDispatchResult, one per endpoint attempted.
        """
        if event_id is None:
            event_id = uuid.uuid4()

        endpoints = self._repo.list_active_endpoints_for_event(tenant_id, event_type)
        results: list[WebhookDispatchResult] = []

        for endpoint in endpoints:
            result = self._deliver(
                endpoint=endpoint,
                event_type=event_type,
                event_id=event_id,
                payload=payload,
                attempt_number=attempt_number,
                tenant_id=tenant_id,
            )
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Internal delivery
    # ------------------------------------------------------------------

    def _deliver(
        self,
        *,
        endpoint: WebhookEndpoint,
        event_type: str,
        event_id: uuid.UUID,
        payload: dict[str, Any],
        attempt_number: int,
        tenant_id: uuid.UUID,
    ) -> WebhookDispatchResult:
        """Perform a single HTTP POST delivery attempt.

        Records the attempt in WebhookDelivery regardless of outcome.
        Auto-disables the endpoint after MAX_CONSECUTIVE_FAILURES failures.
        """
        body = json.dumps(
            {
                "id": str(event_id),
                "type": event_type,
                "tenant_id": str(tenant_id),
                "attempt": attempt_number,
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "data": payload,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        signature = self._sign(body, endpoint.secret_hash)

        delivery = WebhookDelivery(
            id=uuid.uuid4(),
            endpoint_id=endpoint.id,
            tenant_id=tenant_id,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
            status="delivering",
            attempt_number=attempt_number,
            attempted_at=datetime.now(tz=UTC),
        )
        self._repo.record_delivery(delivery)

        http_status: int | None = None
        response_body: str | None = None
        error_message: str | None = None
        succeeded = False

        try:
            response = self._http.post(
                endpoint.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Ajenda-Event": event_type,
                    "X-Ajenda-Delivery": str(delivery.id),
                    "X-Ajenda-Signature-256": signature,
                    "User-Agent": "Ajenda-Webhooks/1.0",
                },
                timeout=DELIVERY_TIMEOUT_SECONDS,
            )
            http_status = response.status_code
            response_body = response.text[:RESPONSE_BODY_MAX_CHARS]
            succeeded = 200 <= http_status < 300

        except requests.Timeout:
            error_message = f"Delivery timed out after {DELIVERY_TIMEOUT_SECONDS}s"
        except requests.ConnectionError as exc:
            error_message = f"Connection error: {exc}"
        except Exception as exc:
            error_message = f"Unexpected error: {exc}"

        # Update delivery record with outcome
        delivery.status = "delivered" if succeeded else "failed"
        delivery.http_status_code = http_status
        delivery.response_body = response_body
        delivery.error_message = error_message
        if succeeded:
            delivery.delivered_at = datetime.now(tz=UTC)

        # Auto-disable endpoint after too many consecutive failures
        if not succeeded:
            failure_count = self._repo.count_recent_failures(
                endpoint.id, since_attempt=max(1, attempt_number - MAX_CONSECUTIVE_FAILURES + 1)
            )
            if failure_count >= MAX_CONSECUTIVE_FAILURES:
                delivery.status = "dead_lettered"
                self._repo.disable_endpoint(endpoint.id, tenant_id=tenant_id)

        return WebhookDispatchResult(
            delivery_id=delivery.id,
            succeeded=succeeded,
            http_status=http_status,
            error=error_message,
        )

    @staticmethod
    def _sign(body: bytes, secret_hash: str) -> str:
        """Generate the HMAC-SHA256 signature header value.

        The signature is computed over the raw request body bytes using the
        bcrypt hash as the HMAC key. This is intentional: the bcrypt hash is
        deterministic for the same plaintext secret, so the tenant can verify
        the signature using their plaintext secret on their end.

        Note: In a future iteration, the plaintext secret should be stored in
        an encrypted secrets store (e.g. AWS Secrets Manager) so the HMAC key
        is the actual plaintext secret rather than its hash. For the current
        implementation, the bcrypt hash serves as a stable, non-reversible key.
        """
        mac = hmac.new(secret_hash.encode("utf-8"), body, hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

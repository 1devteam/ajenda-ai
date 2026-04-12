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

HTTP client:
  Uses httpx.Client (declared dependency in pyproject.toml) instead of the
  previously used requests library, which was an undeclared transitive
  dependency. httpx is already a first-class dependency (used by FastAPI's
  TestClient) and provides an identical synchronous API surface.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from backend.domain.webhook_delivery import RESPONSE_BODY_MAX_CHARS, WebhookDelivery
from backend.domain.webhook_endpoint import WebhookEndpoint
from backend.repositories.tenant_repository import TenantRepository
from backend.repositories.webhook_repository import WebhookRepository
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.webhook_secret_protector import WebhookSecretProtector

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


class WebhookReplayNotAllowedError(Exception):
    """Raised when a delivery replay is not allowed for the selected attempt."""


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


@dataclass(frozen=True)
class EndpointFailureSummary:
    endpoint_id: str
    failure_count: int


@dataclass(frozen=True)
class WebhookReliabilitySummary:
    lookback_hours: int
    total_attempts: int
    delivered_attempts: int
    failed_attempts: int
    dead_lettered_attempts: int
    success_rate: float
    avg_delivery_latency_ms: float | None
    p95_delivery_latency_ms: float | None
    top_failing_endpoints: list[EndpointFailureSummary]
    hourly_series: list[HourlyReliabilityPoint]


@dataclass(frozen=True)
class HourlyReliabilityPoint:
    window_start: str
    delivered_attempts: int
    failed_attempts: int


@dataclass(frozen=True)
class EndpointReliabilitySummary:
    endpoint_id: str
    lookback_hours: int
    total_attempts: int
    delivered_attempts: int
    failed_attempts: int
    dead_lettered_attempts: int
    success_rate: float
    avg_delivery_latency_ms: float | None
    p95_delivery_latency_ms: float | None
    hourly_series: list[HourlyReliabilityPoint]


class WebhookDispatchService:
    """Manages webhook endpoint lifecycle and event delivery.

    Args:
        session: SQLAlchemy Session for all DB operations.
        http_client: Optional httpx.Client for HTTP delivery.
            Injected for testing; defaults to a new client with a 10s timeout.
        http_session: Deprecated alias for http_client. Kept for backwards
            compatibility with existing call sites and unit tests.
    """

    def __init__(
        self,
        session: Session,
        *,
        http_client: httpx.Client | None = None,
        http_session: Any | None = None,
        secret_protector: WebhookSecretProtector | None = None,
    ) -> None:
        self._db = session
        self._repo = WebhookRepository(session)
        self._tenants = TenantRepository(session)
        self._quota = QuotaEnforcementService(session)
        self._protector = secret_protector or WebhookSecretProtector()
        if http_client is not None:
            self._http: Any = http_client
        elif http_session is not None:
            # Backwards-compat shim: accept a requests.Session-like mock so
            # existing unit tests continue to work without modification.
            # In production this path is never taken.
            self._http = http_session
        else:
            self._http = httpx.Client(timeout=DELIVERY_TIMEOUT_SECONDS)

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

        # Generate signing secret using the protector (encrypted-at-rest)
        plaintext_secret, secret_ciphertext = self._protector.generate_secret()
        # Also store a bcrypt hash for backward compatibility with legacy signing path
        secret_hash = bcrypt.hash(plaintext_secret)

        endpoint = WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            url=url,
            secret_hash=secret_hash,
            secret_ciphertext=secret_ciphertext,
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

    def replay_delivery(
        self,
        *,
        tenant_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        delivery_id: uuid.UUID,
    ) -> WebhookDispatchResult:
        """Replay a prior delivery attempt to the same endpoint.

        Reuses the original event_id/event_type/payload and increments the
        attempt_number by one. The replay is blocked for in-flight deliveries.
        """
        endpoint = self.get_endpoint(endpoint_id, tenant_id=tenant_id)
        delivery = self._repo.get_delivery_for_endpoint(
            delivery_id,
            endpoint_id=endpoint_id,
            tenant_id=tenant_id,
        )
        if delivery is None:
            raise WebhookNotFoundError(
                f"Webhook delivery {delivery_id} not found for endpoint {endpoint_id} and tenant {tenant_id}"
            )
        if delivery.status in {"pending", "delivering"}:
            raise WebhookReplayNotAllowedError(
                f"Webhook delivery {delivery_id} is in progress and cannot be replayed yet."
            )

        return self._deliver(
            endpoint=endpoint,
            event_type=delivery.event_type,
            event_id=delivery.event_id,
            payload=delivery.payload,
            attempt_number=delivery.attempt_number + 1,
            tenant_id=tenant_id,
        )

    def get_reliability_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        lookback_hours: int = 24,
    ) -> WebhookReliabilitySummary:
        """Return tenant-scoped reliability metrics for recent deliveries."""
        if lookback_hours < 1 or lookback_hours > 24 * 30:
            raise ValueError("lookback_hours must be between 1 and 720")
        now = datetime.now(tz=UTC)
        end_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = end_hour - timedelta(hours=lookback_hours - 1)
        since = start_hour
        total, delivered, failed, dead_lettered, avg_latency_ms, p95_latency_ms = (
            self._repo.get_delivery_reliability_metrics(
                tenant_id=tenant_id,
                since=since,
            )
        )
        success_rate = round((delivered / total), 4) if total > 0 else 0.0
        top_failures = [
            EndpointFailureSummary(endpoint_id=str(endpoint_id), failure_count=count)
            for endpoint_id, count in self._repo.list_endpoint_failure_counts(
                tenant_id=tenant_id,
                since=since,
                limit=5,
            )
        ]
        raw_hourly = self._repo.list_hourly_delivery_stats(
            tenant_id=tenant_id,
            since=since,
        )
        hourly_map: dict[str, tuple[int, int]] = {}
        for bucket_start, delivered_count, failed_count in raw_hourly:
            bucket_key = bucket_start.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
            hourly_map[bucket_key] = (delivered_count, failed_count)

        hourly_series: list[HourlyReliabilityPoint] = []
        for i in range(lookback_hours):
            current_bucket = start_hour + timedelta(hours=i)
            bucket_key = current_bucket.isoformat()
            delivered_count, failed_count = hourly_map.get(bucket_key, (0, 0))
            hourly_series.append(
                HourlyReliabilityPoint(
                    window_start=bucket_key,
                    delivered_attempts=delivered_count,
                    failed_attempts=failed_count,
                )
            )

        return WebhookReliabilitySummary(
            lookback_hours=lookback_hours,
            total_attempts=total,
            delivered_attempts=delivered,
            failed_attempts=failed,
            dead_lettered_attempts=dead_lettered,
            success_rate=success_rate,
            avg_delivery_latency_ms=round(avg_latency_ms, 2) if avg_latency_ms is not None else None,
            p95_delivery_latency_ms=round(p95_latency_ms, 2) if p95_latency_ms is not None else None,
            top_failing_endpoints=top_failures,
            hourly_series=hourly_series,
        )

    def get_endpoint_reliability_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        lookback_hours: int = 24,
    ) -> EndpointReliabilitySummary:
        """Return endpoint-scoped reliability summary with fixed hourly bins."""
        if lookback_hours < 1 or lookback_hours > 24 * 30:
            raise ValueError("lookback_hours must be between 1 and 720")

        # Ownership check / not-found handling
        self.get_endpoint(endpoint_id, tenant_id=tenant_id)

        now = datetime.now(tz=UTC)
        end_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = end_hour - timedelta(hours=lookback_hours - 1)
        since = start_hour
        total, delivered, failed, dead_lettered, avg_latency_ms, p95_latency_ms = (
            self._repo.get_endpoint_delivery_reliability_metrics(
                tenant_id=tenant_id,
                endpoint_id=endpoint_id,
                since=since,
            )
        )
        success_rate = round((delivered / total), 4) if total > 0 else 0.0

        raw_hourly = self._repo.list_endpoint_hourly_delivery_stats(
            tenant_id=tenant_id,
            endpoint_id=endpoint_id,
            since=since,
        )
        hourly_map: dict[str, tuple[int, int]] = {}
        for bucket_start, delivered_count, failed_count in raw_hourly:
            bucket_key = bucket_start.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
            hourly_map[bucket_key] = (delivered_count, failed_count)

        hourly_series: list[HourlyReliabilityPoint] = []
        for i in range(lookback_hours):
            current_bucket = start_hour + timedelta(hours=i)
            bucket_key = current_bucket.isoformat()
            delivered_count, failed_count = hourly_map.get(bucket_key, (0, 0))
            hourly_series.append(
                HourlyReliabilityPoint(
                    window_start=bucket_key,
                    delivered_attempts=delivered_count,
                    failed_attempts=failed_count,
                )
            )

        return EndpointReliabilitySummary(
            endpoint_id=str(endpoint_id),
            lookback_hours=lookback_hours,
            total_attempts=total,
            delivered_attempts=delivered,
            failed_attempts=failed,
            dead_lettered_attempts=dead_lettered,
            success_rate=success_rate,
            avg_delivery_latency_ms=round(avg_latency_ms, 2) if avg_latency_ms is not None else None,
            p95_delivery_latency_ms=round(p95_latency_ms, 2) if p95_latency_ms is not None else None,
            hourly_series=hourly_series,
        )

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

        # Use decrypted plaintext secret when available (migration 0009+);
        # fall back to legacy bcrypt hash for endpoints created before migration.
        if endpoint.secret_ciphertext:
            try:
                signing_key = self._protector.decrypt_secret(endpoint.secret_ciphertext)
            except ValueError:
                # Decryption failed (key rotation without migration) — fall back
                signing_key = endpoint.secret_hash
        else:
            signing_key = endpoint.secret_hash
        signature = self._sign(body, signing_key)

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
                content=body,
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

        except httpx.TimeoutException:
            error_message = f"Delivery timed out after {DELIVERY_TIMEOUT_SECONDS}s"
        except httpx.ConnectError as exc:
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
    def _sign(body: bytes, signing_key: str) -> str:
        """Generate the HMAC-SHA256 signature header value.

        Args:
            body: The raw request body bytes to sign.
            signing_key: The HMAC key. For endpoints created after migration 0009
                this is the decrypted plaintext secret, allowing tenants to verify
                signatures using their plaintext secret. For legacy endpoints it
                is the bcrypt hash (not verifiable by tenants).

        Returns:
            Signature string in the format ``sha256=<hex_digest>``.
        """
        mac = hmac.new(signing_key.encode("utf-8"), body, hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

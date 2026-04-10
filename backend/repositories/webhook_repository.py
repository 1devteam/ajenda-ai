"""WebhookRepository — data access layer for webhook endpoints and deliveries.

Responsibilities:
  - CRUD for WebhookEndpoint rows (tenant-scoped)
  - Insert and query WebhookDelivery rows
  - Fetch endpoints subscribed to a given event type for a tenant

All methods are synchronous and expect a SQLAlchemy Session injected by the
caller. The caller is responsible for commit/rollback.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from backend.domain.webhook_delivery import WebhookDelivery
from backend.domain.webhook_endpoint import WebhookEndpoint


class WebhookRepository:
    """Data access layer for webhook endpoints and delivery records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # WebhookEndpoint — CRUD
    # ------------------------------------------------------------------

    def create_endpoint(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        """Persist a new WebhookEndpoint. Caller must flush/commit."""
        self._session.add(endpoint)
        self._session.flush()
        return endpoint

    def get_endpoint(self, endpoint_id: uuid.UUID, *, tenant_id: uuid.UUID) -> WebhookEndpoint | None:
        """Return a single endpoint, scoped to the given tenant."""
        return self._session.query(WebhookEndpoint).filter_by(id=endpoint_id, tenant_id=tenant_id).first()

    def list_endpoints(self, tenant_id: uuid.UUID) -> list[WebhookEndpoint]:
        """Return all endpoints for a tenant, ordered by creation time."""
        return (
            self._session.query(WebhookEndpoint)
            .filter_by(tenant_id=tenant_id)
            .order_by(WebhookEndpoint.created_at)
            .all()
        )

    def list_active_endpoints_for_event(self, tenant_id: uuid.UUID, event_type: str) -> list[WebhookEndpoint]:
        """Return all active endpoints subscribed to the given event type.

        Uses PostgreSQL ARRAY containment operator (@>) for efficient filtering.
        """
        from sqlalchemy import String, cast
        from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

        stmt = select(WebhookEndpoint).where(
            and_(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.is_active.is_(True),
                WebhookEndpoint.event_types.contains(cast([event_type], PG_ARRAY(String))),
            )
        )
        return list(self._session.execute(stmt).scalars().all())

    def disable_endpoint(self, endpoint_id: uuid.UUID, *, tenant_id: uuid.UUID) -> bool:
        """Set is_active=False on the endpoint. Returns True if a row was updated."""
        cursor: CursorResult[tuple[()]] = self._session.execute(  # type: ignore[assignment]
            update(WebhookEndpoint)
            .where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.tenant_id == tenant_id,
            )
            .values(is_active=False, updated_at=datetime.now(tz=UTC))
        )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def delete_endpoint(self, endpoint_id: uuid.UUID, *, tenant_id: uuid.UUID) -> bool:
        """Hard-delete an endpoint. Returns True if a row was deleted."""
        endpoint = self.get_endpoint(endpoint_id, tenant_id=tenant_id)
        if endpoint is None:
            return False
        self._session.delete(endpoint)
        self._session.flush()
        return True

    def count_endpoints(self, tenant_id: uuid.UUID) -> int:
        """Return the total number of registered endpoints for a tenant."""
        return self._session.query(WebhookEndpoint).filter_by(tenant_id=tenant_id).count()

    # ------------------------------------------------------------------
    # WebhookDelivery — insert and query
    # ------------------------------------------------------------------

    def record_delivery(self, delivery: WebhookDelivery) -> WebhookDelivery:
        """Persist a delivery attempt record. Caller must flush/commit."""
        self._session.add(delivery)
        self._session.flush()
        return delivery

    def get_delivery(self, delivery_id: uuid.UUID) -> WebhookDelivery | None:
        """Return a single delivery record by ID."""
        return self._session.get(WebhookDelivery, delivery_id)

    def get_delivery_for_endpoint(
        self,
        delivery_id: uuid.UUID,
        *,
        endpoint_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> WebhookDelivery | None:
        """Return a delivery record scoped to endpoint and tenant."""
        return (
            self._session.query(WebhookDelivery)
            .filter_by(id=delivery_id, endpoint_id=endpoint_id, tenant_id=tenant_id)
            .first()
        )

    def list_deliveries_for_endpoint(
        self,
        endpoint_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        limit: int = 50,
    ) -> list[WebhookDelivery]:
        """Return recent delivery attempts for an endpoint, newest first."""
        return (
            self._session.query(WebhookDelivery)
            .filter_by(endpoint_id=endpoint_id, tenant_id=tenant_id)
            .order_by(WebhookDelivery.attempted_at.desc())
            .limit(limit)
            .all()
        )

    def count_recent_failures(
        self,
        endpoint_id: uuid.UUID,
        *,
        since_attempt: int = 1,
    ) -> int:
        """Return the number of failed delivery attempts for an endpoint
        at or after the given attempt number.

        Used by WebhookDispatchService to decide when to disable an endpoint
        after repeated failures.
        """
        return (
            self._session.query(WebhookDelivery)
            .filter(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.status == "failed",
                WebhookDelivery.attempt_number >= since_attempt,
            )
            .count()
        )

    def get_delivery_reliability_metrics(
        self,
        *,
        tenant_id: uuid.UUID,
        since: datetime,
    ) -> tuple[int, int, int, int, float | None]:
        """Return aggregate delivery reliability metrics since a timestamp."""
        delivered_count = func.sum(case((WebhookDelivery.status == "delivered", 1), else_=0))
        failed_count = func.sum(case((WebhookDelivery.status == "failed", 1), else_=0))
        dead_lettered_count = func.sum(case((WebhookDelivery.status == "dead_lettered", 1), else_=0))
        avg_latency_ms = func.avg(
            case(
                (
                    WebhookDelivery.delivered_at.is_not(None),
                    func.extract("epoch", WebhookDelivery.delivered_at - WebhookDelivery.attempted_at) * 1000.0,
                ),
                else_=None,
            )
        )

        row = (
            self._session.query(
                func.count(WebhookDelivery.id),
                delivered_count,
                failed_count,
                dead_lettered_count,
                avg_latency_ms,
            )
            .filter(
                WebhookDelivery.tenant_id == tenant_id,
                WebhookDelivery.attempted_at >= since,
            )
            .one()
        )
        total = int(row[0] or 0)
        delivered = int(row[1] or 0)
        failed = int(row[2] or 0)
        dead_lettered = int(row[3] or 0)
        avg_ms = float(row[4]) if row[4] is not None else None
        return total, delivered, failed, dead_lettered, avg_ms

    def list_endpoint_failure_counts(
        self,
        *,
        tenant_id: uuid.UUID,
        since: datetime,
        limit: int = 5,
    ) -> list[tuple[uuid.UUID, int]]:
        """Return endpoints ordered by failure count since timestamp."""
        rows = (
            self._session.query(
                WebhookDelivery.endpoint_id,
                func.count(WebhookDelivery.id).label("failure_count"),
            )
            .filter(
                WebhookDelivery.tenant_id == tenant_id,
                WebhookDelivery.attempted_at >= since,
                WebhookDelivery.status.in_(("failed", "dead_lettered")),
            )
            .group_by(WebhookDelivery.endpoint_id)
            .order_by(func.count(WebhookDelivery.id).desc())
            .limit(limit)
            .all()
        )
        return [(row[0], int(row[1])) for row in rows]

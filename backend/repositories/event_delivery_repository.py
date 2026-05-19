from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery


class EventDeliveryNotFoundError(ValueError):
    """Raised when an event delivery record does not exist for a tenant."""


class EventDeliveryStateError(ValueError):
    """Raised when an event delivery state transition is invalid."""


class EventDeliveryRepository:
    """Data access and state transitions for durable event deliveries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        tenant_id: str,
        event_type: str,
        destination_url: str,
        payload: dict[str, Any],
        idempotency_key: str,
        headers: dict[str, str] | None = None,
        mission_id: uuid.UUID | None = None,
        max_attempts: int = 3,
    ) -> EventDelivery:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        delivery = EventDelivery(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type=event_type,
            destination_url=destination_url,
            payload_json=payload,
            headers_json=headers or {},
            idempotency_key=idempotency_key,
            mission_id=mission_id,
            attempts=0,
            max_attempts=max_attempts,
            status=EventDeliveryState.PENDING.value,
        )
        self._session.add(delivery)
        return delivery

    def get_for_tenant(self, *, tenant_id: str, delivery_id: uuid.UUID) -> EventDelivery:
        delivery = self._session.get(EventDelivery, delivery_id)
        if delivery is None or delivery.tenant_id != tenant_id:
            raise EventDeliveryNotFoundError("event delivery not found for tenant")
        return delivery

    def get_due(self, *, limit: int = 100) -> list[EventDelivery]:
        now = datetime.now(UTC)
        stmt = (
            select(EventDelivery)
            .where(
                EventDelivery.status.in_(
                    [EventDeliveryState.PENDING.value, EventDeliveryState.RETRYING.value]
                ),
                (
                    EventDelivery.next_attempt_at.is_(None)
                    | (EventDelivery.next_attempt_at <= now)
                ),
            )
            .order_by(EventDelivery.created_at.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def mark_delivering(self, delivery: EventDelivery) -> None:
        if not delivery.can_attempt():
            raise EventDeliveryStateError(f"delivery is not attemptable: {delivery.status}")
        delivery.status = EventDeliveryState.DELIVERING.value
        delivery.attempts += 1
        delivery.updated_at = datetime.now(UTC)

    def mark_delivered(self, delivery: EventDelivery) -> None:
        if delivery.status != EventDeliveryState.DELIVERING.value:
            raise EventDeliveryStateError(f"delivery is not delivering: {delivery.status}")
        now = datetime.now(UTC)
        delivery.status = EventDeliveryState.DELIVERED.value
        delivery.delivered_at = now
        delivery.last_error = None
        delivery.updated_at = now

    def mark_failed_attempt(
        self,
        delivery: EventDelivery,
        *,
        error: str,
        retry_delay_seconds: int = 60,
    ) -> None:
        if delivery.status != EventDeliveryState.DELIVERING.value:
            raise EventDeliveryStateError(f"delivery is not delivering: {delivery.status}")
        now = datetime.now(UTC)
        delivery.last_error = error
        delivery.updated_at = now
        if delivery.attempts >= delivery.max_attempts:
            delivery.status = EventDeliveryState.DEAD_LETTERED.value
            delivery.dead_lettered_at = now
            delivery.next_attempt_at = None
            return

        delivery.status = EventDeliveryState.RETRYING.value
        delivery.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)

    def cancel(self, delivery: EventDelivery, *, reason: str) -> None:
        if delivery.is_terminal():
            raise EventDeliveryStateError(f"delivery is already terminal: {delivery.status}")
        now = datetime.now(UTC)
        delivery.status = EventDeliveryState.CANCELLED.value
        delivery.last_error = reason
        delivery.updated_at = now

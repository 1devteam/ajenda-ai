from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.event_delivery import EventDelivery
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.event_delivery_repository import EventDeliveryRepository


@dataclass(frozen=True, slots=True)
class EventDeliveryRequest:
    tenant_id: str
    event_type: str
    destination_url: str
    payload: dict[str, Any]
    idempotency_key: str
    headers: dict[str, str] | None = None
    mission_id: uuid.UUID | None = None
    max_attempts: int = 3


class EventDeliveryService:
    """Creates durable event delivery records and audit evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._deliveries = EventDeliveryRepository(session)
        self._audit = AuditEventRepository(session)

    def enqueue(self, request: EventDeliveryRequest) -> EventDelivery:
        delivery = self._deliveries.create(
            tenant_id=request.tenant_id,
            event_type=request.event_type,
            destination_url=request.destination_url,
            payload=request.payload,
            headers=request.headers,
            idempotency_key=request.idempotency_key,
            mission_id=request.mission_id,
            max_attempts=request.max_attempts,
        )
        self._audit.append(
            AuditEvent(
                tenant_id=request.tenant_id,
                mission_id=request.mission_id,
                category="events",
                action="enqueue_event_delivery",
                actor="event_delivery_service",
                details=f"Queued event delivery {delivery.id} for {request.event_type}",
                payload_json={
                    "delivery_id": str(delivery.id),
                    "event_type": request.event_type,
                    "destination_url": request.destination_url,
                    "idempotency_key": request.idempotency_key,
                },
            )
        )
        self._session.flush()
        return delivery

    def cancel(self, *, tenant_id: str, delivery_id: uuid.UUID, reason: str) -> EventDelivery:
        delivery = self._deliveries.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        self._deliveries.cancel(delivery, reason=reason)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=delivery.mission_id,
                category="events",
                action="cancel_event_delivery",
                actor="event_delivery_service",
                details=f"Cancelled event delivery {delivery.id}: {reason}",
                payload_json={"delivery_id": str(delivery.id), "reason": reason},
            )
        )
        self._session.flush()
        return delivery

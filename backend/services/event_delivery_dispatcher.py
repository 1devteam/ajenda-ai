from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from backend.domain.event_delivery import EventDelivery
from backend.repositories.event_delivery_repository import EventDeliveryRepository


@dataclass(frozen=True, slots=True)
class EventDeliveryTransportResult:
    """Result returned by an event delivery transport implementation."""

    succeeded: bool
    error: str | None = None

    @classmethod
    def success(cls) -> EventDeliveryTransportResult:
        return cls(succeeded=True)

    @classmethod
    def failure(cls, error: str) -> EventDeliveryTransportResult:
        return cls(succeeded=False, error=error)


class EventDeliveryTransport(Protocol):
    """Transport boundary for delivering an event.

    Implementations may use HTTP, queues, or another transport later. The dispatcher
    only depends on this protocol and never performs network I/O directly.
    """

    def deliver(self, delivery: EventDelivery) -> EventDeliveryTransportResult:
        """Deliver a single event delivery record."""


@dataclass(frozen=True, slots=True)
class EventDeliveryDispatchResult:
    attempted: int
    delivered: int
    retrying: int
    dead_lettered: int


class EventDeliveryDispatcher:
    """Coordinates due event delivery attempts through an injected transport."""

    def __init__(
        self,
        session: Session,
        transport: EventDeliveryTransport,
        *,
        retry_delay_seconds: int = 60,
    ) -> None:
        self._session = session
        self._repository = EventDeliveryRepository(session)
        self._transport = transport
        self._retry_delay_seconds = retry_delay_seconds

    def dispatch_due(self, *, limit: int = 100) -> EventDeliveryDispatchResult:
        attempted = 0
        delivered = 0
        retrying = 0
        dead_lettered = 0

        for delivery in self._repository.get_due(limit=limit):
            if delivery.is_terminal() or not delivery.can_attempt():
                continue

            attempted += 1
            self._repository.mark_delivering(delivery)
            result = self._transport.deliver(delivery)

            if result.succeeded:
                self._repository.mark_delivered(delivery)
                delivered += 1
                continue

            self._repository.mark_failed_attempt(
                delivery,
                error=result.error or "delivery failed",
                retry_delay_seconds=self._retry_delay_seconds,
            )
            if delivery.dead_lettered_at is not None:
                dead_lettered += 1
            else:
                retrying += 1

        self._session.flush()
        return EventDeliveryDispatchResult(
            attempted=attempted,
            delivered=delivered,
            retrying=retrying,
            dead_lettered=dead_lettered,
        )

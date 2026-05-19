from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.services.event_delivery_dispatcher import (
    EventDeliveryDispatchResult,
    EventDeliveryDispatcher,
    EventDeliveryTransport,
)
from backend.services.event_delivery_http_transport import HttpEventDeliveryTransport


@dataclass(frozen=True, slots=True)
class EventDeliveryWorkerConfig:
    batch_limit: int = 100
    retry_delay_seconds: int = 60


class EventDeliveryWorker:
    """Callable event delivery worker entrypoint.

    This class connects a database session and an event delivery transport to the
    dispatcher for one explicit unit of work. It does not own scheduling,
    background loops, endpoint registration, signing, or route wiring.
    """

    def __init__(
        self,
        session: Session,
        transport: EventDeliveryTransport | None = None,
        *,
        config: EventDeliveryWorkerConfig | None = None,
    ) -> None:
        self._session = session
        self._transport = transport or HttpEventDeliveryTransport()
        self._config = config or EventDeliveryWorkerConfig()

    def run_once(self, *, limit: int | None = None) -> EventDeliveryDispatchResult:
        """Dispatch one bounded batch of due event deliveries."""

        batch_limit = limit if limit is not None else self._config.batch_limit
        if batch_limit < 1:
            raise ValueError("limit must be >= 1")

        dispatcher = EventDeliveryDispatcher(
            self._session,
            self._transport,
            retry_delay_seconds=self._config.retry_delay_seconds,
        )
        return dispatcher.dispatch_due(limit=batch_limit)

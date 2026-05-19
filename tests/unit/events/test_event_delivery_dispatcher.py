from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery
from backend.services.event_delivery_dispatcher import (
    EventDeliveryDispatcher,
    EventDeliveryTransportResult,
)


def _delivery(
    status: EventDeliveryState,
    *,
    attempts: int = 0,
    max_attempts: int = 3,
) -> EventDelivery:
    return EventDelivery(
        tenant_id="tenant-a",
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        status=status.value,
        payload_json={"mission_id": "mission-1"},
        headers_json={},
        idempotency_key="tenant-a:mission.completed:mission-1",
        attempts=attempts,
        max_attempts=max_attempts,
    )


def _dispatcher(
    *,
    deliveries: list[EventDelivery],
    transport_result: EventDeliveryTransportResult | None = None,
    transport_error: Exception | None = None,
) -> tuple[EventDeliveryDispatcher, MagicMock, MagicMock, MagicMock]:
    session = MagicMock()
    repository = MagicMock()
    repository.get_due.return_value = deliveries
    transport = MagicMock()
    if transport_error is not None:
        transport.deliver.side_effect = transport_error
    else:
        transport.deliver.return_value = transport_result

    def mark_delivering(delivery: EventDelivery) -> None:
        delivery.status = EventDeliveryState.DELIVERING.value
        delivery.attempts += 1

    def mark_delivered(delivery: EventDelivery) -> None:
        delivery.status = EventDeliveryState.DELIVERED.value

    def mark_failed_attempt(
        delivery: EventDelivery,
        *,
        error: str,
        retry_delay_seconds: int,
    ) -> None:
        delivery.last_error = error
        if delivery.attempts >= delivery.max_attempts:
            delivery.status = EventDeliveryState.DEAD_LETTERED.value
            delivery.dead_lettered_at = object()
            return
        delivery.status = EventDeliveryState.RETRYING.value

    repository.mark_delivering.side_effect = mark_delivering
    repository.mark_delivered.side_effect = mark_delivered
    repository.mark_failed_attempt.side_effect = mark_failed_attempt

    with patch(
        "backend.services.event_delivery_dispatcher.EventDeliveryRepository",
        return_value=repository,
    ):
        dispatcher = EventDeliveryDispatcher(
            session,
            transport,
            retry_delay_seconds=30,
        )

    return dispatcher, repository, transport, session


def test_dispatch_due_marks_successful_delivery_delivered() -> None:
    delivery = _delivery(EventDeliveryState.PENDING)
    dispatcher, repository, transport, _session = _dispatcher(
        deliveries=[delivery],
        transport_result=EventDeliveryTransportResult.success(),
    )

    result = dispatcher.dispatch_due(limit=10)

    repository.get_due.assert_called_once_with(limit=10)
    repository.mark_delivering.assert_called_once_with(delivery)
    transport.deliver.assert_called_once_with(delivery)
    repository.mark_delivered.assert_called_once_with(delivery)
    assert delivery.status == EventDeliveryState.DELIVERED.value
    assert result.attempted == 1
    assert result.delivered == 1
    assert result.retrying == 0
    assert result.dead_lettered == 0


def test_dispatch_due_marks_failed_delivery_retrying() -> None:
    delivery = _delivery(EventDeliveryState.PENDING, max_attempts=3)
    dispatcher, repository, _transport, _session = _dispatcher(
        deliveries=[delivery],
        transport_result=EventDeliveryTransportResult.failure("timeout"),
    )

    result = dispatcher.dispatch_due()

    repository.mark_failed_attempt.assert_called_once_with(
        delivery,
        error="timeout",
        retry_delay_seconds=30,
    )
    assert delivery.status == EventDeliveryState.RETRYING.value
    assert delivery.last_error == "timeout"
    assert result.attempted == 1
    assert result.delivered == 0
    assert result.retrying == 1
    assert result.dead_lettered == 0


def test_dispatch_due_converts_transport_exception_to_failed_attempt() -> None:
    delivery = _delivery(EventDeliveryState.PENDING, max_attempts=3)
    dispatcher, repository, transport, _session = _dispatcher(
        deliveries=[delivery],
        transport_error=TimeoutError("socket timeout"),
    )

    result = dispatcher.dispatch_due()

    transport.deliver.assert_called_once_with(delivery)
    repository.mark_failed_attempt.assert_called_once_with(
        delivery,
        error="socket timeout",
        retry_delay_seconds=30,
    )
    assert delivery.status == EventDeliveryState.RETRYING.value
    assert delivery.last_error == "socket timeout"
    assert result.attempted == 1
    assert result.delivered == 0
    assert result.retrying == 1
    assert result.dead_lettered == 0


def test_dispatch_due_marks_failed_delivery_dead_lettered_after_max_attempts() -> None:
    delivery = _delivery(EventDeliveryState.PENDING, attempts=2, max_attempts=3)
    dispatcher, _repository, _transport, _session = _dispatcher(
        deliveries=[delivery],
        transport_result=EventDeliveryTransportResult.failure("timeout"),
    )

    result = dispatcher.dispatch_due()

    assert delivery.status == EventDeliveryState.DEAD_LETTERED.value
    assert delivery.last_error == "timeout"
    assert delivery.dead_lettered_at is not None
    assert result.attempted == 1
    assert result.delivered == 0
    assert result.retrying == 0
    assert result.dead_lettered == 1


def test_dispatch_due_skips_terminal_records() -> None:
    delivery = _delivery(EventDeliveryState.DELIVERED)
    dispatcher, repository, transport, _session = _dispatcher(
        deliveries=[delivery],
        transport_result=EventDeliveryTransportResult.success(),
    )

    result = dispatcher.dispatch_due()

    repository.mark_delivering.assert_not_called()
    transport.deliver.assert_not_called()
    assert result.attempted == 0
    assert result.delivered == 0
    assert result.retrying == 0
    assert result.dead_lettered == 0


def test_dispatch_due_flushes_claim_before_transport() -> None:
    delivery = _delivery(EventDeliveryState.PENDING)
    dispatcher, _repository, transport, session = _dispatcher(
        deliveries=[delivery],
        transport_result=EventDeliveryTransportResult.success(),
    )

    dispatcher.dispatch_due()

    assert session.flush.call_count == 2
    assert session.flush.call_args_list[0] < transport.deliver.call_args_list[0]

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery
from backend.repositories.event_delivery_repository import (
    EventDeliveryNotFoundError,
    EventDeliveryRepository,
    EventDeliveryStateError,
)
from backend.services.event_delivery import EventDeliveryRequest, EventDeliveryService


def _delivery(status: EventDeliveryState, *, attempts: int = 0, max_attempts: int = 3) -> EventDelivery:
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


def test_event_delivery_terminal_and_attemptable_helpers() -> None:
    pending = _delivery(EventDeliveryState.PENDING)
    delivered = _delivery(EventDeliveryState.DELIVERED)

    assert pending.can_attempt() is True
    assert pending.is_terminal() is False
    assert delivered.can_attempt() is False
    assert delivered.is_terminal() is True


def test_repository_create_adds_pending_delivery() -> None:
    session = MagicMock()
    repo = EventDeliveryRepository(session)

    delivery = repo.create(
        tenant_id="tenant-a",
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        payload={"mission_id": "mission-1"},
        idempotency_key="tenant-a:mission.completed:mission-1",
    )

    session.add.assert_called_once_with(delivery)
    assert delivery.status == EventDeliveryState.PENDING.value
    assert delivery.attempts == 0
    assert delivery.max_attempts == 3


def test_repository_get_for_tenant_rejects_cross_tenant_delivery() -> None:
    session = MagicMock()
    session.get.return_value = _delivery(EventDeliveryState.PENDING)
    repo = EventDeliveryRepository(session)

    with pytest.raises(EventDeliveryNotFoundError):
        repo.get_for_tenant(tenant_id="tenant-b", delivery_id=uuid.uuid4())


def test_repository_mark_delivering_requires_attemptable_state() -> None:
    repo = EventDeliveryRepository(MagicMock())
    delivery = _delivery(EventDeliveryState.DELIVERED)

    with pytest.raises(EventDeliveryStateError):
        repo.mark_delivering(delivery)


def test_repository_delivery_success_marks_terminal() -> None:
    repo = EventDeliveryRepository(MagicMock())
    delivery = _delivery(EventDeliveryState.PENDING)

    repo.mark_delivering(delivery)
    repo.mark_delivered(delivery)

    assert delivery.status == EventDeliveryState.DELIVERED.value
    assert delivery.delivered_at is not None
    assert delivery.last_error is None


def test_repository_failed_attempt_retries_until_max_attempts() -> None:
    repo = EventDeliveryRepository(MagicMock())
    delivery = _delivery(EventDeliveryState.PENDING, max_attempts=2)

    repo.mark_delivering(delivery)
    repo.mark_failed_attempt(delivery, error="timeout", retry_delay_seconds=30)

    assert delivery.status == EventDeliveryState.RETRYING.value
    assert delivery.last_error == "timeout"
    assert delivery.next_attempt_at is not None

    repo.mark_delivering(delivery)
    repo.mark_failed_attempt(delivery, error="timeout", retry_delay_seconds=30)

    assert delivery.status == EventDeliveryState.DEAD_LETTERED.value
    assert delivery.dead_lettered_at is not None
    assert delivery.next_attempt_at is None


def test_service_enqueue_creates_delivery_and_audit_event() -> None:
    session = MagicMock()
    audit_event = MagicMock()
    request = EventDeliveryRequest(
        tenant_id="tenant-a",
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        payload={"mission_id": "mission-1"},
        idempotency_key="tenant-a:mission.completed:mission-1",
    )

    with patch("backend.services.event_delivery.AuditEvent", return_value=audit_event):
        delivery = EventDeliveryService(session).enqueue(request)

    assert delivery.status == EventDeliveryState.PENDING.value
    session.add.assert_any_call(delivery)
    session.add.assert_any_call(audit_event)
    session.flush.assert_called()


def test_repository_get_due_filters_attemptable_records() -> None:
    session = MagicMock()
    repo = EventDeliveryRepository(session)
    due = [_delivery(EventDeliveryState.PENDING)]
    session.scalars.return_value = due

    assert repo.get_due(limit=25) == due
    session.scalars.assert_called_once()


def test_cancel_terminal_delivery_is_rejected() -> None:
    repo = EventDeliveryRepository(MagicMock())
    delivery = _delivery(EventDeliveryState.DELIVERED)

    with pytest.raises(EventDeliveryStateError):
        repo.cancel(delivery, reason="not-needed")


def test_delivery_timestamps_accept_timezone_aware_values() -> None:
    delivery = _delivery(EventDeliveryState.DELIVERING)
    now = datetime.now(UTC)

    delivery.next_attempt_at = now

    assert delivery.next_attempt_at == now

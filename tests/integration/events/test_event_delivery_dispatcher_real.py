from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery
from backend.domain.mission import Mission
from backend.repositories.event_delivery_repository import EventDeliveryRepository
from backend.services.event_delivery_dispatcher import (
    EventDeliveryDispatcher,
    EventDeliveryTransportResult,
)


class RecordingTransport:
    def __init__(
        self,
        result: EventDeliveryTransportResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result or EventDeliveryTransportResult.success()
        self._error = error
        self.calls: list[uuid.UUID] = []
        self.statuses_seen: list[str] = []
        self.attempts_seen: list[int] = []

    def deliver(self, delivery: EventDelivery) -> EventDeliveryTransportResult:
        self.calls.append(delivery.id)
        self.statuses_seen.append(delivery.status)
        self.attempts_seen.append(delivery.attempts)
        if self._error is not None:
            raise self._error
        return self._result


@contextmanager
def _database_session() -> Iterator[Session]:
    database_url = os.getenv("AJENDA_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("AJENDA_TEST_DATABASE_URL is required for live dispatcher persistence")

    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[Mission.__table__, EventDelivery.__table__],
        checkfirst=True,
    )
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _create_delivery(
    repo: EventDeliveryRepository,
    *,
    tenant_id: str,
    idempotency_key: str,
    max_attempts: int = 3,
) -> EventDelivery:
    return repo.create(
        tenant_id=tenant_id,
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        payload={"mission_id": "mission-1"},
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
    )


def _cleanup(session: Session, delivery_ids: list[uuid.UUID]) -> None:
    if delivery_ids:
        session.execute(delete(EventDelivery).where(EventDelivery.id.in_(delivery_ids)))
        session.commit()


def _tenant_id() -> str:
    return f"tenant-{uuid.uuid4()}"


def _idempotency_key() -> str:
    return f"proof-{uuid.uuid4()}"


def test_dispatcher_persists_successful_delivery() -> None:
    delivery_ids: list[uuid.UUID] = []
    with _database_session() as session:
        repo = EventDeliveryRepository(session)
        tenant_id = _tenant_id()
        delivery = _create_delivery(
            repo,
            tenant_id=tenant_id,
            idempotency_key=_idempotency_key(),
        )
        delivery_ids.append(delivery.id)
        delivery_id = delivery.id
        session.commit()

        transport = RecordingTransport(EventDeliveryTransportResult.success())
        result = EventDeliveryDispatcher(session, transport).dispatch_due(limit=10)
        session.commit()

        persisted = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert result.attempted == 1
        assert result.delivered == 1
        assert result.retrying == 0
        assert result.dead_lettered == 0
        assert persisted.status == EventDeliveryState.DELIVERED.value
        assert persisted.attempts == 1
        assert persisted.delivered_at is not None
        assert transport.calls == [delivery_id]
        assert transport.statuses_seen == [EventDeliveryState.DELIVERING.value]
        assert transport.attempts_seen == [1]

        _cleanup(session, delivery_ids)


def test_dispatcher_persists_transport_failure_as_retrying() -> None:
    delivery_ids: list[uuid.UUID] = []
    with _database_session() as session:
        repo = EventDeliveryRepository(session)
        tenant_id = _tenant_id()
        delivery = _create_delivery(
            repo,
            tenant_id=tenant_id,
            idempotency_key=_idempotency_key(),
        )
        delivery_ids.append(delivery.id)
        delivery_id = delivery.id
        session.commit()

        transport = RecordingTransport(EventDeliveryTransportResult.failure("timeout"))
        result = EventDeliveryDispatcher(session, transport, retry_delay_seconds=0).dispatch_due()
        session.commit()

        persisted = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert result.attempted == 1
        assert result.delivered == 0
        assert result.retrying == 1
        assert result.dead_lettered == 0
        assert persisted.status == EventDeliveryState.RETRYING.value
        assert persisted.attempts == 1
        assert persisted.last_error == "timeout"
        assert persisted.next_attempt_at is not None
        assert transport.calls == [delivery_id]

        _cleanup(session, delivery_ids)


def test_dispatcher_persists_transport_exception_as_retrying() -> None:
    delivery_ids: list[uuid.UUID] = []
    with _database_session() as session:
        repo = EventDeliveryRepository(session)
        tenant_id = _tenant_id()
        delivery = _create_delivery(
            repo,
            tenant_id=tenant_id,
            idempotency_key=_idempotency_key(),
        )
        delivery_ids.append(delivery.id)
        delivery_id = delivery.id
        session.commit()

        transport = RecordingTransport(error=TimeoutError("socket timeout"))
        result = EventDeliveryDispatcher(session, transport, retry_delay_seconds=0).dispatch_due()
        session.commit()

        persisted = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert result.attempted == 1
        assert result.delivered == 0
        assert result.retrying == 1
        assert result.dead_lettered == 0
        assert persisted.status == EventDeliveryState.RETRYING.value
        assert persisted.attempts == 1
        assert persisted.last_error == "socket timeout"
        assert persisted.next_attempt_at is not None
        assert transport.calls == [delivery_id]

        _cleanup(session, delivery_ids)


def test_dispatcher_persists_max_attempt_failure_as_dead_lettered() -> None:
    delivery_ids: list[uuid.UUID] = []
    with _database_session() as session:
        repo = EventDeliveryRepository(session)
        tenant_id = _tenant_id()
        delivery = _create_delivery(
            repo,
            tenant_id=tenant_id,
            idempotency_key=_idempotency_key(),
            max_attempts=3,
        )
        delivery.attempts = 2
        delivery_ids.append(delivery.id)
        delivery_id = delivery.id
        session.commit()

        transport = RecordingTransport(EventDeliveryTransportResult.failure("timeout"))
        result = EventDeliveryDispatcher(session, transport, retry_delay_seconds=0).dispatch_due()
        session.commit()

        persisted = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert result.attempted == 1
        assert result.delivered == 0
        assert result.retrying == 0
        assert result.dead_lettered == 1
        assert persisted.status == EventDeliveryState.DEAD_LETTERED.value
        assert persisted.attempts == 3
        assert persisted.last_error == "timeout"
        assert persisted.dead_lettered_at is not None
        assert persisted.next_attempt_at is None
        assert transport.calls == [delivery_id]

        _cleanup(session, delivery_ids)

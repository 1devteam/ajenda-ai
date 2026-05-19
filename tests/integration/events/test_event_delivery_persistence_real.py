from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery
from backend.domain.mission import Mission
from backend.repositories.event_delivery_repository import EventDeliveryRepository


def _database_session() -> Iterator[Session]:
    database_url = os.getenv("AJENDA_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("AJENDA_TEST_DATABASE_URL is required for live event delivery persistence")

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
) -> EventDelivery:
    return repo.create(
        tenant_id=tenant_id,
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        payload={"mission_id": "mission-1"},
        idempotency_key=idempotency_key,
    )


def _cleanup(session: Session, delivery_ids: list[uuid.UUID]) -> None:
    if delivery_ids:
        session.execute(delete(EventDelivery).where(EventDelivery.id.in_(delivery_ids)))
        session.commit()


def test_event_delivery_idempotency_is_unique_per_tenant_in_database() -> None:
    delivery_ids: list[uuid.UUID] = []
    with next(_database_session()) as session:
        repo = EventDeliveryRepository(session)
        shared_key = f"proof-{uuid.uuid4()}"
        tenant_a = f"tenant-a-{uuid.uuid4()}"
        tenant_b = f"tenant-b-{uuid.uuid4()}"

        first = _create_delivery(repo, tenant_id=tenant_a, idempotency_key=shared_key)
        second = _create_delivery(repo, tenant_id=tenant_b, idempotency_key=shared_key)
        delivery_ids.extend([first.id, second.id])
        session.commit()

        duplicate = _create_delivery(repo, tenant_id=tenant_a, idempotency_key=shared_key)
        delivery_ids.append(duplicate.id)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        _cleanup(session, delivery_ids)


def test_event_delivery_state_transitions_persist_in_database() -> None:
    delivery_ids: list[uuid.UUID] = []
    with next(_database_session()) as session:
        repo = EventDeliveryRepository(session)
        tenant_id = f"tenant-{uuid.uuid4()}"
        idempotency_key = f"proof-{uuid.uuid4()}"
        delivery = _create_delivery(repo, tenant_id=tenant_id, idempotency_key=idempotency_key)
        delivery_ids.append(delivery.id)
        delivery_id = delivery.id
        session.commit()

        persisted = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert persisted.status == EventDeliveryState.PENDING.value
        assert persisted.attempts == 0

        repo.mark_delivering(persisted)
        session.commit()

        delivering = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert delivering.status == EventDeliveryState.DELIVERING.value
        assert delivering.attempts == 1

        repo.mark_failed_attempt(delivering, error="timeout", retry_delay_seconds=0)
        session.commit()

        retrying = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert retrying.status == EventDeliveryState.RETRYING.value
        assert retrying.next_attempt_at is not None
        assert retrying.last_error == "timeout"

        repo.mark_delivering(retrying)
        repo.mark_delivered(retrying)
        session.commit()

        delivered = repo.get_for_tenant(tenant_id=tenant_id, delivery_id=delivery_id)
        assert delivered.status == EventDeliveryState.DELIVERED.value
        assert delivered.attempts == 2
        assert delivered.delivered_at is not None

        _cleanup(session, delivery_ids)

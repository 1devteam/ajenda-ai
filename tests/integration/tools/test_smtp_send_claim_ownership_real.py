from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.email_send_idempotency import EmailSendIdempotencyReceipt
from backend.repositories.email_send_idempotency_repository import EmailSendIdempotencyRepository


def _factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def test_real_postgres_serializes_smtp_claim_and_fenced_outcomes(pg_engine) -> None:
    factory = _factory(pg_engine)
    tenant_id = "tenant-smtp-owner-proof"
    action = "gtm.email_send"
    key = "smtp-owner-proof"
    barrier = Barrier(2)

    def contender(owner: str) -> tuple[str, str]:
        session = factory()
        try:
            barrier.wait(timeout=5)
            status, _ = EmailSendIdempotencyRepository(session).try_claim_smtp(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token=owner,
                lease_seconds=60,
            )
            session.commit()
            return owner, status
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(contender, ("owner-a", "owner-b")))

    winners = [owner for owner, status in outcomes if status == "newly_claimed"]
    blocked = [owner for owner, status in outcomes if status == "in_flight"]
    assert len(winners) == 1
    assert len(blocked) == 1
    winner = winners[0]
    foreign = blocked[0]

    session = factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        assert (
            repo.fence_smtp_send(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token=foreign,
            )
            is False
        )
        assert (
            repo.fence_smtp_send(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token=winner,
            )
            is True
        )
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        assert (
            repo.complete_smtp_owned(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token=foreign,
                result_payload={"status": "sent"},
            )
            is False
        )
        assert (
            repo.release_smtp_owned(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token=winner,
                error_detail="ambiguous transport outcome",
            )
            is True
        )
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        status, _ = repo.try_claim_smtp(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
            owner_token="owner-c",
            lease_seconds=60,
        )
        assert status == "in_flight"
        row = session.scalars(
            select(EmailSendIdempotencyReceipt).where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == key,
            )
        ).one()
        assert row.status == "uncertain"
        session.rollback()
    finally:
        session.close()


def test_real_postgres_recovers_only_expired_pre_send_claim(pg_engine) -> None:
    factory = _factory(pg_engine)
    tenant_id = "tenant-smtp-recovery-proof"
    action = "gtm.email_send"
    key = "smtp-recovery-proof"

    session = factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        status, _ = repo.try_claim_smtp(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
            owner_token="owner-old",
            lease_seconds=60,
        )
        assert status == "newly_claimed"
        row = session.scalars(
            select(EmailSendIdempotencyReceipt).where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == key,
            )
        ).one()
        row.result_payload = {
            "claim_owner": "owner-old",
            "claim_expires_at": (datetime.now(tz=UTC) - timedelta(seconds=1)).isoformat(),
        }
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        status, _ = repo.try_claim_smtp(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
            owner_token="owner-new",
            lease_seconds=60,
        )
        assert status == "newly_claimed"
        assert (
            repo.fence_smtp_send(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token="owner-old",
            )
            is False
        )
        assert (
            repo.fence_smtp_send(
                tenant_id=tenant_id,
                action=action,
                idempotency_key=key,
                owner_token="owner-new",
            )
            is True
        )
        session.commit()
    finally:
        session.close()

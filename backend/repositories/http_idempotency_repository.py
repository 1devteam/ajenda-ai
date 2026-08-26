"""Atomic PostgreSQL repository for HTTP idempotency ownership receipts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.domain.http_idempotency import (
    HTTP_IDEMPOTENCY_STATUS_CLAIMING,
    HTTP_IDEMPOTENCY_STATUS_COMPLETED,
    HttpIdempotencyReceipt,
)

ClaimStatus = Literal["acquired", "replay", "in_flight", "payload_mismatch"]


@dataclass(frozen=True)
class RepositoryClaimDecision:
    status: ClaimStatus
    owner_token: str | None = None
    response_ciphertext: str | None = None


class HttpIdempotencyRepository:
    """Owns row-level compare-and-set transitions for HTTP idempotency."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(
        self,
        *,
        operation_key: str,
        request_fingerprint: str,
        owner_token: str,
        now: datetime,
        claim_ttl_seconds: int,
        receipt_ttl_seconds: int,
    ) -> RepositoryClaimDecision:
        claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
        expires_at = now + timedelta(seconds=receipt_ttl_seconds)
        self._session.execute(delete(HttpIdempotencyReceipt).where(HttpIdempotencyReceipt.expires_at <= now))
        receipt_id = f"hir-{uuid.uuid4()}"
        stmt = (
            insert(HttpIdempotencyReceipt)
            .values(
                id=receipt_id,
                operation_key=operation_key,
                request_fingerprint=request_fingerprint,
                owner_token=owner_token,
                status=HTTP_IDEMPOTENCY_STATUS_CLAIMING,
                claim_expires_at=claim_expires_at,
                response_ciphertext=None,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["operation_key"])
            .returning(HttpIdempotencyReceipt.id)
        )
        inserted = self._session.execute(stmt).scalar_one_or_none()
        if inserted is not None:
            self._session.flush()
            return RepositoryClaimDecision(status="acquired", owner_token=owner_token)

        row = self._session.scalars(
            select(HttpIdempotencyReceipt)
            .where(HttpIdempotencyReceipt.operation_key == operation_key)
            .with_for_update()
        ).first()
        if row is None:
            return RepositoryClaimDecision(status="in_flight")

        if row.expires_at <= now:
            row.request_fingerprint = request_fingerprint
            row.owner_token = owner_token
            row.status = HTTP_IDEMPOTENCY_STATUS_CLAIMING
            row.claim_expires_at = claim_expires_at
            row.response_ciphertext = None
            row.expires_at = expires_at
            row.updated_at = now
            self._session.flush()
            return RepositoryClaimDecision(status="acquired", owner_token=owner_token)

        if row.request_fingerprint != request_fingerprint:
            return RepositoryClaimDecision(status="payload_mismatch")

        if row.status == HTTP_IDEMPOTENCY_STATUS_COMPLETED and row.response_ciphertext:
            return RepositoryClaimDecision(status="replay", response_ciphertext=row.response_ciphertext)

        if (
            row.status == HTTP_IDEMPOTENCY_STATUS_CLAIMING
            and row.claim_expires_at is not None
            and row.claim_expires_at <= now
        ):
            row.owner_token = owner_token
            row.claim_expires_at = claim_expires_at
            row.expires_at = expires_at
            row.updated_at = now
            self._session.flush()
            return RepositoryClaimDecision(status="acquired", owner_token=owner_token)

        return RepositoryClaimDecision(status="in_flight")

    def renew(
        self,
        *,
        operation_key: str,
        owner_token: str,
        now: datetime,
        claim_ttl_seconds: int,
    ) -> bool:
        result = self._session.execute(
            update(HttpIdempotencyReceipt)
            .where(
                HttpIdempotencyReceipt.operation_key == operation_key,
                HttpIdempotencyReceipt.owner_token == owner_token,
                HttpIdempotencyReceipt.status == HTTP_IDEMPOTENCY_STATUS_CLAIMING,
            )
            .values(
                claim_expires_at=now + timedelta(seconds=claim_ttl_seconds),
                updated_at=now,
            )
        )
        return bool(getattr(result, "rowcount", 0) == 1)

    def complete(
        self,
        *,
        operation_key: str,
        owner_token: str,
        response_ciphertext: str,
        now: datetime,
        receipt_ttl_seconds: int,
    ) -> bool:
        result = self._session.execute(
            update(HttpIdempotencyReceipt)
            .where(
                HttpIdempotencyReceipt.operation_key == operation_key,
                HttpIdempotencyReceipt.owner_token == owner_token,
                HttpIdempotencyReceipt.status == HTTP_IDEMPOTENCY_STATUS_CLAIMING,
            )
            .values(
                status=HTTP_IDEMPOTENCY_STATUS_COMPLETED,
                claim_expires_at=None,
                response_ciphertext=response_ciphertext,
                expires_at=now + timedelta(seconds=receipt_ttl_seconds),
                updated_at=now,
            )
        )
        return bool(getattr(result, "rowcount", 0) == 1)

    def release(self, *, operation_key: str, owner_token: str) -> bool:
        result = self._session.execute(
            delete(HttpIdempotencyReceipt).where(
                HttpIdempotencyReceipt.operation_key == operation_key,
                HttpIdempotencyReceipt.owner_token == owner_token,
                HttpIdempotencyReceipt.status == HTTP_IDEMPOTENCY_STATUS_CLAIMING,
            )
        )
        return bool(getattr(result, "rowcount", 0) == 1)

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(tz=UTC)

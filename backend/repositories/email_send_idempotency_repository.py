"""Repository for SMTP email-send idempotency claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.domain.email_send_idempotency import (
    EMAIL_SEND_CLAIM_STATUS_CLAIMING,
    EMAIL_SEND_CLAIM_STATUS_COMPLETED,
    EmailSendIdempotencyReceipt,
)

ClaimStatus = Literal["newly_claimed", "replayed", "in_flight"]


class EmailSendIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def try_claim(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
    ) -> tuple[ClaimStatus, dict[str, Any] | None]:
        """Atomically claim a send key or return existing outcome.

        Returns:
            newly_claimed: caller may perform the SMTP send
            replayed: prior successful send; payload is the cached outcome
            in_flight: another worker claimed and has not finalized — do not send
        """
        now = datetime.now(tz=UTC)
        receipt_id = f"esir-{uuid.uuid4()}"
        stmt = (
            insert(EmailSendIdempotencyReceipt)
            .values(
                id=receipt_id,
                tenant_id=tenant_id,
                action=action,
                idempotency_key=idempotency_key,
                status=EMAIL_SEND_CLAIM_STATUS_CLAIMING,
                result_payload=None,
                error_detail=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "action", "idempotency_key"],
            )
            .returning(EmailSendIdempotencyReceipt.id)
        )
        inserted = self._session.execute(stmt).scalar_one_or_none()
        if inserted is not None:
            self._session.flush()
            return "newly_claimed", None

        existing = self._session.scalars(
            select(EmailSendIdempotencyReceipt).where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is None:
            # Rare race: conflict without readable row; fail closed.
            return "in_flight", None
        if existing.status == EMAIL_SEND_CLAIM_STATUS_COMPLETED:
            payload = dict(existing.result_payload) if isinstance(existing.result_payload, dict) else {}
            return "replayed", payload
        return "in_flight", None

    def complete(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        result_payload: dict[str, Any],
    ) -> None:
        row = self._session.scalars(
            select(EmailSendIdempotencyReceipt).where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == idempotency_key,
            )
        ).first()
        if row is None:
            return
        row.status = EMAIL_SEND_CLAIM_STATUS_COMPLETED
        row.result_payload = dict(result_payload)
        row.error_detail = None
        row.updated_at = datetime.now(tz=UTC)
        self._session.flush()

    def release(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        error_detail: str | None = None,
    ) -> None:
        """Drop a failed claim so a later retry may re-claim (no external send succeeded)."""
        # error_detail is intentionally not persisted after delete; parameter kept for audit call sites.
        _ = error_detail
        self._session.execute(
            delete(EmailSendIdempotencyReceipt).where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == idempotency_key,
                EmailSendIdempotencyReceipt.status == EMAIL_SEND_CLAIM_STATUS_CLAIMING,
            )
        )
        self._session.flush()

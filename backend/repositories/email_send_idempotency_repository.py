"""Repository for durable email-send idempotency claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
SMTP_SEND_STATUS_SENDING = "sending"
SMTP_SEND_STATUS_UNCERTAIN = "uncertain"


class EmailSendIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _claim_metadata(*, owner_token: str, expires_at: datetime) -> dict[str, Any]:
        return {
            "claim_owner": owner_token,
            "claim_expires_at": expires_at.astimezone(UTC).isoformat(),
        }

    @staticmethod
    def _claim_owner(row: EmailSendIdempotencyReceipt) -> str | None:
        payload = row.result_payload
        if not isinstance(payload, dict):
            return None
        owner = payload.get("claim_owner")
        return owner if isinstance(owner, str) and owner else None

    @staticmethod
    def _claim_expiry(row: EmailSendIdempotencyReceipt) -> datetime | None:
        payload = row.result_payload
        if not isinstance(payload, dict):
            return None
        raw = payload.get("claim_expires_at")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _locked_row(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
    ) -> EmailSendIdempotencyReceipt | None:
        return self._session.scalars(
            select(EmailSendIdempotencyReceipt)
            .where(
                EmailSendIdempotencyReceipt.tenant_id == tenant_id,
                EmailSendIdempotencyReceipt.action == action,
                EmailSendIdempotencyReceipt.idempotency_key == idempotency_key,
            )
            .with_for_update()
        ).first()

    def try_claim(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
    ) -> tuple[ClaimStatus, dict[str, Any] | None]:
        """Legacy generic claim used by non-SMTP durable callers.

        SMTP uses :meth:`try_claim_smtp`, which adds durable ownership and a
        recoverable pre-send lease without changing the generic open-write
        semantics that also share this receipt table.
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
            return "in_flight", None
        if existing.status == EMAIL_SEND_CLAIM_STATUS_COMPLETED:
            payload = dict(existing.result_payload) if isinstance(existing.result_payload, dict) else {}
            return "replayed", payload
        return "in_flight", None

    def try_claim_smtp(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        owner_token: str,
        lease_seconds: int = 300,
    ) -> tuple[ClaimStatus, dict[str, Any] | None]:
        """Atomically acquire or recover the *pre-send* SMTP claim.

        Only ``claiming`` is recoverable. Once the owner crosses the durable
        ``sending`` fence, a later worker must fail closed because SMTP has no
        provider-side idempotency primitive and delivery may already have
        occurred.
        """
        now = datetime.now(tz=UTC)
        expiry = now + timedelta(seconds=max(1, lease_seconds))
        receipt_id = f"esir-{uuid.uuid4()}"
        stmt = (
            insert(EmailSendIdempotencyReceipt)
            .values(
                id=receipt_id,
                tenant_id=tenant_id,
                action=action,
                idempotency_key=idempotency_key,
                status=EMAIL_SEND_CLAIM_STATUS_CLAIMING,
                result_payload=self._claim_metadata(owner_token=owner_token, expires_at=expiry),
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

        existing = self._locked_row(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return "in_flight", None
        if existing.status == EMAIL_SEND_CLAIM_STATUS_COMPLETED:
            payload = dict(existing.result_payload) if isinstance(existing.result_payload, dict) else {}
            return "replayed", payload
        if existing.status != EMAIL_SEND_CLAIM_STATUS_CLAIMING:
            return "in_flight", None

        current_expiry = self._claim_expiry(existing)
        if current_expiry is None or current_expiry > now:
            return "in_flight", None

        existing.result_payload = self._claim_metadata(owner_token=owner_token, expires_at=expiry)
        existing.error_detail = None
        existing.updated_at = now
        self._session.flush()
        return "newly_claimed", None

    def fence_smtp_send(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        owner_token: str,
    ) -> bool:
        """Cross the durable no-reclaim boundary immediately before SMTP I/O."""
        row = self._locked_row(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if row is None or row.status != EMAIL_SEND_CLAIM_STATUS_CLAIMING:
            return False
        if self._claim_owner(row) != owner_token:
            return False
        row.status = SMTP_SEND_STATUS_SENDING
        row.updated_at = datetime.now(tz=UTC)
        self._session.flush()
        return True

    def complete_smtp_owned(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        owner_token: str,
        result_payload: dict[str, Any],
    ) -> bool:
        """Finalize a fenced SMTP send only for its durable owner."""
        row = self._locked_row(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if row is None or row.status != SMTP_SEND_STATUS_SENDING:
            return False
        if self._claim_owner(row) != owner_token:
            return False
        row.status = EMAIL_SEND_CLAIM_STATUS_COMPLETED
        row.result_payload = dict(result_payload)
        row.error_detail = None
        row.updated_at = datetime.now(tz=UTC)
        self._session.flush()
        return True

    def release_smtp_owned(
        self,
        *,
        tenant_id: str,
        action: str,
        idempotency_key: str,
        owner_token: str,
        error_detail: str | None = None,
    ) -> bool:
        """Release only pre-send ownership; fenced outcomes become uncertain.

        A ``sending`` receipt is never deleted. A transport exception after the
        fence is ambiguous: SMTP may have accepted the message before the
        exception surfaced, so automatic retry would risk duplicate delivery.
        """
        row = self._locked_row(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if row is None or self._claim_owner(row) != owner_token:
            return False
        if row.status == EMAIL_SEND_CLAIM_STATUS_CLAIMING:
            self._session.delete(row)
            self._session.flush()
            return True
        if row.status == SMTP_SEND_STATUS_SENDING:
            row.status = SMTP_SEND_STATUS_UNCERTAIN
            row.error_detail = error_detail
            row.updated_at = datetime.now(tz=UTC)
            self._session.flush()
            return True
        return False

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
        """Legacy generic release used by non-SMTP callers."""
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

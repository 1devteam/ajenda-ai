"""StripeWebhookEventRepository — idempotent webhook event receipts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.domain.stripe_webhook_event import StripeWebhookEvent


class StripeWebhookEventRepository:
    """Data access for Stripe webhook deduplication and outcome receipts."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def try_record_event(self, *, event_id: str, event_type: str, payload_json: dict[str, Any] | None = None) -> bool:
        """Insert a processing receipt. Returns True if new, False if duplicate."""
        stmt = (
            insert(StripeWebhookEvent)
            .values(
                event_id=event_id,
                event_type=event_type,
                outcome="processing",
                processed_at=datetime.now(tz=UTC),
                payload_json=payload_json,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
            .returning(StripeWebhookEvent.event_id)
        )
        recorded = self._session.execute(stmt).scalar_one_or_none()
        return recorded is not None

    def finalize_outcome(
        self,
        *,
        event_id: str,
        outcome: str,
        tenant_id: uuid.UUID | None = None,
        detail: str | None = None,
    ) -> None:
        """Update the receipt with the final processing outcome."""
        receipt = self._session.get(StripeWebhookEvent, event_id)
        if receipt is None:
            return
        receipt.outcome = outcome
        receipt.tenant_id = tenant_id
        receipt.detail = detail
        receipt.processed_at = datetime.now(tz=UTC)

    def list_for_tenant(self, *, tenant_id: uuid.UUID, limit: int = 100) -> list[StripeWebhookEvent]:
        """Return verified, settled invoice receipts for one tenant."""
        stmt = (
            select(StripeWebhookEvent)
            .where(
                StripeWebhookEvent.tenant_id == tenant_id,
                StripeWebhookEvent.event_type.in_(("invoice.paid", "invoice.payment_succeeded")),
                StripeWebhookEvent.outcome == "applied",
            )
            .order_by(StripeWebhookEvent.processed_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        return list(self._session.execute(stmt).scalars().all())

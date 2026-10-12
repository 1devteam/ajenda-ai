from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.billing_meter_dispatch import BillingMeterDispatch


class BillingMeterDispatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, dispatch: BillingMeterDispatch) -> BillingMeterDispatch:
        self._session.add(dispatch)
        self._session.flush()
        return dispatch

    def get_for_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        dispatch_id: uuid.UUID,
    ) -> BillingMeterDispatch | None:
        stmt = select(BillingMeterDispatch).where(
            BillingMeterDispatch.id == dispatch_id,
            BillingMeterDispatch.tenant_id == tenant_id,
        )
        return self._session.scalar(stmt)

    def list_due_pending(self, *, now: datetime, limit: int = 25) -> list[BillingMeterDispatch]:
        stmt = (
            select(BillingMeterDispatch)
            .where(
                BillingMeterDispatch.status == "pending",
                BillingMeterDispatch.next_attempt_at <= now,
            )
            .order_by(BillingMeterDispatch.next_attempt_at.asc(), BillingMeterDispatch.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(stmt))

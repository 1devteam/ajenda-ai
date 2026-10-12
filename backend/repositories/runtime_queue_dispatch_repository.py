from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.runtime_queue_dispatch import RuntimeQueueDispatch


class RuntimeQueueDispatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_task(self, *, tenant_id: str, task_id: uuid.UUID) -> RuntimeQueueDispatch | None:
        stmt = select(RuntimeQueueDispatch).where(
            RuntimeQueueDispatch.tenant_id == tenant_id,
            RuntimeQueueDispatch.task_id == task_id,
        )
        return self._session.scalar(stmt)

    def add(self, dispatch: RuntimeQueueDispatch) -> RuntimeQueueDispatch:
        self._session.add(dispatch)
        self._session.flush()
        return dispatch

    def list_due_pending(self, *, now: datetime, limit: int = 25) -> list[RuntimeQueueDispatch]:
        stmt = (
            select(RuntimeQueueDispatch)
            .where(
                RuntimeQueueDispatch.status == "pending",
                RuntimeQueueDispatch.next_attempt_at <= now,
            )
            .order_by(RuntimeQueueDispatch.next_attempt_at.asc(), RuntimeQueueDispatch.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(stmt))

    def list_cancelled_for_cleanup(self, *, now: datetime, limit: int = 25) -> list[RuntimeQueueDispatch]:
        stmt = (
            select(RuntimeQueueDispatch)
            .where(
                RuntimeQueueDispatch.status == "cancelled",
                RuntimeQueueDispatch.published_at.is_not(None),
                RuntimeQueueDispatch.cancelled_at.is_(None),
                RuntimeQueueDispatch.next_attempt_at <= now,
            )
            .order_by(RuntimeQueueDispatch.updated_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(stmt))

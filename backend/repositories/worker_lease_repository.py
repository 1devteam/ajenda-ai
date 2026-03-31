from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.worker_lease import WorkerLease


class WorkerLeaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, lease: WorkerLease) -> WorkerLease:
        self._session.add(lease)
        self._session.flush()
        self._session.refresh(lease)
        return lease

    def get(self, lease_id: uuid.UUID) -> WorkerLease | None:
        return self._session.get(WorkerLease, lease_id)

    def list_for_task(self, task_id: uuid.UUID) -> list[WorkerLease]:
        stmt = select(WorkerLease).where(WorkerLease.task_id == task_id)
        return list(self._session.scalars(stmt))

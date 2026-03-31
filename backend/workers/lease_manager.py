from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import WorkerLeaseState
from backend.domain.worker_lease import WorkerLease
from backend.runtime.transitions import transition_lease


@dataclass(frozen=True, slots=True)
class LeaseSweepResult:
    expired_ids: list[uuid.UUID]


class LeaseManager:
    def __init__(self, session: Session, expiry_seconds: int = 60) -> None:
        self._session = session
        self._expiry_seconds = expiry_seconds

    def expire_stale_leases(self) -> LeaseSweepResult:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=self._expiry_seconds)
        stmt = select(WorkerLease).where(
            WorkerLease.status == WorkerLeaseState.ACTIVE.value,
            WorkerLease.heartbeat_at.is_not(None),
            WorkerLease.heartbeat_at < threshold,
        )
        expired: list[uuid.UUID] = []
        for lease in self._session.scalars(stmt):
            transition_lease(lease, WorkerLeaseState.EXPIRED)
            expired.append(lease.id)
        self._session.flush()
        return LeaseSweepResult(expired_ids=expired)

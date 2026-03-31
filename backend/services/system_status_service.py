from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.domain.enums import WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet


class SystemStatusService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def health(self) -> dict[str, str]:
        self._session.execute(text("SELECT 1"))
        return {
            "database": "ok",
            "runtime": "ok",
            "queue": "configured",
        }

    def readiness(self) -> dict[str, str]:
        self._session.execute(text("SELECT 1"))
        return {
            "database": "ready",
            "dependencies": "ready",
        }

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
        return {
            "tasks": self._count_grouped(ExecutionTask, tenant_id=tenant_id),
            "fleets": self._count_grouped(WorkforceFleet, tenant_id=tenant_id),
            "leases": self._count_grouped(WorkerLease, tenant_id=tenant_id),
        }

    def _count_grouped(self, model, *, tenant_id: str) -> dict[str, int]:
        stmt = (
            select(model.status, func.count())
            .where(model.tenant_id == tenant_id)
            .group_by(model.status)
        )
        return {str(status): int(count) for status, count in self._session.execute(stmt).all()}

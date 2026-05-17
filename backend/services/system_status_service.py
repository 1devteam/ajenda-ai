from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.session import DatabaseRuntime
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet
from backend.queue.base import QueueAdapter


class SystemStatusService:
    def __init__(
        self,
        session: Session | None = None,
        *,
        queue_adapter: QueueAdapter | None = None,
        database_runtime: DatabaseRuntime | None = None,
    ) -> None:
        self._session = session
        self._queue_adapter = queue_adapter
        self._database_runtime = database_runtime

    def health(self) -> dict[str, str]:
        return {
            "database": "unchecked",
            "runtime": "ok",
            "queue": "unchecked",
        }

    def readiness(self) -> dict[str, str]:
        database_status = "ready" if self._database_ready() else "unavailable"
        queue_status = self._queue_status()
        dependencies_status = "ready" if database_status == "ready" and queue_status == "ready" else "not_ready"
        return {
            "database": database_status,
            "queue": queue_status,
            "dependencies": dependencies_status,
        }

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
        return {
            "tasks": self._count_grouped(ExecutionTask, tenant_id=tenant_id),
            "fleets": self._count_grouped(WorkforceFleet, tenant_id=tenant_id),
            "leases": self._count_grouped(WorkerLease, tenant_id=tenant_id),
        }

    def _database_ready(self) -> bool:
        if self._database_runtime is None:
            return False
        return self._database_runtime.ping()

    def _queue_status(self) -> str:
        if self._queue_adapter is None:
            return "unavailable"
        try:
            return "ready" if self._queue_adapter.ping() else "unavailable"
        except Exception:
            return "unavailable"

    def _count_grouped(self, model: type[Any], *, tenant_id: str) -> dict[str, int]:
        if self._session is None:
            raise RuntimeError("System status requires a database session")
        stmt = select(model.status, func.count()).where(model.tenant_id == tenant_id).group_by(model.status)
        return {str(status): int(count) for status, count in self._session.execute(stmt).all()}

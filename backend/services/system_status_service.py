from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet


class SystemStatusService:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def readiness(self, *, database_runtime: Any, queue_adapter: Any) -> tuple[int, dict[str, Any]]:
        database_ready = self._dependency_ready(database_runtime)
        queue_ready = self._dependency_ready(queue_adapter)
        dependencies = {
            "database": {"status": "ready" if database_ready else "unavailable"},
            "queue": {"status": "ready" if queue_ready else "unavailable"},
        }
        if database_ready and queue_ready:
            return 200, {"status": "ready", "dependencies": dependencies}
        reason = (
            "DEPENDENCY_UNAVAILABLE"
            if not database_ready and not queue_ready
            else "DATABASE_UNAVAILABLE"
            if not database_ready
            else "QUEUE_UNAVAILABLE"
        )
        return 503, {"status": "unavailable", "reason": reason, "dependencies": dependencies}

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
        if self._session is None:
            raise RuntimeError("System status requires a database session.")
        return {
            "tasks": self._count_grouped(ExecutionTask, tenant_id=tenant_id),
            "fleets": self._count_grouped(WorkforceFleet, tenant_id=tenant_id),
            "leases": self._count_grouped(WorkerLease, tenant_id=tenant_id),
        }

    def _count_grouped(self, model: type[Any], *, tenant_id: str) -> dict[str, int]:
        if self._session is None:
            raise RuntimeError("System status requires a database session.")
        stmt = select(model.status, func.count()).where(model.tenant_id == tenant_id).group_by(model.status)
        return {str(status): int(count) for status, count in self._session.execute(stmt).all()}

    @staticmethod
    def _dependency_ready(dependency: Any) -> bool:
        if dependency is None:
            return False
        ping = getattr(dependency, "ping", None)
        if not callable(ping):
            return False
        try:
            return bool(ping())
        except Exception:
            return False

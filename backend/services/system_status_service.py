from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet


class SystemStatusService:
    def __init__(self, session: Session | None) -> None:
        self._session = session

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def readiness(self, *, database_runtime: Any, queue_adapter: Any) -> tuple[int, dict[str, Any]]:
        database_status = self._dependency_status(database_runtime)
        queue_status = self._dependency_status(queue_adapter)

        response: dict[str, Any] = {
            "status": "ready",
            "dependencies": {
                "database": {"status": database_status},
                "queue": {"status": queue_status},
            },
        }

        unavailable = [
            name for name, status in (("database", database_status), ("queue", queue_status)) if status == "unavailable"
        ]
        if unavailable:
            response["status"] = "unavailable"
            if len(unavailable) == 2:
                response["reason"] = "DEPENDENCY_UNAVAILABLE"
            elif unavailable[0] == "database":
                response["reason"] = "DATABASE_UNAVAILABLE"
            else:
                response["reason"] = "QUEUE_UNAVAILABLE"
            return 503, response

        return 200, response

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
        return {
            "tasks": self._count_grouped(ExecutionTask, tenant_id=tenant_id),
            "fleets": self._count_grouped(WorkforceFleet, tenant_id=tenant_id),
            "leases": self._count_grouped(WorkerLease, tenant_id=tenant_id),
        }

    def _dependency_status(self, dependency: Any) -> str:
        if dependency is None:
            return "skipped"
        try:
            ready = bool(dependency.ping())
        except Exception:
            return "unavailable"
        return "ready" if ready else "unavailable"

    def _count_grouped(self, model: type[Any], *, tenant_id: str) -> dict[str, int]:
        if self._session is None:
            raise RuntimeError("System status requires a database session.")
        stmt = select(model.status, func.count()).where(model.tenant_id == tenant_id).group_by(model.status)
        return {str(status): int(count) for status, count in self._session.execute(stmt).all()}

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet


class DatabaseRuntimeProtocol(Protocol):
    def ping(self) -> bool: ...


class QueueAdapterProtocol(Protocol):
    def ping(self) -> bool: ...


@dataclass(frozen=True)
class DependencyStatus:
    status: str
    reason: str | None = None


class SystemStatusService:
    def __init__(self, session: Session | None) -> None:
        self._session = session

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def readiness(
        self, *, database_runtime: DatabaseRuntimeProtocol, queue_adapter: QueueAdapterProtocol
    ) -> dict[str, Any]:
        database = self._safe_dependency_ping(database_runtime.ping, unavailable_code="DATABASE_UNAVAILABLE")
        queue = self._safe_dependency_ping(queue_adapter.ping, unavailable_code="QUEUE_UNAVAILABLE")
        ready = database.status == "ready" and queue.status == "ready"
        dependencies: dict[str, dict[str, str]] = {
            "database": self._dependency_payload(database),
            "queue": self._dependency_payload(queue),
        }
        return {
            "status": "ready" if ready else "unavailable",
            "dependencies": dependencies,
            "reason": None if ready else "DEPENDENCY_UNAVAILABLE",
        }

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
        if self._session is None:
            raise RuntimeError("Session is required for tenant-scoped status checks")
        return {
            "tasks": self._count_grouped(ExecutionTask, tenant_id=tenant_id),
            "fleets": self._count_grouped(WorkforceFleet, tenant_id=tenant_id),
            "leases": self._count_grouped(WorkerLease, tenant_id=tenant_id),
        }

    def _count_grouped(self, model: type[Any], *, tenant_id: str) -> dict[str, int]:
        if self._session is None:
            raise RuntimeError("Session is required for grouped status checks")
        stmt = select(model.status, func.count()).where(model.tenant_id == tenant_id).group_by(model.status)
        return {str(status): int(count) for status, count in self._session.execute(stmt).all()}

    @staticmethod
    def _safe_dependency_ping(ping_callable: Any, *, unavailable_code: str) -> DependencyStatus:
        try:
            healthy = bool(ping_callable())
            return DependencyStatus(
                status="ready" if healthy else "unavailable", reason=None if healthy else unavailable_code
            )
        except Exception:
            return DependencyStatus(status="unavailable", reason=unavailable_code)

    @staticmethod
    def _dependency_payload(status: DependencyStatus) -> dict[str, str]:
        payload = {"status": status.status}
        if status.reason is not None:
            payload["reason"] = status.reason
        return payload

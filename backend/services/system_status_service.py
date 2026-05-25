from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet
from backend.metrics.prometheus_exporter import set_readiness_dependency_status
from backend.services.readiness_evaluator_service import ReadinessEvaluatorService


class SystemStatusService:
    def __init__(self, session: Session | None) -> None:
        self._session = session

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def readiness(self, *, database_runtime: Any, queue_adapter: Any) -> tuple[int, dict[str, Any]]:
        evaluation = ReadinessEvaluatorService().evaluate(
            database_runtime=database_runtime, queue_adapter=queue_adapter
        )
        set_readiness_dependency_status(dependency="database", status=evaluation.database_status)
        set_readiness_dependency_status(dependency="queue", status=evaluation.queue_status)
        return evaluation.status_code, evaluation.payload

    def status(self, *, tenant_id: str) -> dict[str, dict[str, int]]:
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

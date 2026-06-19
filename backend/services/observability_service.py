from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.observability.metrics import MetricsSnapshot, ObservabilityMetrics


class ObservabilityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._metrics = ObservabilityMetrics()

    def metrics_snapshot(self, *, tenant_id: str) -> MetricsSnapshot:
        queued_tasks = self._count_tasks_by_state(tenant_id=tenant_id, state=ExecutionTaskState.QUEUED.value)
        completed_tasks = self._count_tasks_by_state(tenant_id=tenant_id, state=ExecutionTaskState.COMPLETED.value)
        failed_tasks = self._count_tasks_by_state(tenant_id=tenant_id, state=ExecutionTaskState.FAILED.value)
        dead_letter = self._count_tasks_by_state(tenant_id=tenant_id, state=ExecutionTaskState.DEAD_LETTERED.value)
        active_leases = self._count_leases_by_state(
            tenant_id=tenant_id, states=[WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]
        )
        released_leases = self._count_leases_by_state(tenant_id=tenant_id, states=[WorkerLeaseState.RELEASED.value])
        lease_expirations = self._count_audit_actions(tenant_id=tenant_id, action="lease_expired_task_requeued")
        worker_utilization = float(active_leases) / float(max(active_leases + queued_tasks, 1))
        return self._metrics.snapshot(
            tasks_queued=queued_tasks,
            tasks_completed=completed_tasks,
            tasks_failed=failed_tasks,
            dead_letter_count=dead_letter,
            lease_expirations=lease_expirations,
            active_leases=active_leases,
            queued_tasks=queued_tasks,
            worker_utilization=worker_utilization,
            released_leases=released_leases,
            tenant_id=tenant_id,
        )

    def _count_tasks_by_state(self, *, tenant_id: str, state: str) -> int:
        stmt = (
            select(func.count())
            .select_from(ExecutionTask)
            .where(
                ExecutionTask.tenant_id == tenant_id,
                ExecutionTask.status == state,
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def _count_leases_by_state(self, *, tenant_id: str, states: list[str]) -> int:
        stmt = (
            select(func.count())
            .select_from(WorkerLease)
            .where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.status.in_(states),
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def _count_audit_actions(self, *, tenant_id: str, action: str) -> int:
        stmt = (
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == action,
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def compliance_export(self, *, tenant_id: str, limit: int = 100) -> dict[str, object]:
        """Foundation for compliance export: recent tenant-scoped audit and evidence.

        Returns limited recent records for audit/compliance review. Read-only.
        """
        audits = list(
            self._session.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
            )
        )
        evidences = list(
            self._session.scalars(
                select(EvidenceRecord)
                .where(EvidenceRecord.tenant_id == tenant_id)
                .order_by(EvidenceRecord.created_at.desc())
                .limit(limit)
            )
        )
        return {
            "tenant_id": tenant_id,
            "limit": limit,
            "audits": [
                {
                    "id": str(a.id),
                    "mission_id": str(a.mission_id) if a.mission_id else None,
                    "category": a.category,
                    "action": a.action,
                    "actor": a.actor,
                    "details": a.details,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in audits
            ],
            "evidences": [
                {
                    "id": str(e.id),
                    "mission_id": str(e.mission_id),
                    "evidence_type": e.evidence_type,
                    "evidence_source": e.evidence_source,
                    "summary": e.summary,
                    "collection_status": e.collection_status,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in evidences
            ],
        }

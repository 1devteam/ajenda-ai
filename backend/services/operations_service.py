from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.runtime_maintainer import RecoverySummary, RuntimeMaintainer


class OperationsService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._audit = AuditEventRepository(session)

    @staticmethod
    def _aggregate_recovery_summaries(summaries: Iterable[RecoverySummary]) -> RecoverySummary:
        """Combine tenant-scoped recovery results without widening DB authority."""
        totals = {
            field: 0
            for field in (
                "expired_lease_count",
                "requeued_task_count",
                "dead_lettered_count",
                "mismatched_state_count",
                "deliverable_reconciled_count",
                "dispatch_published_count",
                "dispatch_retry_scheduled_count",
                "cancelled_dispatch_cleanup_count",
                "cancelled_dispatch_cleanup_failed_count",
                "billing_meter_delivered_count",
                "billing_meter_retry_scheduled_count",
                "billing_meter_skipped_count",
            )
        }
        for summary in summaries:
            for field in totals:
                totals[field] += getattr(summary, field)
        return RecoverySummary(**totals)

    def _recover_all_tenants(self) -> RecoverySummary:
        """Run global recovery as bounded tenant-scoped passes.

        The API role is intentionally NOBYPASSRLS.  Tenant roots are the
        explicit control-plane inventory; every tenant-owned recovery read or
        write happens only after its transaction-local RLS setting is active.
        """
        tenant_ids = tuple(str(tenant_id) for tenant_id in self._session.scalars(select(Tenant.id)).all())
        summaries: list[RecoverySummary] = []
        for tenant_id in tenant_ids:
            activate_tenant_session(self._session, tenant_id)
            summaries.append(
                RuntimeMaintainer(self._session, self._queue, tenant_id=tenant_id).recover_expired_leases()
            )
        return self._aggregate_recovery_summaries(summaries)

    def inspect_dead_letter(self, *, tenant_id: str) -> list[dict[str, str]]:
        stmt = select(ExecutionTask).where(
            ExecutionTask.tenant_id == tenant_id,
            ExecutionTask.status == ExecutionTaskState.DEAD_LETTERED.value,
        )
        rows: dict[str, dict[str, str]] = {}
        for task in self._session.scalars(stmt):
            rows[str(task.id)] = {
                "task_id": str(task.id),
                "mission_id": str(task.mission_id),
                "status": task.status,
            }

        for entry in self._queue.list_dead_letter(tenant_id=tenant_id):
            if entry.task_id is None:
                rows[f"corrupt:{len(rows)}"] = {
                    "task_id": "",
                    "mission_id": "",
                    "status": "corrupt_dead_letter",
                }
                continue
            queue_task = self._session.get(ExecutionTask, entry.task_id)
            if queue_task is None or queue_task.tenant_id != tenant_id:
                continue
            rows.setdefault(
                str(queue_task.id),
                {
                    "task_id": str(queue_task.id),
                    "mission_id": str(queue_task.mission_id),
                    "status": queue_task.status,
                },
            )
        return list(rows.values())

    def retry_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID) -> dict[str, str]:
        task = self._session.get(ExecutionTask, task_id)
        if task is None or task.tenant_id != tenant_id:
            raise ValueError("task not found for tenant")
        if task.status not in {ExecutionTaskState.DEAD_LETTERED.value, ExecutionTaskState.FAILED.value}:
            raise ValueError("task is not dead-lettered or failed")

        result = ExecutionCoordinator(self._session, self._queue, audit_repository=self._audit).retry_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        return {"task_id": str(task.id), "status": result.state}

    def trigger_recovery(self, *, actor: str, actor_tenant_id: str) -> RecoverySummary:
        """Run global recovery with durable attribution to the human trigger."""
        self._audit.append(
            AuditEvent(
                tenant_id=actor_tenant_id,
                mission_id=None,
                category="runtime_recovery",
                action="global_recovery_requested",
                actor=actor,
                details="Platform operator requested global expired-lease recovery.",
                payload_json={
                    "scope": "platform",
                    "executor": "runtime_maintainer",
                    "trigger_source": "manual_api",
                },
            )
        )
        # Persist the initiating human identity before the maintainer begins its
        # independently committed cross-tenant recovery loop.
        self._session.flush()
        self._session.commit()

        try:
            summary = self._recover_all_tenants()
        except Exception as exc:
            self._audit.append(
                AuditEvent(
                    tenant_id=actor_tenant_id,
                    mission_id=None,
                    category="runtime_recovery",
                    action="global_recovery_failed",
                    actor=actor,
                    details="Platform-triggered global recovery failed.",
                    payload_json={
                        "scope": "platform",
                        "executor": "runtime_maintainer",
                        "trigger_source": "manual_api",
                        "error_type": type(exc).__name__,
                    },
                )
            )
            self._session.flush()
            self._session.commit()
            raise

        self._audit.append(
            AuditEvent(
                tenant_id=actor_tenant_id,
                mission_id=None,
                category="runtime_recovery",
                action="global_recovery_completed",
                actor=actor,
                details="Platform-triggered global recovery completed.",
                payload_json={
                    "scope": "platform",
                    "executor": "runtime_maintainer",
                    "trigger_source": "manual_api",
                    "expired_lease_count": summary.expired_lease_count,
                    "requeued_task_count": summary.requeued_task_count,
                    "dead_lettered_count": summary.dead_lettered_count,
                    "mismatched_state_count": summary.mismatched_state_count,
                    "billing_meter_delivered_count": summary.billing_meter_delivered_count,
                    "billing_meter_retry_scheduled_count": summary.billing_meter_retry_scheduled_count,
                    "billing_meter_skipped_count": summary.billing_meter_skipped_count,
                },
            )
        )
        self._session.flush()
        self._session.commit()
        return summary

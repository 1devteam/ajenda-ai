"""Recognition-only activation for governed learning-history consolidation.

The worker runtime owns completion-time recognition because it is the first
owner that can prove a learning signal was durably persisted.  This module
creates a review-held task; it never invokes consolidation or writes knowledge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter
from backend.repositories.tenant_repository import TenantRepository
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.runtime_governance import manifest_governance_snapshot
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_bridge_runtime_authority import ensure_bridge_runtime_authority

CONSOLIDATION_ACTION = "knowledge.consolidate_learning_history"
CONSOLIDATION_SCOPE = "tenant_eligible_learning_history_v1"
_LEARNING_SIGNAL_ACTION = "analysis.materialize_decision_learning_signal"
_LEARNING_SIGNAL_ROLE = "decision_learning_signal"
# Only unapproved reviews can absorb new evidence. Admission/approval freezes
# the review scope; a signal arriving after that point needs a successor review
# even while the prior consolidation is queued, claimed, or running.
_COALESCIBLE_REVIEW_STATES = {
    ExecutionTaskState.PLANNED.value,
    ExecutionTaskState.PENDING_REVIEW.value,
}


@dataclass(frozen=True, slots=True)
class ConsolidationActivation:
    task_id: uuid.UUID | None
    created: bool
    source_evidence_ids: tuple[str, ...]
    reason: str


def _is_learning_signal(record: EvidenceRecord) -> bool:
    return (
        record.provenance_metadata.get("action_name") == _LEARNING_SIGNAL_ACTION
        and record.provenance_metadata.get("evidence_role") == _LEARNING_SIGNAL_ROLE
    )


def _activation_metadata(task: ExecutionTask) -> dict[str, object] | None:
    raw = (task.metadata_json or {}).get("learning_consolidation_activation")
    return dict(raw) if isinstance(raw, dict) else None


def maybe_activate_learning_consolidation(
    *,
    session: Session,
    queue: QueueAdapter,
    completed_task: ExecutionTask,
    evidence_records: list[EvidenceRecord],
) -> ConsolidationActivation | None:
    """Create or update one approval-held task for the tenant consolidation scope."""

    sources = tuple(sorted({str(record.id) for record in evidence_records if _is_learning_signal(record)}))
    if not sources:
        return None

    # Serialize admission across the tenant so concurrent worker completions
    # cannot create competing tasks for the same all-eligible-history scope.
    TenantRepository(session).get_active_for_update(uuid.UUID(completed_task.tenant_id))
    open_tasks = session.scalars(
        select(ExecutionTask).where(ExecutionTask.tenant_id == completed_task.tenant_id).with_for_update()
    ).all()
    for candidate in open_tasks:
        activation = _activation_metadata(candidate)
        if (
            candidate.status in _COALESCIBLE_REVIEW_STATES
            and activation is not None
            and activation.get("consolidation_scope") == CONSOLIDATION_SCOPE
            and (candidate.metadata_json or {}).get("tool_invocation", {}).get("action") == CONSOLIDATION_ACTION
        ):
            existing = activation.get("source_evidence_ids")
            existing_ids = {str(item) for item in existing} if isinstance(existing, list) else set()
            activation["source_evidence_ids"] = sorted(existing_ids | set(sources))
            candidate.metadata_json = {
                **dict(candidate.metadata_json or {}),
                "learning_consolidation_activation": activation,
            }
            session.add(candidate)
            session.flush()
            return ConsolidationActivation(candidate.id, False, sources, "open_scope_task_updated")

    capability, adapter = ensure_bridge_runtime_authority(
        db=session,
        tenant_id=completed_task.tenant_id,
        action_name=CONSOLIDATION_ACTION,
        admitted_by="runtime_learning_signal_activation",
        tool_input={},
    )
    manifest = ABILITY_MANIFESTS_BY_ACTION[CONSOLIDATION_ACTION]
    task = ExecutionTask(
        tenant_id=completed_task.tenant_id,
        mission_id=completed_task.mission_id,
        title="Review durable learning-history consolidation",
        description="Eligible decision-learning evidence is available for governed consolidation.",
        status=ExecutionTaskState.PLANNED.value,
        requires_human_review=True,
        compliance_category=completed_task.compliance_category,
        jurisdiction=completed_task.jurisdiction,
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {"schema_version": 1, "action": CONSOLIDATION_ACTION, "input": {}},
            "capability_reference": {"capability_id": str(capability.id)},
            "adapter_reference": {"adapter_id": str(adapter.id)},
            "ability_governance": manifest_governance_snapshot(manifest),
            "learning_consolidation_activation": {
                "schema_version": 1,
                "consolidation_scope": CONSOLIDATION_SCOPE,
                "source_evidence_ids": list(sources),
                "recognition_only": True,
                "grants_execution_authority": False,
            },
        },
    )
    session.add(task)
    session.flush()
    admission = ExecutionCoordinator(session, queue).queue_task(tenant_id=task.tenant_id, task_id=task.id)
    if admission.state != ExecutionTaskState.PENDING_REVIEW.value:
        raise RuntimeError("learning consolidation activation must be held for human review")
    return ConsolidationActivation(task.id, True, sources, "pending_human_approval")

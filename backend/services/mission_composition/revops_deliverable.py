"""Assemble a read-only RevOps mission deliverable from runtime-owned artifacts.

The assembler is descriptive. It validates tenant/mission ownership, reads only
completed task artifacts, recomputes deliverable completion, and projects current
approval/effect evidence. It never mutates missions or tasks, grants authority,
queues work, or performs an external effect.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, UTC
from typing import Any

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.deliverable_completion import (
    evaluate_deliverable_completion,
)
from backend.services.mission_composition.deliverable_runtime_artifacts import (
    collect_materialized_artifacts,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    load_deliverable_runtime_state,
)
from backend.services.mission_composition.revops_deliverable_approval import _approval_state
from backend.services.mission_composition.revops_deliverable_contracts import (
    RevOpsEvidenceReferenceRead,
    RevOpsMissionDeliverableRead,
    RevOpsTaskStateRead,
)
from backend.services.mission_composition.revops_deliverable_effects import _effects, _limitations
from backend.services.mission_composition.revops_deliverable_prospects import _assemble_prospects
from backend.services.mission_composition.revops_deliverable_runtime import (
    _completion_read,
    _runtime_state_from_metadata,
    _validate_ownership,
    _validated_artifacts,
)

_DRAFT_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected", "sent"})
_TERMINAL_TASK_STATES = frozenset(
    {
        ExecutionTaskState.COMPLETED.value,
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.CANCELLED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
        ExecutionTaskState.BLOCKED.value,
    }
)


def assemble_revops_mission_deliverable(
    *,
    mission: Mission,
    tasks: Sequence[ExecutionTask],
    document_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    evidence_records: Sequence[EvidenceRecord] = (),
    outcome_reviews: Sequence[OutcomeReview] = (),
    now: datetime | None = None,
) -> RevOpsMissionDeliverableRead:
    """Assemble the current tenant-owned RevOps report without mutating runtime state."""

    _validate_ownership(
        mission=mission,
        tasks=tasks,
        evidence_records=evidence_records,
        outcome_reviews=outcome_reviews,
    )
    state = load_deliverable_runtime_state(_runtime_state_from_metadata(mission.metadata_json))
    if state is None:
        raise ValueError("mission deliverable runtime state is absent")
    request_fields = tuple(field.field_key for field in state.request.fields)
    projected_fields = tuple(binding.field_key for binding in state.projection.bindings)
    if projected_fields != request_fields:
        raise ValueError("mission deliverable runtime projection does not match its request")
    if state.projection.request_unresolved_items != state.request.unresolved_items:
        raise ValueError("mission deliverable runtime unresolved items do not match its request")

    assembly_errors: list[str] = []
    collected = collect_materialized_artifacts(list(tasks))
    artifacts = _validated_artifacts(tasks, assembly_errors=assembly_errors)
    completion = evaluate_deliverable_completion(state.projection, collected)
    prospects = _assemble_prospects(
        mission=mission,
        artifacts=artifacts,
        document_artifacts=document_artifacts or {},
        assembly_errors=assembly_errors,
    )
    evidence_reads = tuple(
        RevOpsEvidenceReferenceRead(
            evidence_id=evidence.id,
            execution_task_id=evidence.execution_task_id,
            evidence_type=evidence.evidence_type,
            evidence_source=evidence.evidence_source,
            summary=evidence.summary,
            confidence=evidence.confidence,
            collection_status=evidence.collection_status,
        )
        for evidence in sorted(evidence_records, key=lambda item: (item.created_at, str(item.id)))
    )
    status_counts = Counter(task.status for task in tasks)
    task_state = RevOpsTaskStateRead(
        task_count=len(tasks),
        statuses=dict(sorted(status_counts.items())),
        all_terminal=bool(tasks) and all(task.status in _TERMINAL_TASK_STATES for task in tasks),
        all_succeeded=bool(tasks) and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks),
    )
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None:
        raise ValueError("assembler now must be timezone-aware")
    approval_state = _approval_state(
        prospects=prospects,
        tasks=tasks,
        outcome_reviews=outcome_reviews,
        now=effective_now.astimezone(UTC),
    )
    limitations = _limitations(
        tasks=tasks,
        evidence_records=evidence_records,
        assembly_errors=assembly_errors,
    )
    return RevOpsMissionDeliverableRead(
        mission_id=mission.id,
        objective=mission.objective,
        artifacts={artifact_key: artifact.payload for artifact_key, artifact in artifacts.items()},
        prospects=prospects,
        assumptions=(),
        limitations=limitations,
        approval_state=approval_state,
        effects=_effects(tasks=tasks, evidence_records=evidence_records),
        evidence_references=evidence_reads,
        task_state=task_state,
        completion=_completion_read(
            state=state,
            completion=completion,
            assembly_errors=assembly_errors,
        ),
        result_semantics={
            "completion_scope": "requested_deliverable",
            "mission_acceptance": (
                mission.metadata_json.get("acceptance") if isinstance(mission.metadata_json, dict) else None
            ),
            "business_outcome_status": (
                artifacts["goal_progress_evaluation"].payload.get("status")
                if "goal_progress_evaluation" in artifacts
                and isinstance(artifacts["goal_progress_evaluation"].payload, dict)
                else None
            ),
        },
    )

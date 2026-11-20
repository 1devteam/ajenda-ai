"""Assemble a read-only RevOps mission deliverable from runtime-owned artifacts.

The assembler is descriptive. It validates tenant/mission ownership, reads only
completed task artifacts, recomputes deliverable completion, and projects current
approval/effect evidence. It never mutates missions or tasks, grants authority,
queues work, or performs an external effect.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
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
    declared_artifact_key,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    build_deliverable_runtime_state,
    goal_evaluation_deliverable_request,
    load_deliverable_runtime_state,
)
from backend.services.mission_composition.revops_deliverable_approval import _approval_state
from backend.services.mission_composition.revops_deliverable_contracts import (
    RevOpsCompletionRead,
    RevOpsEvidenceReferenceRead,
    RevOpsTaskStateRead,
)
from backend.services.mission_composition.revops_deliverable_contracts import (
    RevOpsMissionDeliverableRead as RevOpsMissionDeliverableRead,
)
from backend.services.mission_composition.revops_deliverable_effects import _effects, _limitations
from backend.services.mission_composition.revops_deliverable_prospects import _assemble_prospects
from backend.services.mission_composition.revops_deliverable_runtime import (
    _completion_read,
    _public_research_stages,
    _runtime_state_from_metadata,
    _validate_ownership,
    _validated_artifacts,
)
from backend.services.mission_composition.vertical_know_how import REVOPS_V2_KNOW_HOW
from backend.services.tools.mission_input_binding import handler_output_for_task

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


def _is_completed_standalone_goal_evaluation(tasks: Sequence[ExecutionTask]) -> bool:
    if len(tasks) != 1:
        return False
    task = tasks[0]
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    return (
        task.status == ExecutionTaskState.COMPLETED.value
        and declared_artifact_key(task) == "goal_progress_evaluation"
        and isinstance(invocation, dict)
        and invocation.get("action") == "analysis.evaluate_goal_progress"
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
    state = load_deliverable_runtime_state(_runtime_state_from_metadata(mission.metadata_json), include_shadow=False)
    if state is None and _is_completed_standalone_goal_evaluation(tasks):
        # Older composed goals persisted the declared task result without a
        # mission projection. Reuse the typed projection only for readback.
        state = load_deliverable_runtime_state(
            build_deliverable_runtime_state(goal_evaluation_deliverable_request(), know_how=REVOPS_V2_KNOW_HOW)
        )
    if state is None:
        calendar_tasks = [
            task
            for task in tasks
            if task.status == ExecutionTaskState.COMPLETED.value
            and declared_artifact_key(task) == "calendar_events"
            and isinstance(task.metadata_json, dict)
            and isinstance(task.metadata_json.get("tool_invocation"), dict)
            and task.metadata_json["tool_invocation"].get("action") == "google_calendar.events_read"
        ]
        calendar_artifacts = collect_materialized_artifacts(calendar_tasks)
        calendar_artifact = next(
            (artifact for artifact in calendar_artifacts if artifact.artifact_key == "calendar_events"), None
        )
        if calendar_artifact is not None:
            if len(tasks) != 1 or len(calendar_tasks) != 1 or not isinstance(calendar_artifact.payload, list):
                raise ValueError("calendar event artifact is ambiguous or invalid")
            if any(not isinstance(item, dict) for item in calendar_artifact.payload):
                raise ValueError("calendar event artifact contains invalid records")
            calendar_task = calendar_tasks[0]
            output = handler_output_for_task(calendar_task)
            invocation = calendar_task.metadata_json["tool_invocation"]
            invocation_input = invocation.get("input") if isinstance(invocation.get("input"), dict) else {}
            calendar_limitations: list[str] = []
            if output.get("real") is not True:
                calendar_limitations.append("A real Calendar provider response was not established.")
            if output.get("has_more") is True:
                calendar_limitations.append("Additional Calendar events were not retrieved.")
            elif output.get("has_more") is not False:
                calendar_limitations.append("Calendar pagination completeness was not recorded.")
            if "upcoming" in mission.objective.casefold():
                raw_start = output.get("effective_start")
                try:
                    parsed_start = (
                        datetime.fromisoformat(raw_start.replace("Z", "+00:00")) if isinstance(raw_start, str) else None
                    )
                except ValueError:
                    parsed_start = None
                if invocation_input.get("upcoming") is not True or parsed_start is None or parsed_start.tzinfo is None:
                    calendar_limitations.append("The upcoming time bound was not recorded.")
            complete = not calendar_limitations and all(
                task.status == ExecutionTaskState.COMPLETED.value for task in tasks
            )
            effective_now = now or datetime.now(UTC)
            if effective_now.tzinfo is None:
                raise ValueError("assembler now must be timezone-aware")
            return RevOpsMissionDeliverableRead(
                mission_id=mission.id,
                objective=mission.objective,
                artifacts={"calendar_events": calendar_artifact.payload},
                limitations=tuple(calendar_limitations),
                approval_state=_approval_state(
                    prospects=(), tasks=tasks, outcome_reviews=outcome_reviews, now=effective_now.astimezone(UTC)
                ),
                effects=_effects(tasks=tasks, evidence_records=evidence_records),
                evidence_references=tuple(
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
                ),
                task_state=RevOpsTaskStateRead(
                    task_count=len(tasks),
                    statuses=dict(sorted(Counter(task.status for task in tasks).items())),
                    all_terminal=bool(tasks) and all(task.status in _TERMINAL_TASK_STATES for task in tasks),
                    all_succeeded=bool(tasks)
                    and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks),
                ),
                completion=RevOpsCompletionRead(
                    artifact_complete=complete,
                    complete=complete,
                    unresolved_items=tuple(calendar_limitations),
                    observed_row_count=len(calendar_artifact.payload),
                ),
                result_semantics={
                    "completion_scope": "calendar_provider_page",
                    "source_observations": [
                        {
                            "task_id": str(calendar_task.id),
                            "real": output.get("real"),
                            "effective_start": output.get("effective_start"),
                            "has_more": output.get("has_more"),
                        }
                    ],
                    "mission_acceptance": mission.metadata_json.get("acceptance")
                    if isinstance(mission.metadata_json, dict)
                    else None,
                },
            )
        email_tasks = [
            task
            for task in tasks
            if task.status == ExecutionTaskState.COMPLETED.value
            and declared_artifact_key(task) == "email_messages"
            and isinstance(task.metadata_json, dict)
            and isinstance(task.metadata_json.get("tool_invocation"), dict)
            and task.metadata_json["tool_invocation"].get("action") == "gtm.email_check"
        ]
        collected = collect_materialized_artifacts(email_tasks)
        email_artifact = next((artifact for artifact in collected if artifact.artifact_key == "email_messages"), None)
        if email_artifact is None or not isinstance(email_artifact.payload, list):
            raise ValueError("mission deliverable runtime state is absent")
        if any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
            for item in email_artifact.payload
        ):
            raise ValueError("email reference artifact is invalid")
        effective_now = now or datetime.now(UTC)
        if effective_now.tzinfo is None:
            raise ValueError("assembler now must be timezone-aware")
        source_observations = []
        for item in email_tasks:
            output = handler_output_for_task(item)
            scope = output.get("retrieval_scope")
            source_observations.append(
                {
                    "task_id": str(item.id),
                    "real": output.get("real") if isinstance(output.get("real"), bool) else None,
                    "retrieval_scope": scope if scope in ("message_references", "simulated") else "unknown",
                    "has_more": output.get("has_more") if isinstance(output.get("has_more"), bool) else None,
                }
            )
        return RevOpsMissionDeliverableRead(
            mission_id=mission.id,
            objective=mission.objective,
            artifacts={"email_messages": email_artifact.payload},
            limitations=("Message content was not retrieved; these are message references only.",),
            approval_state=_approval_state(
                prospects=(), tasks=tasks, outcome_reviews=outcome_reviews, now=effective_now.astimezone(UTC)
            ),
            effects=_effects(tasks=tasks, evidence_records=evidence_records),
            evidence_references=tuple(
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
            ),
            task_state=RevOpsTaskStateRead(
                task_count=len(tasks),
                statuses=dict(sorted(Counter(task.status for task in tasks).items())),
                all_terminal=bool(tasks) and all(task.status in _TERMINAL_TASK_STATES for task in tasks),
                all_succeeded=bool(tasks) and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks),
            ),
            completion=RevOpsCompletionRead(unresolved_items=("Message content was not retrieved.",)),
            result_semantics={
                "completion_scope": "message_references",
                "source_observations": source_observations,
                "mission_acceptance": mission.metadata_json.get("acceptance")
                if isinstance(mission.metadata_json, dict)
                else None,
            },
        )
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
        verified_artifact_present=any(
            artifact.artifact_key == "verified_prospect_candidates" for artifact in collected
        ),
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
    public_research_stages = _public_research_stages(tasks)
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
            **({"public_research_stages": public_research_stages} if public_research_stages else {}),
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

"""Runtime-state and artifact validation for RevOps deliverable assembly."""

from collections.abc import Sequence
from typing import Any

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.artifact_schemas import ARTIFACT_SCHEMAS_BY_KEY
from backend.services.mission_composition.deliverable_completion import (
    DeliverableCompletion,
    MaterializedArtifact,
    validate_materialized_artifact,
)
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.deliverable_runtime_artifacts import (
    collect_materialized_artifacts,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
)
from backend.services.mission_composition.revops_deliverable_contracts import RevOpsCompletionRead


def _runtime_state_from_metadata(metadata: object) -> object | None:
    if not isinstance(metadata, dict):
        return None
    intake = metadata.get("mission_intake")
    if not isinstance(intake, dict):
        return None
    context = intake.get("context")
    if not isinstance(context, dict):
        return None
    composition = context.get("composition")
    if not isinstance(composition, dict):
        return None
    return composition.get(DELIVERABLE_RUNTIME_STATE_METADATA_KEY)

def _validate_ownership(
    *,
    mission: Mission,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
    outcome_reviews: Sequence[OutcomeReview],
) -> None:
    for task in tasks:
        if task.tenant_id != mission.tenant_id or task.mission_id != mission.id:
            raise ValueError("execution task is not owned by the assembled tenant mission")
    for evidence in evidence_records:
        if evidence.tenant_id != mission.tenant_id or evidence.mission_id != mission.id:
            raise ValueError("evidence record is not owned by the assembled tenant mission")
    for review in outcome_reviews:
        if review.tenant_id != mission.tenant_id or review.mission_id != mission.id:
            raise ValueError("outcome review is not owned by the assembled tenant mission")

def _completion_read(
    *,
    state: Any,
    completion: DeliverableCompletion,
    assembly_errors: Sequence[str],
) -> RevOpsCompletionRead:
    satisfied: list[DeliverableFieldKey] = []
    missing: list[DeliverableFieldKey] = []
    invalid: list[DeliverableFieldKey] = []
    unproven: list[DeliverableFieldKey] = []
    observed_row_count = max((field.observed_rows for field in completion.fields), default=0)
    required_row_count = max((field.required_rows for field in completion.fields), default=0)
    for field in completion.fields:
        if field.status == "satisfied":
            satisfied.append(field.field_key)
        elif field.status == "missing_artifact":
            missing.append(field.field_key)
        elif field.status in {"invalid_artifact", "insufficient_rows"}:
            invalid.append(field.field_key)
        else:
            unproven.append(field.field_key)
    errors = tuple(dict.fromkeys(assembly_errors))
    return RevOpsCompletionRead(
        requested_fields=tuple(field.field_key for field in state.request.fields),
        satisfied_fields=tuple(satisfied),
        missing_fields=tuple(missing),
        invalid_fields=tuple(invalid),
        unproven_fields=tuple(unproven),
        unresolved_items=completion.unresolved_request_items,
        artifact_complete=completion.complete,
        assembly_errors=errors,
        complete=completion.complete and not errors,
        observed_row_count=observed_row_count,
        required_row_count=required_row_count,
    )

def _validated_artifacts(
    tasks: Sequence[ExecutionTask],
    *,
    assembly_errors: list[str],
) -> dict[str, MaterializedArtifact]:
    validated: dict[str, MaterializedArtifact] = {}
    for artifact in collect_materialized_artifacts(list(tasks)):
        if artifact.artifact_key in ARTIFACT_SCHEMAS_BY_KEY:
            validation = validate_materialized_artifact(artifact)
            if not validation.valid:
                assembly_errors.append(f"artifact {artifact.artifact_key!r} is invalid: {'; '.join(validation.errors)}")
                continue
        validated[artifact.artifact_key] = artifact
    return validated


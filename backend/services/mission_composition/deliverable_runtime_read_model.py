"""Refresh persisted deliverable completion from completed mission task outputs.

The read model is non-authoritative. Updating it never changes task state, mission
state, approvals, credentials, queue state, or external-effect authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_completion import (
    DeliverableCompletion,
    evaluate_deliverable_completion,
)
from backend.services.mission_composition.deliverable_runtime_artifacts import (
    collect_materialized_artifacts,
    conflicting_materialized_artifact_keys,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    DeliverableArtifactLifecycle,
    DeliverableLifecycleState,
    load_deliverable_runtime_state,
)
from backend.services.mission_composition.shadow_preview import reconcile_shadow_preview


def refresh_deliverable_completion_metadata(
    metadata: dict[str, Any],
    tasks: list[ExecutionTask],
) -> tuple[dict[str, Any], DeliverableCompletion | None]:
    """Return refreshed mission metadata without mutating the caller's mapping."""

    updated = dict(metadata)
    raw_intake = updated.get("mission_intake")
    if not isinstance(raw_intake, dict):
        return updated, None
    intake = dict(raw_intake)
    raw_context = intake.get("context")
    if not isinstance(raw_context, dict):
        return updated, None
    context = dict(raw_context)
    raw_composition = context.get("composition")
    if not isinstance(raw_composition, dict):
        return updated, None
    composition = dict(raw_composition)

    raw_state = composition.get(DELIVERABLE_RUNTIME_STATE_METADATA_KEY)
    try:
        state = load_deliverable_runtime_state(raw_state)
    except ValidationError:
        return updated, None
    if state is None:
        return updated, None

    artifacts = collect_materialized_artifacts(tasks)
    completion = evaluate_deliverable_completion(state.projection, artifacts)
    now = datetime.now(UTC)
    conflicts = conflicting_materialized_artifact_keys(tasks)
    if conflicts:
        lifecycle_state: DeliverableLifecycleState = "contradictory"
        contradiction_codes = tuple(f"conflicting_artifact:{key}" for key in conflicts)
    elif not artifacts:
        lifecycle_state = "planned"
        contradiction_codes = ()
    elif completion.complete:
        lifecycle_state = "current"
        contradiction_codes = ()
    else:
        lifecycle_state = "incomplete"
        contradiction_codes = ()
    lifecycle = DeliverableArtifactLifecycle(
        state=lifecycle_state,
        observed_at=now if artifacts else state.lifecycle.observed_at,
        reconciled_at=now,
        freshness_window_seconds=state.lifecycle.freshness_window_seconds,
        materialized_artifact_count=len(artifacts),
        contradiction_codes=contradiction_codes,
        supersedes_artifact_id=state.lifecycle.supersedes_artifact_id,
        epistemic_context_schema_version=state.lifecycle.epistemic_context_schema_version,
        epistemic_freshness=state.lifecycle.epistemic_freshness,
        epistemic_contradiction_status=state.lifecycle.epistemic_contradiction_status,
        epistemic_missing_evidence=state.lifecycle.epistemic_missing_evidence,
        epistemic_budget_status=state.lifecycle.epistemic_budget_status,
        epistemic_budget_excesses=state.lifecycle.epistemic_budget_excesses,
        coverage_assessment=state.lifecycle.coverage_assessment,
        graph_lineage=state.lifecycle.graph_lineage,
        epistemic_reconciliation=state.lifecycle.epistemic_reconciliation,
    )
    completion_payload: dict[str, object] = {
        **completion.model_dump(mode="json"),
        "complete": completion.complete,
    }
    runtime_reconciliation = (
        reconcile_shadow_preview(
            state.shadow_preview,
            tasks=tasks,
            artifacts=artifacts,
            completion=completion,
            contradiction_codes=tuple(f"conflicting_artifact:{key}" for key in conflicts),
        )
        if state.shadow_preview is not None
        else state.runtime_reconciliation
    )
    refreshed_state = state.model_copy(
        update={
            "completion": completion_payload,
            "lifecycle": lifecycle,
            "runtime_reconciliation": runtime_reconciliation,
        }
    )

    composition[DELIVERABLE_RUNTIME_STATE_METADATA_KEY] = refreshed_state.model_dump(mode="json")
    context["composition"] = composition
    intake["context"] = context
    updated["mission_intake"] = intake
    return updated, completion

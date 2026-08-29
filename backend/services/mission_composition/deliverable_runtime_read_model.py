"""Refresh persisted deliverable completion from completed mission task outputs.

The read model is non-authoritative. Updating it never changes task state, mission
state, approvals, credentials, queue state, or external-effect authority.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_completion import (
    DeliverableCompletion,
    evaluate_deliverable_completion,
)
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    load_deliverable_runtime_state,
)


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
    completion_payload: dict[str, object] = {
        **completion.model_dump(mode="json"),
        "complete": completion.complete,
    }
    refreshed_state = state.model_copy(update={"completion": completion_payload})

    composition[DELIVERABLE_RUNTIME_STATE_METADATA_KEY] = refreshed_state.model_dump(mode="json")
    context["composition"] = composition
    intake["context"] = context
    updated["mission_intake"] = intake
    return updated, completion

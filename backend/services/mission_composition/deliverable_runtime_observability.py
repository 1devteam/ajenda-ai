"""Project persisted deliverable runtime state into a read-only mission API view.

The projection validates canonical request, binding, and completion consistency
before reporting status. It never mutates mission metadata, advances runtime
state, or grants execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.services.mission_composition.contracts import CoverageAssessment, EpistemicContext
from backend.services.mission_composition.deliverable_completion import DeliverableCompletion
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    DeliverableLifecycleState,
    load_deliverable_runtime_state,
)


class DeliverableRuntimeStateRead(BaseModel):
    """Validated, non-authoritative deliverable completion observability."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    requested_fields: tuple[DeliverableFieldKey, ...] = ()
    satisfied_fields: tuple[DeliverableFieldKey, ...] = ()
    missing_fields: tuple[DeliverableFieldKey, ...] = ()
    invalid_fields: tuple[DeliverableFieldKey, ...] = ()
    unproven_fields: tuple[DeliverableFieldKey, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    complete: bool = False
    lifecycle_state: DeliverableLifecycleState = "planned"
    observed_at: datetime | None = None
    reconciled_at: datetime | None = None
    contradiction_codes: tuple[str, ...] = ()
    coverage_assessment: CoverageAssessment | None = None
    epistemic_context: EpistemicContext | None = None
    grants_execution_authority: Literal[False] = False


def _raw_runtime_state(metadata: object) -> object | None:
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


def _raw_composition(metadata: object) -> dict[str, object] | None:
    """Return the confirmed composition envelope without trusting its contents."""

    if not isinstance(metadata, dict):
        return None
    intake = metadata.get("mission_intake")
    if not isinstance(intake, dict):
        return None
    context = intake.get("context")
    if not isinstance(context, dict):
        return None
    composition = context.get("composition")
    return composition if isinstance(composition, dict) else None


def build_deliverable_runtime_state_read(metadata: object) -> DeliverableRuntimeStateRead | None:
    """Build a validated read model from mission metadata, failing closed on drift."""

    raw_state = _raw_runtime_state(metadata)
    state = load_deliverable_runtime_state(raw_state)
    if state is None:
        return None

    composition = _raw_composition(metadata)
    coverage = (
        CoverageAssessment.model_validate(composition["coverage_assessment"])
        if composition is not None and isinstance(composition.get("coverage_assessment"), dict)
        else None
    )
    epistemic = (
        EpistemicContext.model_validate(composition["epistemic_context"])
        if composition is not None and isinstance(composition.get("epistemic_context"), dict)
        else None
    )

    requested_fields = tuple(field.field_key for field in state.request.fields)
    projected_fields = tuple(binding.field_key for binding in state.projection.bindings)
    if projected_fields != requested_fields:
        raise ValueError("deliverable runtime projection fields do not match the canonical request")
    if state.projection.request_unresolved_items != state.request.unresolved_items:
        raise ValueError("deliverable runtime projection unresolved items do not match the canonical request")

    satisfied_fields: list[DeliverableFieldKey] = []
    missing_fields: list[DeliverableFieldKey] = []
    invalid_fields: list[DeliverableFieldKey] = []
    unproven_fields: list[DeliverableFieldKey] = []
    complete = False

    if state.completion is None:
        for binding in state.projection.bindings:
            if binding.status == "bound":
                missing_fields.append(binding.field_key)
            else:
                unproven_fields.append(binding.field_key)
    else:
        raw_completion = dict(state.completion)
        raw_completion.pop("complete", None)
        completion = DeliverableCompletion.model_validate(raw_completion)
        completion_fields = tuple(field.field_key for field in completion.fields)
        if completion_fields != requested_fields:
            raise ValueError("deliverable completion fields do not match the canonical request")
        if completion.unresolved_request_items != state.request.unresolved_items:
            raise ValueError("deliverable completion unresolved items do not match the canonical request")

        for field in completion.fields:
            if field.status == "satisfied":
                satisfied_fields.append(field.field_key)
            elif field.status == "missing_artifact":
                missing_fields.append(field.field_key)
            elif field.status == "invalid_artifact":
                invalid_fields.append(field.field_key)
            else:
                unproven_fields.append(field.field_key)
        complete = completion.complete

    return DeliverableRuntimeStateRead(
        requested_fields=requested_fields,
        satisfied_fields=tuple(satisfied_fields),
        missing_fields=tuple(missing_fields),
        invalid_fields=tuple(invalid_fields),
        unproven_fields=tuple(unproven_fields),
        unresolved_items=state.request.unresolved_items,
        complete=complete,
        lifecycle_state=state.lifecycle.effective_state(),
        observed_at=state.lifecycle.observed_at,
        reconciled_at=state.lifecycle.reconciled_at,
        contradiction_codes=state.lifecycle.contradiction_codes,
        coverage_assessment=coverage,
        epistemic_context=epistemic,
    )

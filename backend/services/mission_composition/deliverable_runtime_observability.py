"""Project persisted deliverable runtime state into a read-only mission API view.

The projection validates canonical request, binding, and completion consistency
before reporting status. It never mutates mission metadata, advances runtime
state, or grants execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.services.mission_composition.contracts import (
    CoverageAssessment,
    EpistemicBudgetStatus,
    EpistemicContext,
    GraphLineage,
)
from backend.services.mission_composition.deliverable_completion import DeliverableCompletion
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    DeliverableLifecycleState,
    load_deliverable_runtime_state,
)
from backend.services.mission_composition.semantic_vocabulary import SemanticSelection
from backend.services.mission_composition.shadow_preview import RuntimeReconciliation, ShadowPreview


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
    epistemic_reconciliation: Literal["not_available", "aligned", "blocked"] = "not_available"
    epistemic_missing_evidence: tuple[str, ...] = ()
    epistemic_budget_status: EpistemicBudgetStatus = "within_budget"
    epistemic_budget_excesses: tuple[str, ...] = ()
    epistemic_source_classes: tuple[str, ...] = ()
    epistemic_confidence: float | None = None
    epistemic_confidence_semantics: str | None = None
    epistemic_confidence_basis: tuple[str, ...] = ()
    epistemic_required_evidence: tuple[str, ...] = ()
    semantic_selection: SemanticSelection | None = None
    semantic_reconciliation: Literal["not_available", "aligned", "blocked"] = "not_available"
    coverage_assessment: CoverageAssessment | None = None
    graph_lineage: GraphLineage | None = None
    epistemic_context: EpistemicContext | None = None
    shadow_preview: ShadowPreview | None = None
    runtime_reconciliation: RuntimeReconciliation | None = None
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
    semantic = None
    semantic_reconciliation: Literal["not_available", "aligned", "blocked"] = "not_available"
    if composition is not None and isinstance(composition.get("composition_provenance"), dict):
        provenance = composition["composition_provenance"]
        assert isinstance(provenance, dict)
        raw_semantic = provenance.get("semantic_selection")
        if isinstance(raw_semantic, dict):
            semantic = SemanticSelection.model_validate(raw_semantic)
            semantic_reconciliation = "blocked" if semantic.conflicts else "aligned"

    if epistemic is not None and state.lifecycle.epistemic_context_schema_version is not None:
        if state.lifecycle.epistemic_context_schema_version != epistemic.schema_version:
            raise ValueError("deliverable lifecycle epistemic schema does not match composition context")
        if state.lifecycle.epistemic_freshness != epistemic.freshness:
            raise ValueError("deliverable lifecycle epistemic freshness does not match composition context")
        if state.lifecycle.epistemic_contradiction_status != epistemic.contradiction_status:
            raise ValueError("deliverable lifecycle epistemic contradiction state does not match composition context")
        if state.lifecycle.epistemic_missing_evidence != epistemic.missing_evidence:
            raise ValueError("deliverable lifecycle epistemic evidence does not match composition context")
        if state.lifecycle.epistemic_budget_status != epistemic.budget_status:
            raise ValueError("deliverable lifecycle epistemic budget status does not match composition context")
        if state.lifecycle.epistemic_budget_excesses != epistemic.budget_excesses:
            raise ValueError("deliverable lifecycle epistemic budget excesses do not match composition context")
        if state.lifecycle.epistemic_source_classes != epistemic.source_classes:
            raise ValueError("deliverable lifecycle epistemic sources do not match composition context")
        if state.lifecycle.epistemic_confidence != epistemic.confidence:
            raise ValueError("deliverable lifecycle epistemic confidence does not match composition context")
        if state.lifecycle.epistemic_confidence_semantics != epistemic.confidence_semantics:
            raise ValueError("deliverable lifecycle epistemic confidence semantics do not match composition context")
        if state.lifecycle.epistemic_confidence_basis != epistemic.confidence_basis:
            raise ValueError("deliverable lifecycle epistemic confidence basis does not match composition context")
        if state.lifecycle.epistemic_required_evidence != epistemic.required_evidence:
            raise ValueError("deliverable lifecycle epistemic required evidence does not match composition context")

    if state.lifecycle.coverage_assessment is not None:
        if coverage is None:
            raise ValueError("deliverable lifecycle coverage is missing from composition context")
        if state.lifecycle.coverage_assessment != coverage:
            raise ValueError("deliverable lifecycle coverage does not match composition context")

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
        epistemic_reconciliation=state.lifecycle.epistemic_reconciliation,
        epistemic_missing_evidence=state.lifecycle.epistemic_missing_evidence,
        epistemic_budget_status=state.lifecycle.epistemic_budget_status,
        epistemic_budget_excesses=state.lifecycle.epistemic_budget_excesses,
        epistemic_source_classes=state.lifecycle.epistemic_source_classes,
        epistemic_confidence=state.lifecycle.epistemic_confidence,
        epistemic_confidence_semantics=state.lifecycle.epistemic_confidence_semantics,
        epistemic_confidence_basis=state.lifecycle.epistemic_confidence_basis,
        epistemic_required_evidence=state.lifecycle.epistemic_required_evidence,
        semantic_selection=semantic,
        semantic_reconciliation=semantic_reconciliation,
        coverage_assessment=coverage,
        graph_lineage=state.lifecycle.graph_lineage,
        epistemic_context=epistemic,
        shadow_preview=state.shadow_preview,
        runtime_reconciliation=state.runtime_reconciliation,
    )

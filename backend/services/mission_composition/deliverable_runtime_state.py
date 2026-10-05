"""Durable, non-authoritative mission metadata for requested deliverables.

This module serializes the interpreted deliverable request and its structural
artifact projection so runtime can evaluate materialized outputs without
reinterpreting the original instruction. The envelope grants no execution
authority and does not claim that any artifact has been produced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.mission_composition.contracts import (
    CoverageAssessment,
    EpistemicBudgetStatus,
    EpistemicContext,
    EpistemicContradictionStatus,
    EpistemicFreshness,
    GraphLineage,
)
from backend.services.mission_composition.deliverable_contract import DeliverableRequest
from backend.services.mission_composition.deliverable_projection import (
    DeliverableProjection,
    project_deliverable_request,
)
from backend.services.mission_composition.shadow_preview import RuntimeReconciliation, ShadowPreview
from backend.services.mission_composition.vertical_know_how import (
    REVOPS_V1_KNOW_HOW,
    VerticalKnowHowContract,
)

DELIVERABLE_RUNTIME_STATE_METADATA_KEY = "deliverable_runtime_state"

DeliverableLifecycleState = Literal[
    "planned",
    "current",
    "incomplete",
    "stale",
    "contradictory",
    "superseded",
    "archived",
]


class DeliverableArtifactLifecycle(BaseModel):
    """Persisted, non-authoritative lifecycle for materialized deliverables."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    state: DeliverableLifecycleState = "planned"
    observed_at: datetime | None = None
    reconciled_at: datetime | None = None
    freshness_window_seconds: int | None = Field(default=86_400, ge=0, le=31_536_000)
    materialized_artifact_count: int = Field(default=0, ge=0)
    contradiction_codes: tuple[str, ...] = ()
    supersedes_artifact_id: str | None = None
    epistemic_context_schema_version: int | None = Field(default=None, ge=1)
    # Read-only lineage snapshots explaining what knowledge informed the artifact.
    epistemic_source_classes: tuple[str, ...] = ()
    epistemic_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    epistemic_confidence_semantics: str | None = None
    epistemic_confidence_basis: tuple[str, ...] = ()
    epistemic_required_evidence: tuple[str, ...] = ()
    epistemic_freshness: EpistemicFreshness | None = None
    epistemic_contradiction_status: EpistemicContradictionStatus | None = None
    epistemic_missing_evidence: tuple[str, ...] = ()
    epistemic_budget_status: EpistemicBudgetStatus = "within_budget"
    epistemic_budget_excesses: tuple[str, ...] = ()
    epistemic_reconciliation: Literal["not_available", "aligned", "blocked"] = "not_available"
    # Snapshot composition applicability in the same lineage envelope as the
    # materialized deliverable; this does not grant runtime authority.
    coverage_assessment: CoverageAssessment | None = None
    graph_lineage: GraphLineage = Field(default_factory=GraphLineage)
    grants_execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_lineage(self) -> DeliverableArtifactLifecycle:
        if self.state == "superseded" and not self.supersedes_artifact_id:
            raise ValueError("superseded deliverable requires supersedes_artifact_id")
        if self.state != "contradictory" and self.contradiction_codes:
            raise ValueError("contradiction codes require contradictory deliverable state")
        return self

    def effective_state(self, *, now: datetime | None = None) -> DeliverableLifecycleState:
        """Return stale when a current observation exceeds its freshness window."""

        if self.state != "current" or self.observed_at is None or self.freshness_window_seconds is None:
            return self.state
        current = now or datetime.now(UTC)
        observed = self.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return "stale" if current > observed + timedelta(seconds=self.freshness_window_seconds) else "current"


class DeliverableRuntimeState(BaseModel):
    """Persistable semantic/projection state required for runtime evaluation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    request: DeliverableRequest
    projection: DeliverableProjection
    completion: dict[str, object] | None = None
    shadow_preview: ShadowPreview | None = None
    runtime_reconciliation: RuntimeReconciliation | None = None
    lifecycle: DeliverableArtifactLifecycle = Field(default_factory=DeliverableArtifactLifecycle)
    grants_execution_authority: Literal[False] = False


def build_deliverable_runtime_state(
    request: DeliverableRequest | None,
    *,
    coverage_assessment: CoverageAssessment | None = None,
    epistemic_context: EpistemicContext | None = None,
    know_how: VerticalKnowHowContract = REVOPS_V1_KNOW_HOW,
    minimum_rows: int = 0,
    minimum_rows_by_artifact: dict[str, int] | None = None,
    shadow_preview: ShadowPreview | None = None,
    graph_lineage: GraphLineage | None = None,
) -> dict[str, object] | None:
    """Build JSON-safe durable state from the canonical interpreted request."""

    if request is None:
        return None
    epistemic_reconciliation: Literal["not_available", "aligned", "blocked"] = "not_available"
    if epistemic_context is not None:
        epistemic_reconciliation = (
            "blocked"
            if (
                epistemic_context.contradiction_status == "unresolved"
                or epistemic_context.missing_evidence
                or epistemic_context.budget_status == "exceeded"
            )
            else "aligned"
        )
    state = DeliverableRuntimeState(
        request=request,
        projection=project_deliverable_request(
            request,
            know_how=know_how,
            minimum_rows=minimum_rows,
            minimum_rows_by_artifact=minimum_rows_by_artifact,
        ),
        shadow_preview=shadow_preview,
        lifecycle=DeliverableArtifactLifecycle(
            epistemic_context_schema_version=(epistemic_context.schema_version if epistemic_context else None),
            epistemic_source_classes=(epistemic_context.source_classes if epistemic_context else ()),
            epistemic_confidence=(epistemic_context.confidence if epistemic_context else None),
            epistemic_confidence_semantics=(epistemic_context.confidence_semantics if epistemic_context else None),
            epistemic_confidence_basis=(epistemic_context.confidence_basis if epistemic_context else ()),
            epistemic_required_evidence=(epistemic_context.required_evidence if epistemic_context else ()),
            epistemic_freshness=(epistemic_context.freshness if epistemic_context else None),
            epistemic_contradiction_status=(epistemic_context.contradiction_status if epistemic_context else None),
            epistemic_missing_evidence=(epistemic_context.missing_evidence if epistemic_context else ()),
            epistemic_budget_status=(epistemic_context.budget_status if epistemic_context else "within_budget"),
            epistemic_budget_excesses=(epistemic_context.budget_excesses if epistemic_context else ()),
            epistemic_reconciliation=epistemic_reconciliation,
            coverage_assessment=coverage_assessment,
            graph_lineage=graph_lineage or GraphLineage(),
        ),
    )
    return state.model_dump(mode="json")


def load_deliverable_runtime_state(raw: object) -> DeliverableRuntimeState | None:
    """Load durable state fail closed; callers decide how to surface invalid metadata."""

    if raw is None:
        return None
    return DeliverableRuntimeState.model_validate(raw)

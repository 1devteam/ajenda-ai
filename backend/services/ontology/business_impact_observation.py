"""Observational business-impact evidence: never a Decision recommendation or intervention."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.ontology.commercial_state import KpiSemanticSignature
from backend.services.ontology.decision_feedback import DecisionEpisodeReference
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.outcome import AttributionAssessment, KpiOutcomeDelta, OutcomeStatus
from backend.services.ontology.types import BusinessObjectRef


class BusinessImpactObservation(BaseModel):
    """A source-bound impact observation with no recommendation/execution claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    observation_class: Literal["observational_business_impact"] = "observational_business_impact"
    signal_id: str = Field(min_length=1, max_length=160)
    episode_reference: DecisionEpisodeReference
    selected_candidate_response_key: str = Field(min_length=1, max_length=160)
    baseline_measurement_id: UUID
    observed_measurement_id: UUID
    baseline_source_kind: Literal["customer_attested", "source_verified"]
    observed_source_kind: Literal["customer_attested", "source_verified"]
    goal_id: str | None = None
    subject_refs: tuple[BusinessObjectRef, ...] = ()
    kpi_semantic_signatures: tuple[KpiSemanticSignature, ...] = ()
    kpi_deltas: tuple[KpiOutcomeDelta, ...] = ()
    outcome_evaluation_id: str
    outcome_status: OutcomeStatus
    measured_outcome_attribution: AttributionAssessment
    observation_verification_basis: ObservationVerificationBasis
    observed_at: datetime
    evaluated_at: datetime
    execution_status: Literal["unknown"] = "unknown"
    limitations: tuple[str, ...] = (
        "selected_response_is_strategy_provenance_only",
        "strategy_execution_not_established",
        "observed_change_does_not_establish_intervention_effectiveness",
        "measurement_source_trust_is_distinct_from_timestamp_verification",
    )
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False

    @model_validator(mode="after")
    def validate_observational_scope(self) -> BusinessImpactObservation:
        if self.episode_reference.episode_kind != "business_impact":
            raise ValueError("business impact observation requires business-impact episode provenance")
        provenance = self.episode_reference.business_impact_provenance
        if (
            not isinstance(provenance, dict)
            or provenance.get("baseline_measurement_id") != str(self.baseline_measurement_id)
            or provenance.get("observed_measurement_id") != str(self.observed_measurement_id)
            or provenance.get("outcome_evaluation_id") != self.outcome_evaluation_id
        ):
            raise ValueError("business impact observation contradicts canonical episode provenance")
        return self

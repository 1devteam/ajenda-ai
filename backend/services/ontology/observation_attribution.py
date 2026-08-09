"""Observation & Attribution Integrity Slice 1.

Resolves outcome chronology from explicit provenance and earns a bounded,
non-causal attribution assessment from structured evidence. This module does
not verify an external source, infer causation, persist artifacts, or execute
work.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OBSERVATION_ATTRIBUTION_SCHEMA_VERSION = 1


class ObservationTimeProvenance(StrEnum):
    SOURCE_VERIFIED = "source_verified"
    DERIVED = "derived"
    CALLER_ASSERTED = "caller_asserted"
    UNKNOWN = "unknown"


class AttributionAssessment(StrEnum):
    """Bounded non-causal attribution of observed change to an action."""

    NOT_ASSESSED = "not_assessed"
    TEMPORAL_ASSOCIATION = "temporal_association"
    SUPPORTED_CONTRIBUTION = "supported_contribution"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AttributionOrdering(StrEnum):
    VERIFIED_AFTER_EXECUTION = "verified_after_execution"
    DERIVED_AFTER_EXECUTION = "derived_after_execution"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


def _require_aware(value: datetime | None, field_name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must include timezone information")
    return value


class ObservationTiming(BaseModel):
    """Resolved observation chronology with the provenance kept visible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    source_observed_at: datetime | None = None
    captured_at: datetime | None = None
    asserted_observed_at: datetime | None = None
    resolved_observed_at: datetime | None = None
    provenance: ObservationTimeProvenance = ObservationTimeProvenance.UNKNOWN
    explanation_codes: tuple[str, ...] = ()

    @field_validator(
        "source_observed_at",
        "captured_at",
        "asserted_observed_at",
        "resolved_observed_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None, info: object) -> datetime | None:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_aware(value, field_name)

    @model_validator(mode="after")
    def validate_resolution(self) -> ObservationTiming:
        expected: datetime | None
        if self.provenance == ObservationTimeProvenance.SOURCE_VERIFIED:
            expected = self.source_observed_at
        elif self.provenance == ObservationTimeProvenance.DERIVED:
            if self.source_observed_at is not None:
                raise ValueError("derived chronology cannot ignore source_observed_at")
            expected = self.captured_at
        elif self.provenance == ObservationTimeProvenance.CALLER_ASSERTED:
            if self.source_observed_at is not None or self.captured_at is not None:
                raise ValueError("caller-asserted chronology cannot ignore a stronger timestamp")
            expected = self.asserted_observed_at
        else:
            if any((self.source_observed_at, self.captured_at, self.asserted_observed_at)):
                raise ValueError("unknown chronology cannot contain an observation timestamp")
            expected = None
        if expected is None and self.provenance != ObservationTimeProvenance.UNKNOWN:
            raise ValueError(f"{self.provenance.value} chronology requires its timestamp")
        if self.resolved_observed_at != expected:
            raise ValueError("resolved_observed_at must match the strongest available chronology")
        return self


class AttributionEvidenceInput(BaseModel):
    """Structured evidence considered by the deterministic attribution evaluator."""

    model_config = ConfigDict(extra="forbid")

    executed_at: datetime | None = None
    execution_evidence_ids: list[str] = Field(default_factory=list)
    expected_change_dimensions: list[str] = Field(default_factory=list)
    observed_change_dimensions: list[str] = Field(default_factory=list)
    competing_explanations: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)

    @field_validator("executed_at")
    @classmethod
    def require_execution_timezone(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value, "executed_at")

    @field_validator(
        "execution_evidence_ids",
        "expected_change_dimensions",
        "observed_change_dimensions",
        "competing_explanations",
        "conflicting_evidence_ids",
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item:
                raise ValueError("attribution evidence list entries must be non-empty")
            if item not in normalized:
                normalized.append(item)
        return normalized


def _derive_attribution(
    *,
    evidence: AttributionEvidenceInput,
    observation_timing: ObservationTiming,
) -> tuple[AttributionOrdering, list[str], AttributionAssessment, list[str]]:
    codes: list[str] = []
    observed_at = observation_timing.resolved_observed_at
    if (
        evidence.executed_at is None
        or observed_at is None
        or observation_timing.provenance
        in {ObservationTimeProvenance.CALLER_ASSERTED, ObservationTimeProvenance.UNKNOWN}
    ):
        ordering = AttributionOrdering.UNVERIFIABLE
        codes.append("chronology_unverifiable")
    elif observed_at < evidence.executed_at:
        ordering = AttributionOrdering.CONTRADICTED
        codes.append("observation_precedes_execution")
    elif observation_timing.provenance == ObservationTimeProvenance.DERIVED:
        ordering = AttributionOrdering.DERIVED_AFTER_EXECUTION
        codes.append("derived_capture_follows_execution")
    else:
        ordering = AttributionOrdering.VERIFIED_AFTER_EXECUTION
        codes.append("execution_precedes_observation")

    expected = {item.casefold() for item in evidence.expected_change_dimensions}
    observed = {item.casefold() for item in evidence.observed_change_dimensions}
    matching = sorted(expected & observed)

    if evidence.conflicting_evidence_ids or ordering == AttributionOrdering.CONTRADICTED:
        resulting = AttributionAssessment.CONFLICTING_EVIDENCE
        codes.append("conflicting_attribution_evidence")
    elif not evidence.execution_evidence_ids:
        resulting = AttributionAssessment.INSUFFICIENT_EVIDENCE
        codes.append("execution_evidence_missing")
    elif ordering == AttributionOrdering.UNVERIFIABLE:
        resulting = AttributionAssessment.INSUFFICIENT_EVIDENCE
        codes.append("unverifiable_chronology_blocks_contribution")
    elif not expected or not observed:
        resulting = AttributionAssessment.INSUFFICIENT_EVIDENCE
        codes.append("expected_or_observed_dimensions_missing")
    elif not matching:
        resulting = AttributionAssessment.INSUFFICIENT_EVIDENCE
        codes.append("expected_observed_dimensions_do_not_match")
    elif ordering == AttributionOrdering.DERIVED_AFTER_EXECUTION:
        resulting = AttributionAssessment.TEMPORAL_ASSOCIATION
        codes.append("derived_chronology_caps_at_temporal_association")
    elif evidence.competing_explanations:
        resulting = AttributionAssessment.TEMPORAL_ASSOCIATION
        codes.append("competing_explanations_cap_at_temporal_association")
    elif evidence.confidence < 0.7:
        resulting = AttributionAssessment.TEMPORAL_ASSOCIATION
        codes.append("confidence_below_supported_contribution_threshold")
    else:
        resulting = AttributionAssessment.SUPPORTED_CONTRIBUTION
        codes.extend(["execution_evidence_present", "expected_observed_dimensions_match"])

    codes.append("non_causal_attribution_only")
    return ordering, matching, resulting, list(dict.fromkeys(codes))


class AttributionAssessmentEvidence(BaseModel):
    """Immutable explanation of the non-causal attribution level earned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    execution_evidence_ids: tuple[str, ...] = ()
    executed_at: datetime | None = None
    observation_timing: ObservationTiming
    ordering: AttributionOrdering
    expected_change_dimensions: tuple[str, ...] = ()
    observed_change_dimensions: tuple[str, ...] = ()
    matching_dimensions: tuple[str, ...] = ()
    competing_explanations: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    explanation_codes: tuple[str, ...] = ()
    resulting_attribution: AttributionAssessment
    causal_claim: Literal[False] = False
    algorithm: str = "attribution_evidence_v1"

    @field_validator("executed_at")
    @classmethod
    def require_execution_timezone(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value, "executed_at")

    @model_validator(mode="after")
    def validate_deterministic_result(self) -> AttributionAssessmentEvidence:
        evidence = AttributionEvidenceInput(
            executed_at=self.executed_at,
            execution_evidence_ids=list(self.execution_evidence_ids),
            expected_change_dimensions=list(self.expected_change_dimensions),
            observed_change_dimensions=list(self.observed_change_dimensions),
            competing_explanations=list(self.competing_explanations),
            conflicting_evidence_ids=list(self.conflicting_evidence_ids),
            confidence=self.confidence,
        )
        ordering, matching, resulting, codes = _derive_attribution(
            evidence=evidence,
            observation_timing=self.observation_timing,
        )
        if self.ordering != ordering:
            raise ValueError("ordering must match deterministic attribution evaluation")
        if self.matching_dimensions != tuple(matching):
            raise ValueError("matching_dimensions must match deterministic attribution evaluation")
        if self.resulting_attribution != resulting:
            raise ValueError("resulting_attribution must match deterministic attribution evaluation")
        if self.explanation_codes != tuple(codes):
            raise ValueError("explanation_codes must match deterministic attribution evaluation")
        return self


def resolve_observation_timing(
    *,
    source_observed_at: datetime | None = None,
    captured_at: datetime | None = None,
    asserted_observed_at: datetime | None = None,
) -> ObservationTiming:
    """Choose the strongest explicit chronology without treating capture as source truth."""

    source_observed_at = _require_aware(source_observed_at, "source_observed_at")
    captured_at = _require_aware(captured_at, "captured_at")
    asserted_observed_at = _require_aware(asserted_observed_at, "asserted_observed_at")
    if source_observed_at is not None:
        provenance = ObservationTimeProvenance.SOURCE_VERIFIED
        resolved = source_observed_at
        codes = ["source_observation_time_selected"]
    elif captured_at is not None:
        provenance = ObservationTimeProvenance.DERIVED
        resolved = captured_at
        codes = ["capture_time_used_as_derived_observation_bound"]
    elif asserted_observed_at is not None:
        provenance = ObservationTimeProvenance.CALLER_ASSERTED
        resolved = asserted_observed_at
        codes = ["caller_asserted_observation_time_selected"]
    else:
        provenance = ObservationTimeProvenance.UNKNOWN
        resolved = None
        codes = ["observation_time_unknown"]
    return ObservationTiming(
        source_observed_at=source_observed_at,
        captured_at=captured_at,
        asserted_observed_at=asserted_observed_at,
        resolved_observed_at=resolved,
        provenance=provenance,
        explanation_codes=tuple(codes),
    )


def evaluate_attribution_evidence(
    *,
    evidence: AttributionEvidenceInput,
    observation_timing: ObservationTiming,
) -> AttributionAssessmentEvidence:
    """Earn attribution from evidence; temporal association never becomes causation."""

    ordering, matching, resulting, codes = _derive_attribution(
        evidence=evidence,
        observation_timing=observation_timing,
    )
    return AttributionAssessmentEvidence(
        execution_evidence_ids=tuple(evidence.execution_evidence_ids),
        executed_at=evidence.executed_at,
        observation_timing=observation_timing,
        ordering=ordering,
        expected_change_dimensions=tuple(evidence.expected_change_dimensions),
        observed_change_dimensions=tuple(evidence.observed_change_dimensions),
        matching_dimensions=tuple(matching),
        competing_explanations=tuple(evidence.competing_explanations),
        conflicting_evidence_ids=tuple(evidence.conflicting_evidence_ids),
        confidence=evidence.confidence,
        explanation_codes=tuple(codes),
        resulting_attribution=resulting,
    )

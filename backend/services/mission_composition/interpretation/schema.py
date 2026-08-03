"""Strict model-output contract for mission-language interpretation.

The model may normalize language and identify canonical mission facts. It may
not select abilities, grant permissions, create runtime state, or authorize
side effects. Every material interpretation is grounded in source text so the
backend can fail closed before Ajenda's deterministic composition layers run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.mission_composition.contracts import (
    CanonicalOutcome,
    RiskLevel,
    SemanticUnitKind,
    SendPolicyCondition,
    SendPolicyMode,
)

INTERPRETATION_OUTPUT_SCHEMA_VERSION = 1

TargetType = Literal["market", "company", "person", "contact", "recipient", "competitor_set", "email"]
ContextRequirementKey = Literal["hubspot_source"]


class GroundedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: CanonicalOutcome
    source_text: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: SendPolicyMode = "unknown"
    condition: SendPolicyCondition = "none"
    source_text: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _source_required_for_material_policy(self) -> GroundedPolicy:
        if self.mode != "unknown" and not (self.source_text or "").strip():
            raise ValueError("source_text is required for a material policy")
        if self.mode == "forbid" and self.condition != "none":
            raise ValueError("forbid policy must use condition=none")
        if self.mode == "allow" and self.condition != "none":
            raise ValueError("allow policy must use condition=none")
        return self


class GroundedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TargetType
    source_text: str = Field(min_length=1, max_length=1000)
    source: Literal["instruction", "profile_context"] = "instruction"
    industry: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=240)
    radius_km: float | None = Field(default=None, ge=0)
    domain: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=2048)
    email: str | None = Field(default=None, max_length=320)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedTimingConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["absolute_window", "relative", "after_job", "after_approval"] = "absolute_window"
    source_text: str = Field(min_length=1, max_length=1000)
    start: str | None = Field(default=None, max_length=80)
    end: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=240)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedUnsupportedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedContextRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: ContextRequirementKey
    source_text: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroundedSuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=1000)
    measurable: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class InterpretationSegment(BaseModel):
    """One exact source span and how the model accounted for it."""

    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(min_length=1, max_length=2000)
    normalized_text: str = Field(min_length=1, max_length=2000)
    kind: SemanticUnitKind = "other"
    material: bool = True
    accounted: bool = False
    mapped_outcomes: list[CanonicalOutcome] = Field(default_factory=list, max_length=10)
    risk: RiskLevel = "low"
    reason: str | None = Field(default=None, max_length=500)


class InterpretationClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)


class InterpretationContradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=160)
    first_span: str = Field(min_length=1, max_length=500)
    second_span: str = Field(min_length=1, max_length=500)
    first_value: str = Field(min_length=1, max_length=240)
    second_value: str = Field(min_length=1, max_length=240)
    risk: RiskLevel = "high"


class LlmMissionInterpretation(BaseModel):
    """Untrusted, schema-constrained interpretation returned by the local LLM."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    interpreted_instruction: str = Field(min_length=1, max_length=8000)
    requested_outcomes: list[GroundedOutcome] = Field(default_factory=list, max_length=30)
    unsupported_outcomes: list[GroundedUnsupportedOutcome] = Field(default_factory=list, max_length=20)
    requested_quantity: int | None = Field(default=None, ge=1, le=100)
    quantity_source_text: str | None = Field(default=None, max_length=1000)
    send_policy: GroundedPolicy = Field(default_factory=GroundedPolicy)
    contact_policy: GroundedPolicy = Field(default_factory=GroundedPolicy)
    publish_policy: GroundedPolicy = Field(default_factory=GroundedPolicy)
    write_policy: GroundedPolicy = Field(default_factory=GroundedPolicy)
    target_entities: list[GroundedTarget] = Field(default_factory=list, max_length=20)
    timing_constraints: list[GroundedTimingConstraint] = Field(default_factory=list, max_length=10)
    constraints: list[GroundedConstraint] = Field(default_factory=list, max_length=30)
    forbidden_outcomes: list[GroundedOutcome] = Field(default_factory=list, max_length=30)
    success_criteria: list[GroundedSuccessCriterion] = Field(default_factory=list, max_length=20)
    urgency: Literal["normal"] = "normal"
    approval_preference: Literal["review_before_external_action"] = "review_before_external_action"
    context_requirements: list[GroundedContextRequirement] = Field(default_factory=list, max_length=20)
    clarifications: list[InterpretationClarification] = Field(default_factory=list, max_length=20)
    segments: list[InterpretationSegment] = Field(min_length=1, max_length=60)
    contradictions: list[InterpretationContradiction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _cross_field_invariants(self) -> LlmMissionInterpretation:
        requested = [item.outcome for item in self.requested_outcomes]
        forbidden = [item.outcome for item in self.forbidden_outcomes]
        if len(requested) != len(set(requested)):
            raise ValueError("requested_outcomes must be unique")
        if len(forbidden) != len(set(forbidden)):
            raise ValueError("forbidden_outcomes must be unique")
        overlap = set(requested) & set(forbidden)
        if overlap:
            raise ValueError(f"outcomes cannot be both requested and forbidden: {sorted(overlap)}")
        if self.requested_quantity is not None and not (self.quantity_source_text or "").strip():
            raise ValueError("quantity_source_text is required when requested_quantity is set")
        unsupported = [item.text.strip().casefold() for item in self.unsupported_outcomes]
        if len(unsupported) != len(set(unsupported)):
            raise ValueError("unsupported_outcomes must be unique")
        requirements = [item.requirement for item in self.context_requirements]
        if len(requirements) != len(set(requirements)):
            raise ValueError("context_requirements must be unique")
        return self

"""Commercial State / Goal / KPI Ontology — Slice 2.

Answers: what state is a business object in, what outcome are we driving,
how is progress measured, and what changed.

Distinct from Slice 1 identities (Account, Opportunity, …):

- Goal — desired business outcome (direction of change)
- KPI — measurable indicator attached to a Goal
- BusinessStateSnapshot — point-in-time believed state of a subject
- BusinessEvent — something that changed or may have changed state

Hard separations (do not collapse):

- Evidence is not state (source-backed claim vs operating representation)
- Event is not state (what happened vs where we are)
- KPI is not evidence (measurement vs proving claim)
- Goal is not a business object identity (desired change vs entity)

Does not: optimize KPIs, auto-mutate goals, execute recommendations,
ingest runtime events, or introduce a graph database.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.ontology.types import BusinessObjectRef, OntologyRelationshipSpec

COMMERCIAL_STATE_SCHEMA_VERSION = 1


class GoalStatus(StrEnum):
    """Lifecycle of a desired outcome."""

    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class KpiDirection(StrEnum):
    """How movement of the metric relates to goal success."""

    INCREASE = "increase"
    DECREASE = "decrease"
    MAINTAIN = "maintain"


class Goal(BaseModel):
    """A desired business outcome — direction of change, not an identity object.

    subject_refs name which business objects the goal concerns (e.g. an
    Opportunity). status is lifecycle only; progress lives on KPIs / evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    goal_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    status: GoalStatus = GoalStatus.ACTIVE
    target_date: date | None = Field(
        default=None,
        description="Optional calendar target (ISO-8601 date strings accepted)",
    )

    @field_validator("goal_id", "name")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("goal fields must be non-empty")
        return normalized


class Kpi(BaseModel):
    """Measurable indicator attached to a Goal.

    current_value / target_value are optional so a KPI can be declared before
    the first measurement. direction defines what "better" means for algorithms.
    required marks contribution to goal progress aggregation.
    maintain_tolerance is used only when direction=maintain.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kpi_id: str = Field(min_length=1, max_length=160)
    goal_id: str = Field(min_length=1, max_length=160, description="Owning Goal.goal_id")
    name: str = Field(min_length=1, max_length=240)
    metric: str = Field(
        min_length=1,
        max_length=160,
        description="Stable metric key, e.g. qualification_score, reply_rate",
    )
    direction: KpiDirection = KpiDirection.INCREASE
    target_value: float | None = None
    current_value: float | None = None
    previous_value: float | None = Field(
        default=None,
        description="Optional prior measurement for change delta in evaluation",
    )
    unit: str = Field(default="", max_length=40)
    required: bool = Field(
        default=True,
        description="Whether this KPI participates as required for goal progress status",
    )
    maintain_tolerance: float | None = Field(
        default=None,
        ge=0,
        description="Absolute tolerance around target when direction=maintain",
    )

    @field_validator("kpi_id", "goal_id", "name", "metric")
    @classmethod
    def normalize_required_str(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("kpi fields must be non-empty")
        return normalized


class BusinessStateSnapshot(BaseModel):
    """Point-in-time operating representation of a subject.

    Not system-of-record truth and not evidence. attributes hold reasoned or
    projected fields (stage, scores, flags). evidence_ids cite supporting
    EvidenceFact / EvidenceItem identities without embedding claims.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(min_length=1, max_length=160)
    subject_ref: BusinessObjectRef
    captured_at: datetime = Field(
        description="When this representation was formed (ISO-8601 datetime accepted)",
    )
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Opaque evidence identities supporting attributes",
    )
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("snapshot_id")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("snapshot fields must be non-empty")
        return normalized


class BusinessEvent(BaseModel):
    """Something that changed or may have changed business state.

    Generalizes the idea behind light_crm Activity without replacing CRM
    activity storage. evidence_ids prove the event; structured payload carries
    event-specific fields. Does not itself update a BusinessStateSnapshot.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "Stable type key; may align with light_crm ActivityType "
            "(email_sent, stage_changed, …) or broader vocabulary"
        ),
    )
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    occurred_at: datetime = Field(description="When the event occurred (ISO-8601 accepted)")
    evidence_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="", max_length=1000)

    @field_validator("event_id", "event_type")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event fields must be non-empty")
        return normalized


# Declarative cross-type relationships (typed). Not a graph runtime.
COMMERCIAL_RELATIONSHIP_SPECS: tuple[OntologyRelationshipSpec, ...] = (
    OntologyRelationshipSpec(
        name="goal_concerns_subjects",
        from_endpoint="Goal",
        to_endpoint="BusinessObjectRef",
        cardinality="many_to_many",
        description="A goal may name one or more business objects as subjects.",
    ),
    OntologyRelationshipSpec(
        name="kpi_belongs_to_goal",
        from_endpoint="Kpi",
        to_endpoint="Goal",
        cardinality="many_to_one",
        description="Each KPI is owned by exactly one Goal via goal_id.",
    ),
    OntologyRelationshipSpec(
        name="snapshot_of_subject",
        from_endpoint="BusinessStateSnapshot",
        to_endpoint="BusinessObjectRef",
        cardinality="many_to_one",
        description="A snapshot describes one subject at one captured_at.",
    ),
    OntologyRelationshipSpec(
        name="event_involves_subjects",
        from_endpoint="BusinessEvent",
        to_endpoint="BusinessObjectRef",
        cardinality="many_to_many",
        description="An event may involve one or more business objects.",
    ),
    OntologyRelationshipSpec(
        name="snapshot_supported_by_evidence",
        from_endpoint="BusinessStateSnapshot",
        to_endpoint="Evidence",
        cardinality="many_to_many",
        description="State attributes may cite evidence ids; evidence is not state.",
    ),
    OntologyRelationshipSpec(
        name="event_supported_by_evidence",
        from_endpoint="BusinessEvent",
        to_endpoint="Evidence",
        cardinality="many_to_many",
        description="Events may cite evidence ids proving occurrence; event is not evidence.",
    ),
)

"""Mission Composition Engine contracts (ADR-0008).

These models describe interpretation and planning only. They do not grant
runtime execution authority, queue work, claim leases, or invoke tools.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COMPOSITION_SCHEMA_VERSION = 3
JOB_CATALOG_VERSION = "8"
INTERPRETER_VERSION = "9"
CAPABILITY_RESOLVER_VERSION = "7"

ProposalStatus = Literal[
    "interpretation_failed",
    "interpretation_ready",
    "composition_blocked",
    "connection_required",
    "charter_blocked",
    "proposal_ready",
    "superseded",
    "confirmed",
]
DependencyKind = Literal["hard", "conditional", "optional"]
SemanticUnitKind = Literal[
    "action",
    "target",
    "quantity",
    "location",
    "time",
    "side_effect",
    "approval",
    "prohibition",
    "correction",
    "recipient",
    "deliverable",
    "other",
]
RiskLevel = Literal["low", "medium", "high", "critical"]

JobRiskLevel = Literal["low", "medium", "high", "critical"]
JobMaturity = Literal["runtime_bound", "catalog_only"]
ReadinessStatus = Literal[
    "ready",
    "connection_required",
    "charter_blocked",
    "catalog_only",
    "unavailable",
    "permission_required",
]
SelectionStatus = Literal["selected", "alternative", "rejected"]

# Canonical business outcomes owned by the interpreter → job catalog boundary.
CanonicalOutcome = Literal[
    "research_prospects",
    "observe_contacts",
    "qualify_prospects",
    "enrich_contacts",
    "prepare_outreach",
    "send_outreach",
    "update_crm",
    "publish_content",
    "read_calendar",
    "read_email",
    "read_crm",
    "query_salesforce",
    "read_linkedin",
    "read_github",
    "read_contacts",
]

CANONICAL_OUTCOMES: frozenset[str] = frozenset(
    {
        "research_prospects",
        "observe_contacts",
        "qualify_prospects",
        "enrich_contacts",
        "prepare_outreach",
        "send_outreach",
        "update_crm",
        "publish_content",
        "read_calendar",
        "read_email",
        "read_crm",
        "query_salesforce",
        "read_linkedin",
        "read_github",
        "read_contacts",
    }
)

# Legacy phrase → canonical ID (compatibility for in-flight records / older tests).
LEGACY_OUTCOME_ALIASES: dict[str, CanonicalOutcome] = {
    "research prospects": "research_prospects",
    "discover companies": "research_prospects",
    "find leads": "research_prospects",
    "prospect discovery": "research_prospects",
    "market research": "research_prospects",
    "qualify prospects": "qualify_prospects",
    "identify strong prospects": "qualify_prospects",
    "score leads": "qualify_prospects",
    "score them": "qualify_prospects",
    "score the prospects": "qualify_prospects",
    "score competitors": "qualify_prospects",
    "rank them": "qualify_prospects",
    "rate them": "qualify_prospects",
    "grade them": "qualify_prospects",
    "qualification": "qualify_prospects",
    "strongest prospects": "qualify_prospects",
    "enrich contacts": "enrich_contacts",
    "enrich leads": "enrich_contacts",
    "lead enrichment": "enrich_contacts",
    "collect contact info": "observe_contacts",
    "collect contacts": "observe_contacts",
    "collect contact details": "observe_contacts",
    "contact info": "observe_contacts",
    "contact details": "observe_contacts",
    "return the contact info": "observe_contacts",
    "return contact info": "observe_contacts",
    "draft introductions": "prepare_outreach",
    "draft emails": "prepare_outreach",
    "personalized introductions": "prepare_outreach",
    "outreach preparation": "prepare_outreach",
    "prepare drafts": "prepare_outreach",
    "send emails": "send_outreach",
    "send introductions": "send_outreach",
    "deliver outreach": "send_outreach",
    "log activity": "update_crm",
    "upsert crm": "update_crm",
    "pipeline update": "update_crm",
    "add to contacts": "update_crm",
    "save to contacts": "update_crm",
    "add contacts": "update_crm",
    "calendar briefing": "read_calendar",
    "read calendar": "read_calendar",
    "schedule review": "read_calendar",
    "google calendar": "read_calendar",
    "what is scheduled": "read_calendar",
    "my schedule": "read_calendar",
    "check gmail": "read_email",
    "read email": "read_email",
    "check inbox": "read_email",
    "search email": "read_email",
    "read hubspot": "read_crm",
    "search hubspot": "read_crm",
    "check crm": "read_crm",
    "read crm": "read_crm",
    "query salesforce": "query_salesforce",
    "read salesforce": "query_salesforce",
    "search salesforce": "query_salesforce",
    "read linkedin": "read_linkedin",
    "linkedin profile": "read_linkedin",
    "my linkedin": "read_linkedin",
    "linkedin profile read": "read_linkedin",
    "check linkedin": "read_linkedin",
    "read github": "read_github",
    "github repo": "read_github",
    "github repository": "read_github",
    "read github repo": "read_github",
    "check github": "read_github",
    "read contacts": "read_contacts",
    "google contacts": "read_contacts",
    "my contacts": "read_contacts",
    "list contacts": "read_contacts",
    "read google contacts": "read_contacts",
    "check contacts": "read_contacts",
}

SendPolicyMode = Literal["allow", "forbid", "conditional", "unknown"]
SendPolicyCondition = Literal["none", "approval", "review", "scheduled_time", "after_job", "other"]
ProvenanceSource = Literal[
    "explicit",
    "normalized",
    "inferred_deterministic",
    "inferred_fuzzy",
    "profile_context",
    "system_default",
    "unresolved",
    "contradictory",
]
ClauseStatus = Literal["recognized", "unmatched", "unresolved", "non_material"]


class InterpretationEvidence(BaseModel):
    """Typed provenance for one interpreted field or value."""

    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=160)
    source: ProvenanceSource
    source_text: str | None = Field(default=None, max_length=1000)
    normalized_value: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rule_id: str | None = Field(default=None, max_length=120)
    interpreter_version: str = Field(default=INTERPRETER_VERSION, max_length=40)
    components_active: list[str] = Field(default_factory=lambda: ["regex_core"], max_length=20)


class InterpretedClause(BaseModel):
    """One material/non-material span from the instruction."""

    model_config = ConfigDict(extra="forbid")

    clause_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    status: ClauseStatus
    material: bool = True
    mapped_outcomes: list[CanonicalOutcome] = Field(default_factory=list, max_length=10)
    reason: str | None = Field(default=None, max_length=500)


class SendPolicy(BaseModel):
    """Structured send authority — not free-text constraints."""

    model_config = ConfigDict(extra="forbid")

    mode: SendPolicyMode = "unknown"
    condition: SendPolicyCondition = "none"
    source: ProvenanceSource = "unresolved"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rule_id: str | None = Field(default=None, max_length=120)


class TargetEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    industry: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=240)
    radius_km: float | None = Field(default=None, ge=0)
    domain: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=2048)
    email: str | None = Field(default=None, max_length=320)
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceSource = "explicit"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SemanticUnit(BaseModel):
    """One material action/target/policy unit — coverage is measured over these."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(min_length=1, max_length=80)
    kind: SemanticUnitKind = "other"
    text: str = Field(min_length=1, max_length=2000)
    accounted: bool = False
    mapped_outcomes: list[CanonicalOutcome] = Field(default_factory=list, max_length=10)
    risk: RiskLevel = "low"
    reason: str | None = Field(default=None, max_length=500)


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=160)
    first_span: str = Field(min_length=1, max_length=500)
    second_span: str = Field(min_length=1, max_length=500)
    first_value: str = Field(min_length=1, max_length=240)
    second_value: str = Field(min_length=1, max_length=240)
    risk: RiskLevel = "high"
    resolution_status: Literal["unresolved", "resolved"] = "unresolved"
    rule_id: str | None = Field(default=None, max_length=120)


class StructuredPolicy(BaseModel):
    """Generic permission/timing policy for non-send channels."""

    model_config = ConfigDict(extra="forbid")

    mode: SendPolicyMode = "unknown"
    condition: SendPolicyCondition = "none"
    source: ProvenanceSource = "unresolved"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rule_id: str | None = Field(default=None, max_length=120)


class TimingConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["absolute_window", "relative", "after_job", "after_approval"] = "absolute_window"
    start: str | None = Field(default=None, max_length=80)
    end: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=240)
    provenance: ProvenanceSource = "explicit"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class JobDependency(BaseModel):
    """Typed dependency — not unconditional pipeline expansion."""

    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    kind: DependencyKind = "hard"
    # Expand only when these intent/job inputs are missing.
    required_when_missing: tuple[str, ...] = ()
    # Alternative input sources that satisfy the dependency without expansion.
    satisfied_by: tuple[str, ...] = ()


class Clarification(BaseModel):
    """Backend-owned restatement requirement (not a fragment Q&A slot).

    ``question`` holds the full-mission restatement text shown to the user.
    The frontend must not merge answers into MissionIntent; the user restates
    the complete raw instruction and compose runs again.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)


class SuccessCriterion(BaseModel):
    """Display / evidence description only — not a transport for structured facts."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    measurable: bool = True


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tasks: int | None = Field(default=None, ge=1)
    max_runtime_minutes: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)


def normalize_outcome_token(value: str) -> CanonicalOutcome | None:
    """Map a phrase or ID to a canonical outcome, or None if unknown."""

    raw = " ".join(value.strip().lower().replace("-", "_").split())
    if not raw:
        return None
    underscored = raw.replace(" ", "_")
    if underscored in CANONICAL_OUTCOMES:
        return underscored  # type: ignore[return-value]
    if raw in LEGACY_OUTCOME_ALIASES:
        return LEGACY_OUTCOME_ALIASES[raw]
    if underscored.replace("_", " ") in LEGACY_OUTCOME_ALIASES:
        return LEGACY_OUTCOME_ALIASES[underscored.replace("_", " ")]
    return None


class MissionIntent(BaseModel):
    """Candidate interpretation of a user instruction. Not an execution grant."""

    model_config = ConfigDict(extra="forbid")

    # Audit forms
    raw_instruction: str = Field(default="", max_length=8000)
    normalized_instruction: str = Field(default="", max_length=8000)
    # Display only — not authoritative for execution inputs.
    objective: str = Field(min_length=1, max_length=5000)
    # Canonical outcome IDs only (legacy phrases normalized on validate).
    requested_outcomes: list[str] = Field(default_factory=list, max_length=30)
    unsupported_outcomes: list[str] = Field(default_factory=list, max_length=20)
    requested_quantity: int | None = Field(default=None, ge=1, le=100)
    quantity_provenance: ProvenanceSource | None = None
    send_policy: SendPolicy = Field(default_factory=SendPolicy)
    contact_policy: StructuredPolicy = Field(default_factory=StructuredPolicy)
    publish_policy: StructuredPolicy = Field(default_factory=StructuredPolicy)
    write_policy: StructuredPolicy = Field(default_factory=StructuredPolicy)
    target_entities: list[TargetEntity] = Field(default_factory=list, max_length=20)
    timing_constraints: list[TimingConstraint] = Field(default_factory=list, max_length=10)
    # Human-readable display constraints (not authority).
    constraints: list[str] = Field(default_factory=list, max_length=30)
    # Split forbid concepts (resolver uses forbidden_actions + policies).
    forbidden_canonical_outcomes: list[str] = Field(default_factory=list, max_length=30)
    forbidden_actions: list[str] = Field(default_factory=list, max_length=30)
    # Legacy mixed field — kept for compatibility; prefer the split fields above.
    forbidden_outcomes: list[str] = Field(default_factory=list, max_length=30)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list, max_length=20)
    urgency: str = Field(default="normal", max_length=40)
    approval_preference: str = Field(default="review_before_external_action", max_length=80)
    budget_limits: BudgetLimits | None = None
    context_requirements: list[str] = Field(default_factory=list, max_length=20)
    ambiguity: list[Clarification] = Field(default_factory=list, max_length=20)
    interpreted_clauses: list[InterpretedClause] = Field(default_factory=list, max_length=40)
    unmatched_material_clauses: list[InterpretedClause] = Field(default_factory=list, max_length=20)
    semantic_units: list[SemanticUnit] = Field(default_factory=list, max_length=60)
    unmatched_material_units: list[SemanticUnit] = Field(default_factory=list, max_length=30)
    contradictions: list[Contradiction] = Field(default_factory=list, max_length=20)
    interpretation_evidence: list[InterpretationEvidence] = Field(default_factory=list, max_length=50)
    coverage_score: float = Field(default=0.0, ge=0.0, le=1.0)
    minimum_field_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    interpretation_ready: bool = False
    interpretation_readiness_reasons: list[str] = Field(default_factory=list, max_length=20)
    components_available: list[str] = Field(default_factory=list, max_length=30)
    components_executed: list[str] = Field(default_factory=list, max_length=30)
    components_contributing: list[str] = Field(default_factory=list, max_length=30)
    # Legacy alias of components_executed for older readers.
    components_active: list[str] = Field(default_factory=lambda: ["regex_core"], max_length=30)
    interpreter_version: str = Field(default=INTERPRETER_VERSION, max_length=40)

    @field_validator("requested_outcomes", mode="before")
    @classmethod
    def _normalize_outcomes(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        normalized: list[str] = []
        for item in value:
            if not item or not str(item).strip():
                continue
            mapped = normalize_outcome_token(str(item))
            if mapped is None:
                # Reject unknown tokens to prevent vocabulary drift.
                raise ValueError(f"unknown requested_outcome: {item!r}")
            if mapped not in normalized:
                normalized.append(mapped)
        return normalized

    @field_validator(
        "constraints",
        "forbidden_outcomes",
        "forbidden_canonical_outcomes",
        "forbidden_actions",
        "unsupported_outcomes",
        "context_requirements",
        "components_active",
        "components_available",
        "components_executed",
        "components_contributing",
        "interpretation_readiness_reasons",
    )
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item and item.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("list entries must be unique")
        return normalized

    def effective_forbidden_actions(self) -> list[str]:
        """Resolver-facing action forbid set (structured only)."""

        actions = {item.strip() for item in self.forbidden_actions if item and item.strip()}
        # Legacy bridge: only known action tokens from mixed forbidden_outcomes.
        for item in self.forbidden_outcomes:
            token = item.strip()
            if "." in token and " " not in token:
                actions.add(token)
        if self.send_policy.mode in {"forbid", "conditional"}:
            actions.add("gtm.email_send")
        if self.publish_policy.mode in {"forbid", "conditional"}:
            actions.add("gtm.social_publish")
        return sorted(actions)

    def blocks_send(self) -> bool:
        """Authoritative send block from structured policy (not constraint prose)."""

        if self.send_policy.mode == "forbid":
            return True
        if self.send_policy.mode == "conditional" and self.send_policy.condition in {
            "approval",
            "review",
        }:
            return True
        forbidden = set(self.effective_forbidden_actions())
        return "gtm.email_send" in forbidden

    def has_recipient_context(self) -> bool:
        for entity in self.target_entities:
            if entity.email or entity.type in {"person", "recipient", "contact"}:
                return True
            if entity.name and entity.email:
                return True
            attrs = entity.attributes or {}
            if attrs.get("email") or attrs.get("recipient") or attrs.get("crm_record_id"):
                return True
        return False


class BusinessJob(BaseModel):
    """Business work unit between intent outcomes and governed abilities."""

    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    vertical_role: str = Field(min_length=1, max_length=120)
    # Canonical outcome IDs only.
    supported_outcomes: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    produced_outputs: tuple[str, ...] = ()
    candidate_actions: tuple[str, ...] = ()
    risk_level: JobRiskLevel = "low"
    maturity: JobMaturity = "runtime_bound"
    credential_policy: Literal["none", "optional", "required"] = "none"
    approval_policy: Literal["none", "review_before_external", "always_review"] = "none"
    evidence_requirements: tuple[str, ...] = ()
    # Legacy unconditional deps — prefer dependencies when present.
    depends_on_jobs: tuple[str, ...] = ()
    dependencies: tuple[JobDependency, ...] = ()
    seed_brain_missions: tuple[str, ...] = ()


class AbilityAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    status: ReadinessStatus
    reason_not_selected: str | None = Field(default=None, max_length=500)


class AbilitySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    ability_id: str | None = Field(default=None, max_length=160)
    action_name: str = Field(min_length=1, max_length=160)
    selection_status: SelectionStatus = "selected"
    selection_reason: str = Field(min_length=1, max_length=500)
    readiness: ReadinessStatus
    vertical_role: str = Field(min_length=1, max_length=120)
    alternatives: list[AbilityAlternative] = Field(default_factory=list, max_length=20)
    credential_reference: dict[str, Any] | None = None
    side_effect_class: str = Field(min_length=1, max_length=40)
    requires_connection: bool = False
    connection_provider: str | None = Field(default=None, max_length=80)


class JobAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    vertical_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    depends_on_jobs: list[str] = Field(default_factory=list, max_length=20)


class PlannedStepPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    job_key: str = Field(min_length=1, max_length=120)
    action_name: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    output_contract: str = Field(min_length=1, max_length=240)
    input_bindings: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    tool_input: dict[str, Any] = Field(default_factory=dict)
    credential_reference: dict[str, Any] | None = None


class AllowedActionsProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_by: Literal["mission_composition_engine"] = "mission_composition_engine"
    selection_version: str = Field(default="1", max_length=40)
    user_supplied: Literal[False] = False
    validated_against_registry: bool = True
    validated_against_charter: bool = True
    validated_against_manifests: bool = True
    job_catalog_version: str = Field(default=JOB_CATALOG_VERSION, max_length=40)
    resolver_version: str = Field(default=CAPABILITY_RESOLVER_VERSION, max_length=40)


class CompositionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpreter_version: str = Field(default=INTERPRETER_VERSION, max_length=40)
    job_catalog_version: str = Field(default=JOB_CATALOG_VERSION, max_length=40)
    resolver_version: str = Field(default=CAPABILITY_RESOLVER_VERSION, max_length=40)
    composition_schema_version: int = Field(default=COMPOSITION_SCHEMA_VERSION, ge=1)
    grants_execution_authority: Literal[False] = False
    authority_class: Literal["declarative", "read_model"] = "read_model"
    know_how_id: str | None = Field(default=None, max_length=160)
    know_how_version: str | None = Field(default=None, max_length=40)
    components_active: list[str] = Field(default_factory=lambda: ["regex_core"], max_length=20)

    @model_validator(mode="after")
    def _know_how_reference_is_complete(self) -> CompositionProvenance:
        if bool(self.know_how_id) != bool(self.know_how_version):
            raise ValueError("know-how reference requires both id and version")
        return self


class MissionCompositionRecord(BaseModel):
    """Canonical per-mission composition artifact before runtime admission."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=COMPOSITION_SCHEMA_VERSION, ge=1)
    proposal_id: str = Field(min_length=1, max_length=80)
    # Default preserves schema-v2 rows that predate thread scoping (migration 0036).
    interpretation_thread_id: str = Field(default="legacy-unscoped", min_length=1, max_length=80)
    proposal_status: ProposalStatus = "interpretation_ready"
    # Populated after successful confirm for idempotent retries (tenant-scoped store).
    confirm_receipt: dict[str, Any] | None = None
    instruction: str = Field(min_length=1, max_length=8000)
    raw_instruction: str = Field(default="", max_length=8000)
    normalized_instruction: str = Field(default="", max_length=8000)
    intent: MissionIntent
    job_assignments: list[JobAssignment] = Field(default_factory=list, max_length=40)
    ability_selections: list[AbilitySelection] = Field(default_factory=list, max_length=40)
    forbidden_actions: list[str] = Field(default_factory=list, max_length=40)
    allowed_actions: list[str] = Field(default_factory=list, max_length=50)
    allowed_actions_provenance: AllowedActionsProvenance = Field(default_factory=AllowedActionsProvenance)
    missing_connections: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    approval_gates: list[str] = Field(default_factory=list, max_length=20)
    planned_steps: list[PlannedStepPreview] = Field(default_factory=list, max_length=40)
    task_graph_preview: dict[str, Any] = Field(default_factory=dict)
    planner_proposal: dict[str, Any] | None = None
    planner_provenance: dict[str, Any] | None = None
    clarifications: list[Clarification] = Field(default_factory=list, max_length=20)
    ready_to_start: bool = False
    composition_provenance: CompositionProvenance = Field(default_factory=CompositionProvenance)

    @model_validator(mode="after")
    def _selected_actions_subset(self) -> MissionCompositionRecord:
        runtime_selected = sorted(
            {
                item.action_name
                for item in self.ability_selections
                if item.selection_status == "selected" and item.readiness == "ready"
            }
        )
        if list(self.allowed_actions) != runtime_selected and self.ability_selections:
            self.allowed_actions = runtime_selected
        return self

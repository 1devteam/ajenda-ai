"""Versioned declarative know-how for the selected Revenue Operations vertical.

Know-how constrains composition. It never registers actions, resolves credentials,
grants approval, persists runtime state, or dispatches work.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.mission_composition.connector_capabilities import CONNECTORS_BY_ID
from backend.services.mission_composition.contracts import CanonicalOutcome
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY
from backend.services.tools.action_registry import ActionRegistry, get_default_action_registry
from backend.services.tools.schemas import SideEffectClass
from backend.services.vertical_ops.graft1st_contracts import (
    GRAFT1ST_CONTRACT_PACKAGE_ID,
    GRAFT1ST_CONTRACT_PACKAGE_VERSION,
)

REVOPS_KNOW_HOW_SCHEMA_VERSION = 1


class KnowHowBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_prospects: int = Field(ge=1, le=50)
    max_external_effects: int = Field(ge=0, le=100)
    max_wall_seconds: int = Field(ge=1, le=86_400)
    max_provider_calls: int = Field(ge=0, le=500)
    max_model_tokens: int = Field(ge=0, le=2_000_000)
    max_cost_usd: float = Field(ge=0, le=10_000)


class KnowHowStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str = Field(min_length=1, max_length=120)
    job_keys: tuple[str, ...] = Field(min_length=1, max_length=20)
    depends_on: tuple[str, ...] = Field(default=(), max_length=20)
    optional: bool = False
    review_boundary: Literal["none", "before_external_effect"] = "none"


class DeliverableField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=120)
    produced_by_jobs: tuple[str, ...] = Field(min_length=1, max_length=20)
    required: bool = True


class VerticalKnowHowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    know_how_id: str = Field(min_length=1, max_length=160)
    know_how_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    vertical: Literal["revenue_operations"] = "revenue_operations"
    authority_class: Literal["declarative"] = "declarative"
    grants_execution_authority: Literal[False] = False
    promotion_status: Literal["blocked_pending_owner_thresholds", "eligible"]
    supported_outcomes: tuple[CanonicalOutcome, ...] = Field(min_length=1, max_length=30)
    stages: tuple[KnowHowStage, ...] = Field(min_length=1, max_length=20)
    deliverable_fields: tuple[DeliverableField, ...] = Field(min_length=1, max_length=30)
    connectors: tuple[str, ...] = Field(default=(), max_length=20)
    prohibited_actions: tuple[str, ...] = Field(default=(), max_length=40)
    budget: KnowHowBudget | None = None
    graft1st_contract_package_id: str | None = Field(default=None, min_length=1, max_length=160)
    graft1st_contract_package_version: str | None = Field(
        default=None,
        pattern=r"^[1-9]\d*\.\d+\.\d+$",
        max_length=40,
    )

    @model_validator(mode="after")
    def validate_shape(self) -> VerticalKnowHowContract:
        stage_keys = [stage.stage_key for stage in self.stages]
        if len(stage_keys) != len(set(stage_keys)):
            raise ValueError("know-how stage_key values must be unique")
        known_stages = set(stage_keys)
        for stage in self.stages:
            missing = set(stage.depends_on) - known_stages
            if missing:
                raise ValueError(f"stage {stage.stage_key} depends on unknown stages: {sorted(missing)}")
            if stage.stage_key in stage.depends_on:
                raise ValueError(f"stage {stage.stage_key} cannot depend on itself")
        _assert_acyclic(self.stages)

        job_keys = [job_key for stage in self.stages for job_key in stage.job_keys]
        if len(job_keys) != len(set(job_keys)):
            raise ValueError("know-how jobs must belong to exactly one stage")
        unknown_jobs = set(job_keys) - set(BUSINESS_JOBS_BY_KEY)
        if unknown_jobs:
            raise ValueError(f"know-how references unknown jobs: {sorted(unknown_jobs)}")

        for field in self.deliverable_fields:
            unknown_producers = set(field.produced_by_jobs) - set(job_keys)
            if unknown_producers:
                raise ValueError(
                    f"deliverable {field.field_key} references jobs outside know-how: {sorted(unknown_producers)}"
                )
            producer_outputs = {
                output
                for job_key in field.produced_by_jobs
                for output in BUSINESS_JOBS_BY_KEY[job_key].produced_outputs
            }
            if field.field_key not in producer_outputs:
                raise ValueError(f"deliverable {field.field_key} has no declared producer output")

        unknown_connectors = set(self.connectors) - set(CONNECTORS_BY_ID)
        if unknown_connectors:
            raise ValueError(f"know-how references unknown connectors: {sorted(unknown_connectors)}")
        if self.promotion_status == "eligible" and self.budget is None:
            raise ValueError("eligible know-how requires an owner-approved budget")
        package_fields = (self.graft1st_contract_package_id, self.graft1st_contract_package_version)
        if any(package_fields) and not all(package_fields):
            raise ValueError("G.R.A.F.T.1st contract package reference requires both id and version")
        return self


def _assert_acyclic(stages: tuple[KnowHowStage, ...]) -> None:
    dependencies = {stage.stage_key: set(stage.depends_on) for stage in stages}
    remaining = set(dependencies)
    while remaining:
        ready = {key for key in remaining if not (dependencies[key] & remaining)}
        if not ready:
            raise ValueError("know-how stage dependencies contain a cycle")
        remaining -= ready


def validate_know_how_runtime_references(
    contract: VerticalKnowHowContract,
    *,
    registry: ActionRegistry | None = None,
) -> None:
    """Validate references without executing or changing the action registry."""

    action_registry = registry or get_default_action_registry()
    prohibited = set(contract.prohibited_actions)
    for stage in contract.stages:
        for job_key in stage.job_keys:
            job = BUSINESS_JOBS_BY_KEY[job_key]
            if job.maturity != "runtime_bound":
                raise ValueError(f"know-how job is not runtime_bound: {job_key}")
            for action_name in job.candidate_actions:
                definition = action_registry.get(action_name)
                if definition.input_model is None:
                    raise ValueError(f"know-how action has no Pydantic input model: {action_name}")
                manifest = ABILITY_MANIFESTS_BY_ACTION.get(action_name)
                if manifest is None:
                    # Registered aliases are allowed only when their canonical action has a manifest.
                    canonical = definition.name
                    manifest = ABILITY_MANIFESTS_BY_ACTION.get(canonical)
                if manifest is None:
                    raise ValueError(f"know-how action has no ability manifest: {action_name}")
                effective = manifest.max_side_effect_class or manifest.side_effect_class
                if effective in {
                    SideEffectClass.EXTERNAL_WRITE,
                    SideEffectClass.EXTERNAL_SEND,
                    SideEffectClass.EXTERNAL_PUBLISH,
                }:
                    if not manifest.approval_required or not manifest.idempotency_required:
                        raise ValueError(f"external-effect action lacks approval/idempotency contract: {action_name}")
                    if stage.review_boundary != "before_external_effect":
                        raise ValueError(f"external-effect stage lacks review boundary: {stage.stage_key}")
                if action_name in prohibited:
                    raise ValueError(f"prohibited action referenced by know-how job: {action_name}")


REVOPS_V1_KNOW_HOW = VerticalKnowHowContract(
    know_how_id="revops.research-to-approved-outreach",
    know_how_version="1.0.0",
    promotion_status="blocked_pending_owner_thresholds",
    supported_outcomes=(
        "research_prospects",
        "observe_contacts",
        "qualify_prospects",
        "enrich_contacts",
        "prepare_outreach",
        "read_crm",
        "send_outreach",
        "update_crm",
        "persist_internal_crm",
    ),
    stages=(
        KnowHowStage(
            stage_key="research",
            job_keys=("research.discover_prospects", "research.observe_sources", "sales.research_context"),
        ),
        KnowHowStage(
            stage_key="decision_support",
            job_keys=("intelligence.retrieve_knowledge", "intelligence.advise_next"),
            depends_on=("research",),
            optional=True,
        ),
        KnowHowStage(
            stage_key="qualification",
            job_keys=("sales.qualify_prospects", "gtm.enrich_contacts"),
            depends_on=("research",),
        ),
        KnowHowStage(
            stage_key="draft",
            job_keys=("email.prepare_outreach",),
            depends_on=("qualification",),
        ),
        KnowHowStage(
            stage_key="crm_context",
            job_keys=("crm.read_records",),
            optional=True,
        ),
        KnowHowStage(
            stage_key="delivery",
            job_keys=("email.deliver_outreach",),
            depends_on=("draft",),
            optional=True,
            review_boundary="before_external_effect",
        ),
        KnowHowStage(
            stage_key="crm_update",
            job_keys=("crm.pipeline_maintenance",),
            depends_on=("qualification",),
            optional=True,
            review_boundary="before_external_effect",
        ),
    ),
    deliverable_fields=(
        DeliverableField(field_key="prospect_candidates", produced_by_jobs=("research.discover_prospects",)),
        DeliverableField(field_key="observed_contacts", produced_by_jobs=("research.observe_sources",)),
        DeliverableField(field_key="qualified_prospects", produced_by_jobs=("sales.qualify_prospects",)),
        DeliverableField(field_key="enriched_prospects", produced_by_jobs=("gtm.enrich_contacts",)),
        DeliverableField(field_key="introduction_drafts", produced_by_jobs=("email.prepare_outreach",)),
        DeliverableField(field_key="sent_messages", produced_by_jobs=("email.deliver_outreach",), required=False),
        DeliverableField(field_key="pipeline_records", produced_by_jobs=("crm.pipeline_maintenance",), required=False),
    ),
    connectors=("gmail", "hubspot"),
    prohibited_actions=("gtm.social_publish", "web.open_write", "webhook.dispatch"),
    budget=None,
)

REVOPS_V2_KNOW_HOW = VerticalKnowHowContract(
    know_how_id="revops.gtm-crm-communications",
    know_how_version="2.0.0",
    # Owner-approved promotion: V2 combines research synthesis with the
    # existing GTM qualification, drafting, and internal CRM stages.
    promotion_status="eligible",
    supported_outcomes=(*REVOPS_V1_KNOW_HOW.supported_outcomes, "synthesize_research_report"),
    stages=(
        *REVOPS_V1_KNOW_HOW.stages,
        KnowHowStage(
            stage_key="research_report",
            job_keys=("research.synthesize_report",),
            depends_on=("research",),
        ),
    ),
    deliverable_fields=(
        *REVOPS_V1_KNOW_HOW.deliverable_fields,
        DeliverableField(
            field_key="research_report",
            produced_by_jobs=("research.synthesize_report",),
        ),
    ),
    connectors=REVOPS_V1_KNOW_HOW.connectors,
    prohibited_actions=REVOPS_V1_KNOW_HOW.prohibited_actions,
    budget=KnowHowBudget(
        max_prospects=10,
        max_external_effects=0,
        max_wall_seconds=900,
        max_provider_calls=40,
        max_model_tokens=200_000,
        max_cost_usd=25.0,
    ),
    graft1st_contract_package_id=GRAFT1ST_CONTRACT_PACKAGE_ID,
    graft1st_contract_package_version=GRAFT1ST_CONTRACT_PACKAGE_VERSION,
)

VERTICAL_KNOW_HOW_BY_ID_VERSION: dict[tuple[str, str], VerticalKnowHowContract] = {
    (REVOPS_V1_KNOW_HOW.know_how_id, REVOPS_V1_KNOW_HOW.know_how_version): REVOPS_V1_KNOW_HOW,
    (REVOPS_V2_KNOW_HOW.know_how_id, REVOPS_V2_KNOW_HOW.know_how_version): REVOPS_V2_KNOW_HOW,
}


def get_vertical_know_how(*, know_how_id: str, know_how_version: str) -> VerticalKnowHowContract:
    contract = VERTICAL_KNOW_HOW_BY_ID_VERSION.get((know_how_id.strip(), know_how_version.strip()))
    if contract is None:
        raise ValueError(f"unknown or unavailable know-how version: {know_how_id}@{know_how_version}")
    return contract


def select_vertical_know_how(outcomes: list[str]) -> VerticalKnowHowContract | None:
    """Select only when every requested outcome belongs to the bounded RevOps contract."""

    requested = set(outcomes)
    v2_supported = {str(item) for item in REVOPS_V2_KNOW_HOW.supported_outcomes}
    if "synthesize_research_report" in requested and requested <= v2_supported:
        return REVOPS_V2_KNOW_HOW
    supported = {str(item) for item in REVOPS_V1_KNOW_HOW.supported_outcomes}
    if requested and requested <= supported:
        return REVOPS_V1_KNOW_HOW
    return None

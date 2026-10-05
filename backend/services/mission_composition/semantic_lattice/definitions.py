"""Shared business vocabulary for declarative mission interpretation.

Concepts in this module normalize language only. They do not select jobs, resolve
abilities, grant authority, resolve credentials, or execute provider work.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConceptType = Literal["entity", "process", "artifact", "relationship", "metric"]


class SemanticConcept(BaseModel):
    """Versioned, shared concept definition with inspectable provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    aliases: tuple[str, ...] = Field(default=(), max_length=30)
    concept_type: ConceptType
    related_concepts: tuple[str, ...] = Field(default=(), max_length=20)
    applicable_domains: tuple[str, ...] = Field(default=("shared_business",), max_length=20)
    normalization_rule: str = Field(default="lowercase_trim_collapse_whitespace", max_length=160)
    source_reference: str = Field(min_length=1, max_length=240)
    version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    grants_execution_authority: Literal[False] = False


class TenantSemanticOverride(BaseModel):
    """Tenant-owned terminology alias; never mutates shared vocabulary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=120)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=20)
    source_reference: str = Field(min_length=1, max_length=240)
    version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    scope: Literal["tenant_private"] = "tenant_private"
    grants_execution_authority: Literal[False] = False


class SemanticJobBinding(BaseModel):
    """Read-only link between a semantic concept and canonical business jobs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1, max_length=120)
    concept_version: str = Field(min_length=1, max_length=40)
    source: Literal["requested_outcome", "explicit_instruction"]
    expected_job_keys: tuple[str, ...] = Field(default=(), max_length=10)
    selected_job_keys: tuple[str, ...] = Field(default=(), max_length=40)
    status: Literal["informational", "satisfied", "conflict"] = "informational"
    grants_execution_authority: Literal[False] = False


class SemanticLatticeComponent(BaseModel):
    """Versioned declarative lattice component with explicit multi-parent lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component_id: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    parents: tuple[str, ...] = Field(default=(), max_length=8)
    source_reference: str = Field(min_length=1, max_length=240)
    grants_execution_authority: Literal[False] = False


class SemanticComponentJobGuidance(BaseModel):
    """Advisory component-to-job hint; the job catalog remains authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component_id: str = Field(min_length=1, max_length=80)
    candidate_job_keys: tuple[str, ...] = Field(default=(), max_length=20)
    selected_job_keys: tuple[str, ...] = Field(default=(), max_length=40)
    status: Literal["informational", "satisfied"] = "informational"
    grants_execution_authority: Literal[False] = False


class SemanticSelection(BaseModel):
    """Composed semantic read model used to inspect concept-to-job reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    lattice_version: str = Field(default="1.0.0", pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    active_components: tuple[str, ...] = Field(default=(), max_length=30)
    active_component_provenance: tuple[SemanticLatticeComponent, ...] = Field(default=(), max_length=30)
    component_conflicts: tuple[str, ...] = Field(default=(), max_length=20)
    component_job_guidance: tuple[SemanticComponentJobGuidance, ...] = Field(default=(), max_length=30)
    concepts: tuple[str, ...] = Field(default=(), max_length=40)
    concept_provenance: tuple[SemanticConcept, ...] = Field(default=(), max_length=40)
    tenant_overrides: tuple[TenantSemanticOverride, ...] = Field(default=(), max_length=30)
    matched_terms: tuple[str, ...] = Field(default=(), max_length=40)
    bindings: tuple[SemanticJobBinding, ...] = Field(default=(), max_length=40)
    conflicts: tuple[str, ...] = Field(default=(), max_length=20)
    source_reference: str = "Ajenda shared semantic vocabulary"
    grants_execution_authority: Literal[False] = False


def normalize_concept_text(value: str) -> str:
    """Normalize user terminology without applying fuzzy or authority-bearing inference."""

    return re.sub(r"\s+", " ", value.strip().lower())


SHARED_BUSINESS_CONCEPTS: tuple[SemanticConcept, ...] = (
    SemanticConcept(
        concept_id="prospect",
        display_name="Prospect",
        aliases=("lead", "target company", "target account"),
        concept_type="entity",
        related_concepts=("customer", "qualification", "outreach"),
        applicable_domains=("shared_business", "gtm"),
        source_reference="Ajenda shared GTM vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="customer",
        display_name="Customer",
        aliases=("client", "account", "buyer"),
        concept_type="entity",
        related_concepts=("prospect", "pipeline"),
        applicable_domains=("shared_business", "gtm"),
        source_reference="Ajenda shared GTM vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="qualification",
        display_name="Qualification",
        aliases=("score", "rank", "fit", "lead quality"),
        concept_type="process",
        related_concepts=("prospect",),
        applicable_domains=("shared_business", "gtm"),
        source_reference="Ajenda shared GTM vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="outreach",
        display_name="Outreach",
        aliases=("introduction", "email", "follow-up"),
        concept_type="process",
        related_concepts=("prospect", "customer"),
        applicable_domains=("shared_business", "gtm"),
        source_reference="Ajenda shared GTM vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="pipeline",
        display_name="Pipeline",
        aliases=("deal stage", "opportunity stage", "sales stage"),
        concept_type="relationship",
        related_concepts=("prospect", "customer"),
        applicable_domains=("shared_business", "gtm"),
        source_reference="Ajenda shared GTM vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="estimate",
        display_name="Estimate",
        aliases=("quote", "proposal", "pricing estimate"),
        concept_type="artifact",
        related_concepts=("customer",),
        applicable_domains=("shared_business", "service_business"),
        source_reference="Ajenda shared business vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="job",
        display_name="Job",
        aliases=("work order", "service call", "project"),
        concept_type="artifact",
        related_concepts=("customer",),
        applicable_domains=("shared_business", "service_business"),
        source_reference="Ajenda shared business vocabulary",
        version="1.0.0",
    ),
)

DOMAIN_AND_INDUSTRY_CONCEPTS: tuple[SemanticConcept, ...] = (
    SemanticConcept(
        concept_id="service_area",
        display_name="Service area",
        aliases=("coverage area", "territory", "location coverage"),
        concept_type="relationship",
        related_concepts=("customer", "job"),
        applicable_domains=("local_service_business", "field_service"),
        source_reference="Ajenda local-service business vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="appointment",
        display_name="Appointment",
        aliases=("booking", "scheduled visit"),
        concept_type="artifact",
        related_concepts=("customer", "job"),
        applicable_domains=("local_service_business", "healthcare_business", "professional_services"),
        source_reference="Ajenda service-business vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="technician",
        display_name="Technician",
        aliases=("service technician", "field worker"),
        concept_type="entity",
        related_concepts=("job", "service_area"),
        applicable_domains=("field_service",),
        source_reference="Ajenda field-service vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="maintenance_plan",
        display_name="Maintenance plan",
        aliases=(
            "maintenance agreements",
            "maintenance agreement",
            "service plan",
            "service plans",
            "maintenance plans",
        ),
        concept_type="relationship",
        related_concepts=("customer", "job"),
        applicable_domains=("recurring_service_business", "field_service", "hvac"),
        source_reference="Ajenda recurring-service and HVAC vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="heat_pump",
        display_name="Heat pump",
        aliases=("heat-pump",),
        concept_type="entity",
        related_concepts=("job", "maintenance_plan"),
        applicable_domains=("hvac",),
        source_reference="Ajenda HVAC industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="furnace",
        display_name="Furnace",
        aliases=("heating furnace",),
        concept_type="entity",
        related_concepts=("job", "maintenance_plan"),
        applicable_domains=("hvac",),
        source_reference="Ajenda HVAC industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="storm_damage",
        display_name="Storm damage",
        aliases=("hail damage", "wind damage"),
        concept_type="process",
        related_concepts=("estimate", "job"),
        applicable_domains=("roofing",),
        source_reference="Ajenda roofing industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="drain_cleaning",
        display_name="Drain cleaning",
        aliases=("drain service",),
        concept_type="process",
        related_concepts=("job", "service_area"),
        applicable_domains=("plumbing",),
        source_reference="Ajenda plumbing industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="water_heater",
        display_name="Water heater",
        aliases=("water-heater",),
        concept_type="entity",
        related_concepts=("job", "estimate"),
        applicable_domains=("plumbing",),
        source_reference="Ajenda plumbing industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="panel_upgrade",
        display_name="Panel upgrade",
        aliases=("electrical panel upgrade",),
        concept_type="process",
        related_concepts=("estimate", "job"),
        applicable_domains=("electrical",),
        source_reference="Ajenda electrical industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="irrigation",
        display_name="Irrigation",
        aliases=("irrigation service", "sprinkler service"),
        concept_type="process",
        related_concepts=("job", "service_area"),
        applicable_domains=("landscaping",),
        source_reference="Ajenda landscaping industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="termite",
        display_name="Termite",
        aliases=("termite control",),
        concept_type="entity",
        related_concepts=("job", "maintenance_plan"),
        applicable_domains=("pest_control",),
        source_reference="Ajenda pest-control industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="matter",
        display_name="Matter",
        aliases=("legal matter", "case"),
        concept_type="artifact",
        related_concepts=("customer", "appointment"),
        applicable_domains=("professional_services", "legal"),
        source_reference="Ajenda legal industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="patient",
        display_name="Patient",
        aliases=("new patient",),
        concept_type="entity",
        related_concepts=("appointment", "customer"),
        applicable_domains=("healthcare_business", "dental"),
        source_reference="Ajenda healthcare-business and dental vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="candidate",
        display_name="Candidate",
        aliases=("job candidate", "applicant"),
        concept_type="entity",
        related_concepts=("pipeline", "outreach"),
        applicable_domains=("recruiting",),
        source_reference="Ajenda recruiting industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="trial",
        display_name="Trial",
        aliases=("free trial", "product trial"),
        concept_type="relationship",
        related_concepts=("customer", "pipeline"),
        applicable_domains=("b2b_software", "saas"),
        source_reference="Ajenda SaaS industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="subscription",
        display_name="Subscription",
        aliases=("plan subscription", "recurring subscription"),
        concept_type="relationship",
        related_concepts=("customer", "pipeline"),
        applicable_domains=("b2b_software", "saas", "recurring_service_business"),
        source_reference="Ajenda recurring-business and SaaS vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="sku",
        display_name="SKU",
        aliases=("stock keeping unit", "product code"),
        concept_type="entity",
        related_concepts=("customer", "order"),
        applicable_domains=("ecommerce", "retail"),
        source_reference="Ajenda e-commerce vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="order",
        display_name="Order",
        aliases=("purchase order", "customer order"),
        concept_type="artifact",
        related_concepts=("customer", "sku"),
        applicable_domains=("ecommerce", "retail"),
        source_reference="Ajenda e-commerce vocabulary",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="campaign",
        display_name="Campaign",
        aliases=("ad campaign", "marketing campaign", "campaigns"),
        concept_type="artifact",
        related_concepts=("audience", "creative", "ad_budget"),
        applicable_domains=("advertising",),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="audience",
        display_name="Audience",
        aliases=("target audience", "ad audience", "segment"),
        concept_type="entity",
        related_concepts=("prospect", "campaign"),
        applicable_domains=("advertising", "gtm"),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="creative",
        display_name="Creative",
        aliases=("ad creative", "advertisement creative"),
        concept_type="artifact",
        related_concepts=("campaign", "audience"),
        applicable_domains=("advertising",),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="ad_budget",
        display_name="Ad budget",
        aliases=("advertising budget", "media budget", "spend budget", "ad spend", "spend"),
        concept_type="metric",
        related_concepts=("campaign",),
        applicable_domains=("advertising", "finance"),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="impression",
        display_name="Impression",
        aliases=("ad impression", "reach impression", "impressions"),
        concept_type="metric",
        related_concepts=("campaign", "audience"),
        applicable_domains=("advertising",),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="click",
        display_name="Click",
        aliases=("ad click", "link click", "clicks"),
        concept_type="metric",
        related_concepts=("campaign", "impression"),
        applicable_domains=("advertising",),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
    SemanticConcept(
        concept_id="ad_conversion",
        display_name="Ad conversion",
        aliases=("conversion from ads", "advertising conversion", "conversion", "conversions"),
        concept_type="metric",
        related_concepts=("campaign", "click", "customer"),
        applicable_domains=("advertising", "gtm"),
        source_reference="Ajenda advertising industry overlay",
        version="1.0.0",
    ),
)

ALL_SEMANTIC_CONCEPTS: tuple[SemanticConcept, ...] = SHARED_BUSINESS_CONCEPTS + DOMAIN_AND_INDUSTRY_CONCEPTS
SHARED_BUSINESS_CONCEPTS_BY_ID = {concept.concept_id: concept for concept in ALL_SEMANTIC_CONCEPTS}
_ALIASES = {
    normalize_concept_text(alias): concept.concept_id
    for concept in ALL_SEMANTIC_CONCEPTS
    for alias in (concept.concept_id, concept.display_name, *concept.aliases)
}

_OUTCOME_CONCEPTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "research_prospects": ("prospect", ("research.discover_prospects",)),
    "qualify_prospects": ("qualification", ("sales.qualify_prospects",)),
    "prepare_outreach": ("outreach", ("email.prepare_outreach",)),
    "send_outreach": ("outreach", ("email.deliver_outreach",)),
    "read_crm": ("pipeline", ("crm.read_records",)),
    "persist_internal_crm": ("pipeline", ("crm.internal_persistence",)),
    "maintain_pipeline": ("pipeline", ("crm.pipeline_maintenance",)),
}

_COMPONENT_ORDER = (
    "shared_business",
    "gtm.core",
    "local_service_business",
    "field_service",
    "professional_services",
    "healthcare_business",
    "b2b_sales",
    "finance",
    "advertising",
    "recurring_service_business",
    "ecommerce",
    "hvac",
    "roofing",
    "plumbing",
    "electrical",
    "landscaping",
    "pest_control",
    "legal",
    "dental",
    "recruiting",
    "saas",
    "ecommerce_retail",
)
SEMANTIC_LATTICE_COMPONENTS: tuple[SemanticLatticeComponent, ...] = (
    SemanticLatticeComponent(
        component_id="shared_business", version="1.0.0", source_reference="Ajenda shared business vocabulary"
    ),
    SemanticLatticeComponent(
        component_id="gtm.core",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda shared GTM vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="local_service_business",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda local-service domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="field_service",
        version="1.0.0",
        parents=("local_service_business",),
        source_reference="Ajenda field-service domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="professional_services",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda professional-services domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="healthcare_business",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda healthcare-business domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="b2b_sales",
        version="1.0.0",
        parents=("gtm.core",),
        source_reference="Ajenda B2B-sales domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="finance",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda finance vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="advertising",
        version="1.0.0",
        parents=("gtm.core",),
        source_reference="Ajenda advertising domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="recurring_service_business",
        version="1.0.0",
        parents=("local_service_business",),
        source_reference="Ajenda recurring-service domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="ecommerce",
        version="1.0.0",
        parents=("shared_business",),
        source_reference="Ajenda e-commerce domain vocabulary",
    ),
    SemanticLatticeComponent(
        component_id="hvac",
        version="1.0.0",
        parents=("field_service", "recurring_service_business"),
        source_reference="Ajenda HVAC industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="roofing",
        version="1.0.0",
        parents=("field_service",),
        source_reference="Ajenda roofing industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="plumbing",
        version="1.0.0",
        parents=("field_service",),
        source_reference="Ajenda plumbing industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="electrical",
        version="1.0.0",
        parents=("field_service",),
        source_reference="Ajenda electrical industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="landscaping",
        version="1.0.0",
        parents=("field_service",),
        source_reference="Ajenda landscaping industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="pest_control",
        version="1.0.0",
        parents=("field_service", "recurring_service_business"),
        source_reference="Ajenda pest-control industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="legal",
        version="1.0.0",
        parents=("professional_services",),
        source_reference="Ajenda legal industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="dental",
        version="1.0.0",
        parents=("healthcare_business", "local_service_business"),
        source_reference="Ajenda dental industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="recruiting",
        version="1.0.0",
        parents=("professional_services", "b2b_sales"),
        source_reference="Ajenda recruiting industry overlay",
    ),
    SemanticLatticeComponent(
        component_id="saas", version="1.0.0", parents=("b2b_sales",), source_reference="Ajenda SaaS industry overlay"
    ),
    SemanticLatticeComponent(
        component_id="ecommerce_retail",
        version="1.0.0",
        parents=("ecommerce",),
        source_reference="Ajenda e-commerce retail overlay",
    ),
)
_LATTICE_COMPONENTS_BY_ID = {item.component_id: item for item in SEMANTIC_LATTICE_COMPONENTS}
_INDUSTRY_COMPONENT_TERMS = {
    "hvac": "hvac",
    "roofing": "roofing",
    "plumbing": "plumbing",
    "electrical": "electrical",
    "landscaping": "landscaping",
    "pest control": "pest_control",
    "legal": "legal",
    "law firm": "legal",
    "dental": "dental",
    "dentist": "dental",
    "recruiting": "recruiting",
    "staffing": "recruiting",
    "saas": "saas",
    "software": "saas",
    "e-commerce": "ecommerce_retail",
    "ecommerce": "ecommerce_retail",
    "retail": "ecommerce_retail",
    "advertising": "advertising",
    "ads": "advertising",
    "paid media": "advertising",
    "ad campaign": "advertising",
}
_COMPONENT_DOMAIN_ALIASES = {
    "gtm": "gtm.core",
    "service_business": "local_service_business",
    "b2b_software": "saas",
}
_COMPONENT_JOB_HINTS: dict[str, tuple[str, ...]] = {
    "gtm.core": (
        "research.discover_prospects",
        "research.observe_sources",
        "sales.qualify_prospects",
        "gtm.enrich_contacts",
        "email.prepare_outreach",
        "crm.read_records",
    ),
    "local_service_business": ("research.discover_prospects", "research.observe_sources", "sales.qualify_prospects"),
    "field_service": ("research.discover_prospects", "research.observe_sources", "sales.qualify_prospects"),
    "professional_services": ("research.discover_prospects", "research.observe_sources", "sales.qualify_prospects"),
    "healthcare_business": ("research.discover_prospects", "research.observe_sources", "sales.qualify_prospects"),
    "b2b_sales": (
        "research.discover_prospects",
        "research.observe_sources",
        "sales.qualify_prospects",
        "crm.read_records",
    ),
    "advertising": ("research.synthesize_report", "analysis.evaluate_goal_progress"),
    "recurring_service_business": (
        "research.discover_prospects",
        "sales.qualify_prospects",
        "crm.pipeline_maintenance",
    ),
    "ecommerce": ("research.synthesize_report", "analysis.evaluate_goal_progress", "crm.read_records"),
}


def _validate_aliases() -> None:
    """Fail closed if shared vocabulary introduces an ambiguous alias."""

    seen: dict[str, str] = {}
    for concept in ALL_SEMANTIC_CONCEPTS:
        for alias in (concept.concept_id, concept.display_name, *concept.aliases):
            normalized = normalize_concept_text(alias)
            prior = seen.get(normalized)
            if prior is not None and prior != concept.concept_id:
                raise ValueError(f"semantic alias conflict: {normalized!r} maps to {prior} and {concept.concept_id}")
            seen[normalized] = concept.concept_id


_validate_aliases()


def _compose_lattice_components(requested: set[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Expand requested components through explicit multi-parent inheritance."""

    expanded: set[str] = set()
    conflicts: list[str] = []

    def visit(component_id: str, trail: tuple[str, ...] = ()) -> None:
        if component_id in expanded:
            return
        component = _LATTICE_COMPONENTS_BY_ID.get(component_id)
        if component is None:
            conflicts.append(f"unknown semantic lattice component: {component_id}")
            return
        if component_id in trail:
            conflicts.append(f"semantic lattice parent cycle: {' -> '.join((*trail, component_id))}")
            return
        for parent in component.parents:
            visit(parent, (*trail, component_id))
        expanded.add(component_id)

    for component_id in requested:
        visit(component_id)
    ordered = tuple(component for component in _COMPONENT_ORDER if component in expanded)
    return ordered, tuple(dict.fromkeys(conflicts))


def build_semantic_selection(
    *,
    instruction: str,
    requested_outcomes: Iterable[str],
    selected_job_keys: Iterable[str],
    tenant_overrides: Iterable[TenantSemanticOverride] = (),
    tenant_override_conflicts: Iterable[str] = (),
) -> SemanticSelection:
    """Legacy compatibility resolver; canonical runtime selection lives in ``semantic_lattice.resolver``.

    Historical imports continue to receive the original behavior while new
    composition code uses the modular resolver.  Neither path grants runtime
    authority.
    """

    selected = tuple(dict.fromkeys(str(item) for item in selected_job_keys if str(item).strip()))
    selected_set = set(selected)
    concepts: list[str] = []
    terms: list[str] = []
    bindings: list[SemanticJobBinding] = []
    conflicts: list[str] = []
    tenant_override_items = tuple(tenant_overrides)
    conflicts.extend(str(item) for item in tenant_override_conflicts)
    tenant_aliases: dict[str, str] = {}
    for override in tenant_override_items:
        if override.concept_id not in SHARED_BUSINESS_CONCEPTS_BY_ID:
            conflicts.append(f"tenant semantic override references unknown concept: {override.concept_id}")
            continue
        for alias in override.aliases:
            normalized_alias = normalize_concept_text(alias)
            shared_concept_id = _ALIASES.get(normalized_alias)
            if shared_concept_id is not None and shared_concept_id != override.concept_id:
                conflicts.append(
                    f"tenant semantic alias conflict: {normalized_alias!r} maps to "
                    f"shared concept {shared_concept_id} and tenant concept {override.concept_id}"
                )
                continue
            prior = tenant_aliases.get(normalized_alias)
            if prior is not None and prior != override.concept_id:
                conflicts.append(
                    f"tenant semantic alias conflict: {normalized_alias!r} maps to {prior} and {override.concept_id}"
                )
                continue
            tenant_aliases[normalized_alias] = override.concept_id
    component_candidates: set[str] = {"shared_business"}
    if requested_outcomes or selected:
        component_candidates.add("gtm.core")

    for raw_outcome in requested_outcomes:
        outcome = normalize_concept_text(str(raw_outcome))
        mapping = _OUTCOME_CONCEPTS.get(outcome)
        if mapping is None:
            continue
        concept_id, expected = mapping
        concept = SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id]
        component_candidates.update(concept.applicable_domains)
        if concept_id not in concepts:
            concepts.append(concept_id)
        binding_status: Literal["satisfied", "conflict"] = (
            "satisfied" if set(expected).issubset(selected_set) else "conflict"
        )
        if binding_status == "conflict":
            conflicts.append(
                f"semantic concept {concept_id} expected jobs {','.join(expected)}; "
                f"selected {','.join(selected) or 'none'}"
            )
        bindings.append(
            SemanticJobBinding(
                concept_id=concept_id,
                concept_version=concept.version,
                source="requested_outcome",
                expected_job_keys=expected,
                selected_job_keys=selected,
                status=binding_status,
            )
        )

    normalized_instruction = normalize_concept_text(instruction)
    for term, component in _INDUSTRY_COMPONENT_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized_instruction):
            component_candidates.add(component)
    for concept in ALL_SEMANTIC_CONCEPTS:
        candidates = (concept.concept_id, concept.display_name, *concept.aliases)
        matched = next(
            (
                term
                for term in candidates
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(normalize_concept_text(term))}(?![a-z0-9])", normalized_instruction
                )
            ),
            None,
        )
        if matched is None:
            continue
        if concept.concept_id not in concepts:
            concepts.append(concept.concept_id)
        normalized_match = normalize_concept_text(matched)
        if normalized_match not in terms:
            terms.append(normalized_match)

    for alias, concept_id in tenant_aliases.items():
        if not re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_instruction):
            continue
        if concept_id not in concepts:
            concepts.append(concept_id)
        if alias not in terms:
            terms.append(alias)
        concept = SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id]
        component_candidates.update(concept.applicable_domains)

    normalized_components = {_COMPONENT_DOMAIN_ALIASES.get(component, component) for component in component_candidates}
    active_components, component_conflicts = _compose_lattice_components(normalized_components)
    conflicts.extend(component_conflicts)
    concept_provenance = tuple(SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id] for concept_id in concepts)
    component_job_guidance = tuple(
        SemanticComponentJobGuidance(
            component_id=component,
            candidate_job_keys=_COMPONENT_JOB_HINTS[component],
            selected_job_keys=selected,
            status=("satisfied" if set(selected).intersection(_COMPONENT_JOB_HINTS[component]) else "informational"),
        )
        for component in active_components
        if component in _COMPONENT_JOB_HINTS
    )
    return SemanticSelection(
        active_components=active_components,
        active_component_provenance=tuple(_LATTICE_COMPONENTS_BY_ID[component] for component in active_components),
        component_conflicts=component_conflicts,
        component_job_guidance=component_job_guidance,
        concepts=tuple(concepts),
        concept_provenance=concept_provenance,
        tenant_overrides=tenant_override_items,
        matched_terms=tuple(terms),
        bindings=tuple(bindings),
        conflicts=tuple(dict.fromkeys(conflicts)),
    )


def resolve_shared_concept(value: str) -> SemanticConcept | None:
    """Resolve an exact canonical ID or alias; unknown terms remain unresolved."""

    concept_id = _ALIASES.get(normalize_concept_text(value))
    return SHARED_BUSINESS_CONCEPTS_BY_ID.get(concept_id) if concept_id else None

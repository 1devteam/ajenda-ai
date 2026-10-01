"""Shared business vocabulary for declarative mission interpretation.

Concepts in this module normalize language only. They do not select jobs, resolve
abilities, grant authority, resolve credentials, or execute provider work.
"""

from __future__ import annotations

import re
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

SHARED_BUSINESS_CONCEPTS_BY_ID = {concept.concept_id: concept for concept in SHARED_BUSINESS_CONCEPTS}
_ALIASES = {
    normalize_concept_text(alias): concept.concept_id
    for concept in SHARED_BUSINESS_CONCEPTS
    for alias in (concept.concept_id, concept.display_name, *concept.aliases)
}


def resolve_shared_concept(value: str) -> SemanticConcept | None:
    """Resolve an exact canonical ID or alias; unknown terms remain unresolved."""

    concept_id = _ALIASES.get(normalize_concept_text(value))
    return SHARED_BUSINESS_CONCEPTS_BY_ID.get(concept_id) if concept_id else None

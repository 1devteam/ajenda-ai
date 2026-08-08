"""Business Ontology Slice 1 — core identities and commercial spine.

Extracted from concepts that already repeat across light_crm, sales/GTM,
record stores, and evidence/decision surfaces. Not an academic ontology.

Storage note (honest): light_crm currently maps lead→contact, company→account,
deal→opportunity on upsert. Canonical types still distinguish *lead* as a
commercial concept so higher-order reasoning is not forced into contact-only
language; storage projection remains a vertical concern until a later slice.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BUSINESS_OBJECT_SCHEMA_VERSION = 1


class BusinessObjectType(StrEnum):
    """Canonical business object types for Ontology Slice 1."""

    PERSON = "person"
    ORGANIZATION = "organization"
    ACCOUNT = "account"
    CONTACT = "contact"
    LEAD = "lead"
    OPPORTUNITY = "opportunity"


CANONICAL_BUSINESS_OBJECT_TYPES: frozenset[str] = frozenset(t.value for t in BusinessObjectType)

# Synonyms observed in light_crm / sales inputs → canonical type.
# Does not mutate storage; callers may normalize for reasoning surfaces.
OBJECT_TYPE_ALIASES: dict[str, BusinessObjectType] = {
    "person": BusinessObjectType.PERSON,
    "individual": BusinessObjectType.PERSON,
    "organization": BusinessObjectType.ORGANIZATION,
    "org": BusinessObjectType.ORGANIZATION,
    "company": BusinessObjectType.ORGANIZATION,
    "companies": BusinessObjectType.ORGANIZATION,
    "account": BusinessObjectType.ACCOUNT,
    "accounts": BusinessObjectType.ACCOUNT,
    "contact": BusinessObjectType.CONTACT,
    "contacts": BusinessObjectType.CONTACT,
    "lead": BusinessObjectType.LEAD,
    "leads": BusinessObjectType.LEAD,
    "prospect": BusinessObjectType.LEAD,
    "prospects": BusinessObjectType.LEAD,
    "opportunity": BusinessObjectType.OPPORTUNITY,
    "opportunities": BusinessObjectType.OPPORTUNITY,
    "deal": BusinessObjectType.OPPORTUNITY,
    "deals": BusinessObjectType.OPPORTUNITY,
}


class BusinessObjectRef(BaseModel):
    """Stable reference to a business object instance.

    object_id is opaque tenant-scoped identity (CRM id, internal record id, etc.).
    This model does not resolve or load the object.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    object_type: BusinessObjectType
    object_id: str = Field(min_length=1, max_length=160)

    @field_validator("object_id")
    @classmethod
    def normalize_object_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("object_id must be non-empty")
        return normalized


class RelationshipSpec(BaseModel):
    """Declarative relationship between canonical object types (documentation + validation aid)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    from_type: BusinessObjectType
    to_type: BusinessObjectType
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    description: str = Field(min_length=1, max_length=500)


class OntologyRelationshipSpec(BaseModel):
    """Declarative relationship across ontology concepts (objects, goals, evidence, etc.).

    Endpoints are stable string labels (e.g. "Goal", "Kpi", "Evidence") so
    commercial and evaluation relationships are not forced into BusinessObjectType.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    from_endpoint: str = Field(min_length=1, max_length=80)
    to_endpoint: str = Field(min_length=1, max_length=80)
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    description: str = Field(min_length=1, max_length=500)


RELATIONSHIP_SPECS: tuple[RelationshipSpec, ...] = (
    RelationshipSpec(
        name="contact_belongs_to_account",
        from_type=BusinessObjectType.CONTACT,
        to_type=BusinessObjectType.ACCOUNT,
        cardinality="many_to_one",
        description="A contact is associated with at most one primary account (light_crm account_id).",
    ),
    RelationshipSpec(
        name="contact_is_person_in_context",
        from_type=BusinessObjectType.CONTACT,
        to_type=BusinessObjectType.PERSON,
        cardinality="many_to_one",
        description="A contact is a person known in a business relationship context.",
    ),
    RelationshipSpec(
        name="account_is_organization_view",
        from_type=BusinessObjectType.ACCOUNT,
        to_type=BusinessObjectType.ORGANIZATION,
        cardinality="one_to_one",
        description="An account is the commercial view of an organization entity.",
    ),
    RelationshipSpec(
        name="opportunity_concerns_account",
        from_type=BusinessObjectType.OPPORTUNITY,
        to_type=BusinessObjectType.ACCOUNT,
        cardinality="many_to_one",
        description="An opportunity concerns one account (light_crm account_id).",
    ),
    RelationshipSpec(
        name="opportunity_involves_contact",
        from_type=BusinessObjectType.OPPORTUNITY,
        to_type=BusinessObjectType.CONTACT,
        cardinality="many_to_many",
        description="An opportunity may involve one or more contacts (light_crm contact_id primary).",
    ),
    RelationshipSpec(
        name="lead_targets_account",
        from_type=BusinessObjectType.LEAD,
        to_type=BusinessObjectType.ACCOUNT,
        cardinality="many_to_one",
        description="A lead may target an account/organization for a potential relationship.",
    ),
    RelationshipSpec(
        name="lead_associated_contact",
        from_type=BusinessObjectType.LEAD,
        to_type=BusinessObjectType.CONTACT,
        cardinality="many_to_one",
        description="A lead may be associated with a contact person; storage may still project lead→contact.",
    ),
)


def canonicalize_object_type(raw: str) -> BusinessObjectType:
    """Map a raw type string (including aliases) to a canonical BusinessObjectType."""

    key = raw.strip().lower()
    if not key:
        raise ValueError("object type must be non-empty")
    mapped = OBJECT_TYPE_ALIASES.get(key)
    if mapped is None:
        raise ValueError(f"unknown business object type: {raw!r}")
    return mapped


def is_canonical_object_type(raw: str) -> bool:
    """Return True if raw is already a canonical type value."""

    return raw.strip().lower() in CANONICAL_BUSINESS_OBJECT_TYPES

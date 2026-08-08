"""Business ontology contracts (Slice 1).

Shared vocabulary and reference types for business objects that already
repeat across abilities. Does not execute tools, persist records, or wire
composition/runtime.
"""

from backend.services.ontology.types import (
    BUSINESS_OBJECT_SCHEMA_VERSION,
    CANONICAL_BUSINESS_OBJECT_TYPES,
    OBJECT_TYPE_ALIASES,
    RELATIONSHIP_SPECS,
    BusinessObjectRef,
    BusinessObjectType,
    RelationshipSpec,
    canonicalize_object_type,
    is_canonical_object_type,
)

__all__ = [
    "BUSINESS_OBJECT_SCHEMA_VERSION",
    "CANONICAL_BUSINESS_OBJECT_TYPES",
    "OBJECT_TYPE_ALIASES",
    "RELATIONSHIP_SPECS",
    "BusinessObjectRef",
    "BusinessObjectType",
    "RelationshipSpec",
    "canonicalize_object_type",
    "is_canonical_object_type",
]

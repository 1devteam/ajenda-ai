"""Business ontology contracts.

Slice 1 — identities and commercial spine (BusinessObjectType / Ref).
Slice 2 — commercial state: Goal, KPI, BusinessStateSnapshot, BusinessEvent.

Does not execute tools, persist records, or wire composition/runtime.
"""

from backend.services.ontology.commercial_state import (
    COMMERCIAL_RELATIONSHIP_SPECS,
    COMMERCIAL_STATE_SCHEMA_VERSION,
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    GoalStatus,
    Kpi,
    KpiDirection,
)
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
    "COMMERCIAL_RELATIONSHIP_SPECS",
    "COMMERCIAL_STATE_SCHEMA_VERSION",
    "OBJECT_TYPE_ALIASES",
    "RELATIONSHIP_SPECS",
    "BusinessEvent",
    "BusinessObjectRef",
    "BusinessObjectType",
    "BusinessStateSnapshot",
    "Goal",
    "GoalStatus",
    "Kpi",
    "KpiDirection",
    "RelationshipSpec",
    "canonicalize_object_type",
    "is_canonical_object_type",
]

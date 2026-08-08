"""Business ontology contracts.

Slice 1 — identities and commercial spine (BusinessObjectType / Ref).
Slice 2 — commercial state: Goal, KPI, BusinessStateSnapshot, BusinessEvent.
Evaluation Intelligence — EvaluationResult and deterministic assessors.

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
from backend.services.ontology.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EvaluationResult,
    GapKind,
    GoalProgressStatus,
    KpiEvaluation,
    ProgressGap,
    StateAttributeChange,
    StateComparison,
    compare_state_snapshots,
    evaluate_goal_progress,
    evaluate_kpi,
)
from backend.services.ontology.types import (
    BUSINESS_OBJECT_SCHEMA_VERSION,
    CANONICAL_BUSINESS_OBJECT_TYPES,
    OBJECT_TYPE_ALIASES,
    RELATIONSHIP_SPECS,
    BusinessObjectRef,
    BusinessObjectType,
    OntologyRelationshipSpec,
    RelationshipSpec,
    canonicalize_object_type,
    is_canonical_object_type,
)

__all__ = [
    "BUSINESS_OBJECT_SCHEMA_VERSION",
    "CANONICAL_BUSINESS_OBJECT_TYPES",
    "COMMERCIAL_RELATIONSHIP_SPECS",
    "COMMERCIAL_STATE_SCHEMA_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "OBJECT_TYPE_ALIASES",
    "RELATIONSHIP_SPECS",
    "BusinessEvent",
    "BusinessObjectRef",
    "BusinessObjectType",
    "BusinessStateSnapshot",
    "EvaluationResult",
    "GapKind",
    "Goal",
    "GoalProgressStatus",
    "GoalStatus",
    "Kpi",
    "KpiDirection",
    "KpiEvaluation",
    "OntologyRelationshipSpec",
    "ProgressGap",
    "RelationshipSpec",
    "StateAttributeChange",
    "StateComparison",
    "canonicalize_object_type",
    "compare_state_snapshots",
    "evaluate_goal_progress",
    "evaluate_kpi",
    "is_canonical_object_type",
]

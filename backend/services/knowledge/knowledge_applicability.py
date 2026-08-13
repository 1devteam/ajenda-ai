"""Deterministic current-context applicability for semantically retrieved knowledge.

Semantic relevance is not applicability. This layer evaluates only typed current
condition assertions; it does not infer condition truth, retrieve knowledge,
mutate lifecycle state, make decisions, or execute work.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from backend.services.knowledge.knowledge_retrieval import (
    KnowledgeRetrievalQuery,
    KnowledgeRetrievalResult,
    RetrievedKnowledgeMatch,
)
from backend.services.ontology.commercial_state import (
    GoalSemanticComparison,
    GoalSemanticComparisonStatus,
    GoalSemanticSignature,
)
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.types import (
    BusinessObjectRef,
    BusinessObjectSemanticSignature,
    business_object_semantic_signature,
)

KNOWLEDGE_APPLICABILITY_ALGORITHM = "knowledge_applicability_v1"


class ContextConditionState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class KnowledgeApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    PARTIALLY_APPLICABLE = "partially_applicable"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    INVALIDATED = "invalidated"


class ContextConditionAssertion(BaseModel):
    """One already-resolved current assertion for an opaque canonical token."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    condition_key: str
    state: ContextConditionState
    subject_refs: tuple[BusinessObjectRef, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    observed_at: datetime
    verification_basis: ObservationVerificationBasis

    @field_validator("condition_key")
    @classmethod
    def validate_condition_key(cls, value: str) -> str:
        if not value or value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("condition_key must be a non-empty canonical token without whitespace")
        return value

    @field_validator("subject_refs")
    @classmethod
    def canonicalize_subject_refs(cls, values: tuple[BusinessObjectRef, ...]) -> tuple[BusinessObjectRef, ...]:
        identities = {(item.object_type.value, item.object_id): item for item in values}
        return tuple(identities[key] for key in sorted(identities))

    @field_validator("evidence_ids")
    @classmethod
    def canonicalize_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item != item.strip() for item in values):
            raise ValueError("evidence_ids must contain non-empty canonical identities")
        return tuple(sorted(set(values)))

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class KnowledgeApplicabilityContext(BaseModel):
    """Typed present situation; generic business-state attributes are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    subject_refs: tuple[BusinessObjectRef, ...]
    subject_semantic_signatures: tuple[BusinessObjectSemanticSignature, ...]
    goal_semantic_signature: GoalSemanticSignature
    condition_assertions: tuple[ContextConditionAssertion, ...] = ()
    evaluated_at: datetime

    @field_validator("subject_refs")
    @classmethod
    def canonicalize_subject_refs(cls, values: tuple[BusinessObjectRef, ...]) -> tuple[BusinessObjectRef, ...]:
        identities = {(item.object_type.value, item.object_id): item for item in values}
        return tuple(identities[key] for key in sorted(identities))

    @field_validator("subject_semantic_signatures")
    @classmethod
    def canonicalize_subject_semantics(
        cls, values: tuple[BusinessObjectSemanticSignature, ...]
    ) -> tuple[BusinessObjectSemanticSignature, ...]:
        return tuple(sorted(set(values), key=lambda item: item.object_type.value))

    @field_validator("goal_semantic_signature")
    @classmethod
    def canonicalize_goal(cls, value: GoalSemanticSignature) -> GoalSemanticSignature:
        return GoalSemanticSignature(
            objective_key=value.objective_key,
            kpis=tuple(
                sorted(
                    set(value.kpis),
                    key=lambda item: (item.metric, item.direction.value, item.normalized_unit or ""),
                )
            ),
        )

    @field_validator("condition_assertions")
    @classmethod
    def canonicalize_assertions(
        cls, values: tuple[ContextConditionAssertion, ...]
    ) -> tuple[ContextConditionAssertion, ...]:
        keys = [item.condition_key for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("condition_assertions must contain one resolved assertion per condition_key")
        return tuple(sorted(values, key=lambda item: item.condition_key))

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_subject_coherence(self) -> KnowledgeApplicabilityContext:
        if not self.subject_refs or not self.subject_semantic_signatures:
            raise ValueError("current context requires exact and semantic subjects")
        derived = {business_object_semantic_signature(item) for item in self.subject_refs}
        if derived != set(self.subject_semantic_signatures):
            raise ValueError("exact subject types disagree with subject semantic signatures")
        exact = {(item.object_type, item.object_id) for item in self.subject_refs}
        for assertion in self.condition_assertions:
            asserted = {(item.object_type, item.object_id) for item in assertion.subject_refs}
            if not asserted.issubset(exact):
                raise ValueError("condition assertion subjects fall outside the current context")
        return self


class KnowledgeApplicabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    applicability_id: str
    retrieval_id: str
    proposition_key: str
    knowledge_ids: tuple[str, ...]
    status: KnowledgeApplicabilityStatus
    goal_comparison: GoalSemanticComparison
    required_scope_conditions: tuple[str, ...]
    satisfied_scope_conditions: tuple[str, ...]
    unsatisfied_scope_conditions: tuple[str, ...]
    unknown_scope_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    active_invalidation_conditions: tuple[str, ...]
    cleared_invalidation_conditions: tuple[str, ...]
    unknown_invalidation_conditions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    epistemic_limits: tuple[str, ...]
    evaluated_at: datetime
    algorithm: str = KNOWLEDGE_APPLICABILITY_ALGORITHM
    is_policy: Literal[False] = False
    is_decision_support: Literal[False] = False
    is_decision_instruction: Literal[False] = False


class KnowledgeApplicabilityResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    resolution_id: str
    retrieval: KnowledgeRetrievalResult
    evaluations: tuple[KnowledgeApplicabilityResult, ...]
    referenced_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    algorithm: str = KNOWLEDGE_APPLICABILITY_ALGORITHM
    is_policy: Literal[False] = False
    is_decision_support: Literal[False] = False
    is_decision_instruction: Literal[False] = False


def _identity(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


def validate_context_for_query(*, query: KnowledgeRetrievalQuery, context: KnowledgeApplicabilityContext) -> None:
    """Reject a production request whose two owner-semantic views disagree."""

    if query.subject_semantic_signatures != context.subject_semantic_signatures:
        raise ValueError("applicability context subjects disagree with retrieval query")
    if query.goal_semantic_signature != context.goal_semantic_signature:
        raise ValueError("applicability context goal disagrees with retrieval query")


def evaluate_knowledge_applicability(
    *, retrieval_id: str, match: RetrievedKnowledgeMatch, context: KnowledgeApplicabilityContext
) -> KnowledgeApplicabilityResult:
    """Evaluate one authoritative semantic match using exact condition identities."""

    if set(match.proposition.subject_semantic_signatures) != set(context.subject_semantic_signatures):
        raise ValueError("applicability context subjects disagree with retrieved proposition")
    assertions = {item.condition_key: item for item in context.condition_assertions}
    scope = tuple(sorted(set(match.proposition.scope_conditions)))
    invalidations = tuple(sorted(set(match.proposition.invalidation_conditions)))
    satisfied = tuple(
        key for key in scope if assertions.get(key) and assertions[key].state == ContextConditionState.ACTIVE
    )
    unsatisfied = tuple(
        key for key in scope if assertions.get(key) and assertions[key].state == ContextConditionState.INACTIVE
    )
    unknown_scope = tuple(
        key for key in scope if assertions.get(key) is None or assertions[key].state == ContextConditionState.UNKNOWN
    )
    active_invalidations = tuple(
        key for key in invalidations if assertions.get(key) and assertions[key].state == ContextConditionState.ACTIVE
    )
    cleared_invalidations = tuple(
        key for key in invalidations if assertions.get(key) and assertions[key].state == ContextConditionState.INACTIVE
    )
    unknown_invalidations = tuple(
        key
        for key in invalidations
        if assertions.get(key) is None or assertions[key].state == ContextConditionState.UNKNOWN
    )

    if active_invalidations:
        status = KnowledgeApplicabilityStatus.INVALIDATED
        status_reason = "contextual_invalidation_condition_active"
    elif unsatisfied:
        status = KnowledgeApplicabilityStatus.NOT_APPLICABLE
        status_reason = "required_scope_condition_inactive"
    elif unknown_scope or unknown_invalidations:
        status = KnowledgeApplicabilityStatus.INSUFFICIENT_CONTEXT
        status_reason = "required_condition_truth_unknown"
    elif match.goal_comparison.status == GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT:
        status = KnowledgeApplicabilityStatus.PARTIALLY_APPLICABLE
        status_reason = "partial_goal_equivalence_caps_applicability"
    elif match.goal_comparison.status == GoalSemanticComparisonStatus.EQUIVALENT:
        status = KnowledgeApplicabilityStatus.APPLICABLE
        status_reason = "all_applicability_requirements_proven"
    else:  # Retrieval must never emit any other comparison status as a match.
        raise ValueError("retrieved match has ineligible goal comparison")

    relevant = tuple(assertions[key] for key in sorted(set(scope) | set(invalidations)) if key in assertions)
    evidence_ids = tuple(sorted({evidence_id for item in relevant for evidence_id in item.evidence_ids}))
    limits = set(match.epistemic_limits) - {
        "scope_conditions_not_evaluated",
        "invalidation_conditions_not_evaluated",
    }
    if unknown_scope:
        limits.add("scope_condition_truth_unknown")
    if unknown_invalidations:
        limits.add("invalidation_condition_truth_unknown")
    if match.goal_comparison.status == GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT:
        limits.add("partial_goal_equivalence")
    if any(
        item.verification_basis in {ObservationVerificationBasis.CALLER_ASSERTED, ObservationVerificationBasis.UNKNOWN}
        for item in relevant
    ):
        limits.add("weak_condition_assertion_verification_basis")
    reason_codes = tuple(sorted(set(match.reason_codes) | {status_reason}))
    identity_payload = {
        "algorithm": KNOWLEDGE_APPLICABILITY_ALGORITHM,
        "retrieval_id": retrieval_id,
        "proposition_key": match.proposition.proposition_key,
        "knowledge_ids": sorted(item.knowledge_id for item in match.authoritative_artifacts),
        "evaluated_at": context.evaluated_at.isoformat(),
        "subject_refs": [item.model_dump(mode="json") for item in context.subject_refs],
        "subject_semantic_signatures": [item.model_dump(mode="json") for item in context.subject_semantic_signatures],
        "goal_semantic_signature": context.goal_semantic_signature.model_dump(mode="json"),
        "assertions": [item.model_dump(mode="json") for item in relevant],
    }
    return KnowledgeApplicabilityResult(
        applicability_id=_identity("knowledge-applicability-v1", identity_payload),
        retrieval_id=retrieval_id,
        proposition_key=match.proposition.proposition_key,
        knowledge_ids=tuple(sorted(item.knowledge_id for item in match.authoritative_artifacts)),
        status=status,
        goal_comparison=match.goal_comparison,
        required_scope_conditions=scope,
        satisfied_scope_conditions=satisfied,
        unsatisfied_scope_conditions=unsatisfied,
        unknown_scope_conditions=unknown_scope,
        invalidation_conditions=invalidations,
        active_invalidation_conditions=active_invalidations,
        cleared_invalidation_conditions=cleared_invalidations,
        unknown_invalidation_conditions=unknown_invalidations,
        evidence_ids=evidence_ids,
        reason_codes=reason_codes,
        epistemic_limits=tuple(sorted(limits)),
        evaluated_at=context.evaluated_at,
    )


def resolve_knowledge_applicability(
    *, retrieval: KnowledgeRetrievalResult, context: KnowledgeApplicabilityContext
) -> KnowledgeApplicabilityResolutionResult:
    """Evaluate all matches from one canonical Retrieval result in memory."""

    validate_context_for_query(query=retrieval.query, context=context)
    evaluations = tuple(
        evaluate_knowledge_applicability(retrieval_id=retrieval.retrieval_id, match=match, context=context)
        for match in retrieval.matches
    )
    referenced = tuple(sorted({item for evaluation in evaluations for item in evaluation.evidence_ids}))
    reasons = retrieval.reason_codes if not evaluations else ()
    limits = tuple(sorted({item for evaluation in evaluations for item in evaluation.epistemic_limits}))
    payload = {
        "algorithm": KNOWLEDGE_APPLICABILITY_ALGORITHM,
        "retrieval_id": retrieval.retrieval_id,
        "applicability_ids": sorted(item.applicability_id for item in evaluations),
    }
    return KnowledgeApplicabilityResolutionResult(
        resolution_id=_identity("knowledge-applicability-resolution-v1", payload),
        retrieval=retrieval,
        evaluations=evaluations,
        referenced_evidence_ids=referenced,
        reason_codes=reasons,
        epistemic_limits=limits,
    )

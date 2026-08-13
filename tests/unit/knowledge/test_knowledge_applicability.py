from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.services.knowledge import (
    ContextConditionAssertion,
    ContextConditionState,
    CurrentKnowledgeState,
    KnowledgeApplicabilityContext,
    KnowledgeApplicabilityStatus,
    KnowledgeLifecycleStatus,
    KnowledgeRetrievalInspectionTrace,
    KnowledgeRetrievalQuery,
    KnowledgeRetrievalResult,
    evaluate_knowledge_applicability,
    match_current_knowledge,
    resolve_knowledge_applicability,
)
from backend.services.ontology.commercial_state import (
    GoalSemanticComparison,
    GoalSemanticComparisonStatus,
    GoalSemanticSignature,
)
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from tests.unit.ontology.test_knowledge_qualification import candidate

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _match(*, scope=("segment:smb",), invalidation=("pricing_model_changed",)):
    qualification = qualify_pattern_knowledge(candidate(latest=NOW))
    assert qualification.qualified_knowledge is not None
    artifact = qualification.qualified_knowledge
    proposition = artifact.proposition.model_copy(
        update={"scope_conditions": scope, "invalidation_conditions": invalidation}
    )
    artifact = artifact.model_copy(update={"proposition": proposition})
    state = CurrentKnowledgeState(
        proposition_key=proposition.proposition_key,
        lifecycle_status=KnowledgeLifecycleStatus.ACTIVE,
        evaluation_frontier=NOW,
        authoritative_qualification_ids=(artifact.qualification_id,),
        authoritative_knowledge_ids=(artifact.knowledge_id,),
        historical_qualification_count=1,
        lifecycle_projection_id="knowledge-lifecycle-v1:test",
    )
    query = KnowledgeRetrievalQuery(
        subject_semantic_signatures=proposition.subject_semantic_signatures,
        goal_semantic_signature=GoalSemanticSignature(objective_key=proposition.objective_key),
    )
    match = match_current_knowledge(query=query, current_state=state, artifacts=(artifact,))
    assert match is not None
    return query, match


def _assertion(
    key,
    state,
    *,
    basis=ObservationVerificationBasis.INDEPENDENTLY_VERIFIED,
    evidence=(),
    observed_at=NOW,
):
    return ContextConditionAssertion(
        condition_key=key,
        state=state,
        subject_refs=(BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-123"),),
        evidence_ids=evidence,
        observed_at=observed_at,
        verification_basis=basis,
    )


def _context(query, *assertions):
    return KnowledgeApplicabilityContext(
        subject_refs=(BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-123"),),
        subject_semantic_signatures=query.subject_semantic_signatures,
        goal_semantic_signature=query.goal_semantic_signature,
        condition_assertions=assertions,
        evaluated_at=NOW,
    )


@pytest.mark.parametrize(
    ("scope_state", "invalidation_state", "expected"),
    [
        (ContextConditionState.ACTIVE, ContextConditionState.INACTIVE, KnowledgeApplicabilityStatus.APPLICABLE),
        (ContextConditionState.INACTIVE, ContextConditionState.INACTIVE, KnowledgeApplicabilityStatus.NOT_APPLICABLE),
        (
            ContextConditionState.UNKNOWN,
            ContextConditionState.INACTIVE,
            KnowledgeApplicabilityStatus.INSUFFICIENT_CONTEXT,
        ),
        (
            ContextConditionState.ACTIVE,
            ContextConditionState.UNKNOWN,
            KnowledgeApplicabilityStatus.INSUFFICIENT_CONTEXT,
        ),
        (ContextConditionState.ACTIVE, ContextConditionState.ACTIVE, KnowledgeApplicabilityStatus.INVALIDATED),
        (ContextConditionState.INACTIVE, ContextConditionState.ACTIVE, KnowledgeApplicabilityStatus.INVALIDATED),
    ],
)
def test_condition_truth_and_precedence_are_explicit(scope_state, invalidation_state, expected) -> None:
    query, match = _match()
    context = _context(
        query,
        _assertion("segment:smb", scope_state, evidence=("ev-scope",)),
        _assertion("pricing_model_changed", invalidation_state, evidence=("ev-invalidation",)),
    )
    result = evaluate_knowledge_applicability(retrieval_id="retrieval:test", match=match, context=context)
    assert result.status == expected
    assert result.evidence_ids == ("ev-invalidation", "ev-scope")
    assert result.is_policy is result.is_decision_support is result.is_decision_instruction is False


def test_missing_context_is_unknown_and_no_conditions_are_applicable() -> None:
    query, match = _match()
    missing = evaluate_knowledge_applicability(retrieval_id="retrieval:test", match=match, context=_context(query))
    assert missing.status == KnowledgeApplicabilityStatus.INSUFFICIENT_CONTEXT
    assert missing.unknown_scope_conditions == ("segment:smb",)
    assert missing.unknown_invalidation_conditions == ("pricing_model_changed",)

    query, match = _match(scope=(), invalidation=())
    assert (
        evaluate_knowledge_applicability(retrieval_id="retrieval:test", match=match, context=_context(query)).status
        == KnowledgeApplicabilityStatus.APPLICABLE
    )


def test_partial_goal_equivalence_caps_applicability() -> None:
    query, match = _match()
    partial = match.model_copy(
        update={
            "goal_comparison": GoalSemanticComparison(
                status=GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT,
                reason_codes=("matching_kpi_semantics_without_complete_objective_identity",),
            )
        }
    )
    result = evaluate_knowledge_applicability(
        retrieval_id="retrieval:test",
        match=partial,
        context=_context(
            query,
            _assertion("segment:smb", ContextConditionState.ACTIVE),
            _assertion("pricing_model_changed", ContextConditionState.INACTIVE),
        ),
    )
    assert result.status == KnowledgeApplicabilityStatus.PARTIALLY_APPLICABLE
    assert "partial_goal_equivalence" in result.epistemic_limits


def test_context_rejects_duplicate_conditions_and_subject_contradictions() -> None:
    query, _ = _match()
    with pytest.raises(ValidationError, match="one resolved assertion"):
        _context(
            query,
            _assertion("segment:smb", ContextConditionState.ACTIVE),
            _assertion("segment:smb", ContextConditionState.INACTIVE),
        )
    with pytest.raises(ValidationError, match="exact subject types disagree"):
        KnowledgeApplicabilityContext(
            subject_refs=(BusinessObjectRef(object_type=BusinessObjectType.ACCOUNT, object_id="acct-1"),),
            subject_semantic_signatures=query.subject_semantic_signatures,
            goal_semantic_signature=query.goal_semantic_signature,
            evaluated_at=NOW,
        )


def test_context_accepts_assertions_observed_before_evaluation() -> None:
    query, match = _match(invalidation=())
    context = _context(
        query,
        _assertion("segment:smb", ContextConditionState.ACTIVE, observed_at=NOW - timedelta(seconds=1)),
    )
    result = evaluate_knowledge_applicability(retrieval_id="retrieval:test", match=match, context=context)
    assert result.status == KnowledgeApplicabilityStatus.APPLICABLE


def test_context_accepts_assertions_observed_at_evaluation() -> None:
    query, match = _match(invalidation=())
    context = _context(query, _assertion("segment:smb", ContextConditionState.ACTIVE, observed_at=NOW))
    result = evaluate_knowledge_applicability(retrieval_id="retrieval:test", match=match, context=context)
    assert result.status == KnowledgeApplicabilityStatus.APPLICABLE


def test_context_rejects_future_assertions_before_they_can_determine_applicability() -> None:
    query, _ = _match(invalidation=())
    with pytest.raises(ValidationError, match="observation cannot occur after applicability evaluation"):
        _context(
            query,
            _assertion("segment:smb", ContextConditionState.ACTIVE, observed_at=NOW + timedelta(seconds=1)),
        )


def test_deterministic_identity_ignores_order_and_unrelated_assertions() -> None:
    query, match = _match()
    scope = _assertion("segment:smb", ContextConditionState.ACTIVE, evidence=("ev-b", "ev-a"))
    invalidation = _assertion("pricing_model_changed", ContextConditionState.INACTIVE)
    unrelated = _assertion("region:us", ContextConditionState.ACTIVE)
    first = evaluate_knowledge_applicability(
        retrieval_id="retrieval:test", match=match, context=_context(query, scope, invalidation)
    )
    reordered = evaluate_knowledge_applicability(
        retrieval_id="retrieval:test", match=match, context=_context(query, unrelated, invalidation, scope)
    )
    assert reordered == first


def test_weak_provenance_is_preserved_as_limit_without_inventing_a_trust_gate() -> None:
    query, match = _match(invalidation=())
    result = evaluate_knowledge_applicability(
        retrieval_id="retrieval:test",
        match=match,
        context=_context(
            query,
            _assertion(
                "segment:smb",
                ContextConditionState.ACTIVE,
                basis=ObservationVerificationBasis.CALLER_ASSERTED,
                evidence=(),
            ),
        ),
    )
    assert result.status == KnowledgeApplicabilityStatus.APPLICABLE
    assert result.evidence_ids == ()
    assert "weak_condition_assertion_verification_basis" in result.epistemic_limits


def test_resolution_preserves_no_match_semantics() -> None:
    query, _ = _match()
    retrieval = KnowledgeRetrievalResult(
        query=query,
        matches=(),
        candidate_proposition_count=0,
        active_proposition_count=0,
        semantic_match_count=0,
        retrieval_id="knowledge-retrieval-v1:none",
        inspection_trace=KnowledgeRetrievalInspectionTrace(),
        reason_codes=("no_current_semantic_knowledge_match",),
    )
    result = resolve_knowledge_applicability(retrieval=retrieval, context=_context(query))
    assert result.evaluations == ()
    assert result.reason_codes == ("no_current_semantic_knowledge_match",)

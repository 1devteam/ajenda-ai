from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.knowledge import (
    CurrentKnowledgeState,
    KnowledgeLifecycleStatus,
    KnowledgeRetrievalQuery,
    match_current_knowledge,
)
from backend.services.ontology.commercial_state import GoalSemanticComparisonStatus, GoalSemanticSignature
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from tests.unit.ontology.test_knowledge_qualification import candidate


def _artifact():
    result = qualify_pattern_knowledge(candidate(latest=datetime(2026, 2, 1, tzinfo=UTC)))
    assert result.qualified_knowledge is not None
    return result.qualified_knowledge


def _state(artifact, status=KnowledgeLifecycleStatus.ACTIVE):
    ids = (artifact.knowledge_id,) if status == KnowledgeLifecycleStatus.ACTIVE else ()
    return CurrentKnowledgeState(
        proposition_key=artifact.proposition.proposition_key,
        lifecycle_status=status,
        evaluation_frontier=artifact.qualified_through_evaluated_at,
        authoritative_qualification_ids=(artifact.qualification_id,),
        authoritative_knowledge_ids=ids,
        historical_qualification_count=1,
        lifecycle_projection_id=f"projection:{status.value}",
    )


def _query(artifact, **updates):
    values = {
        "subject_semantic_signatures": artifact.proposition.subject_semantic_signatures,
        "goal_semantic_signature": GoalSemanticSignature(objective_key=artifact.proposition.objective_key),
    }
    values.update(updates)
    return KnowledgeRetrievalQuery(**values)


def test_query_rejects_unbounded_subjects_and_goal() -> None:
    with pytest.raises(ValidationError, match="subject semantic"):
        KnowledgeRetrievalQuery(
            subject_semantic_signatures=(), goal_semantic_signature=GoalSemanticSignature(objective_key="goal")
        )
    with pytest.raises(ValidationError, match="objective key or KPI"):
        KnowledgeRetrievalQuery(
            subject_semantic_signatures=(BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),),
            goal_semantic_signature=GoalSemanticSignature(),
        )


def test_active_exact_semantics_match_without_claiming_applicability() -> None:
    artifact = _artifact()
    proposition = artifact.proposition.model_copy(
        update={"scope_conditions": ("enterprise",), "invalidation_conditions": ("market_changed",)}
    )
    artifact = artifact.model_copy(update={"proposition": proposition})
    state = _state(artifact)
    match = match_current_knowledge(query=_query(artifact), current_state=state, artifacts=[artifact])
    assert match is not None
    assert match.goal_comparison.status == GoalSemanticComparisonStatus.EQUIVALENT
    assert match.applicability_determined is False
    assert match.proposition.scope_conditions == ("enterprise",)
    assert match.epistemic_limits == (
        "invalidation_conditions_not_evaluated",
        "scope_conditions_not_evaluated",
    )


@pytest.mark.parametrize(
    "status",
    [
        KnowledgeLifecycleStatus.ABSENT,
        KnowledgeLifecycleStatus.PROVISIONAL,
        KnowledgeLifecycleStatus.CONTESTED,
        KnowledgeLifecycleStatus.INVALIDATED,
    ],
)
def test_non_active_authority_is_never_retrieved(status) -> None:
    artifact = _artifact()
    assert (
        match_current_knowledge(query=_query(artifact), current_state=_state(artifact, status), artifacts=[artifact])
        is None
    )


def test_subject_intervention_relationship_and_goal_are_exact() -> None:
    artifact = _artifact()
    different_subject = BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT)
    assert (
        match_current_knowledge(
            query=_query(artifact, subject_semantic_signatures=(different_subject,)),
            current_state=_state(artifact),
            artifacts=[artifact],
        )
        is None
    )
    assert (
        match_current_knowledge(
            query=_query(artifact, intervention_keys=("different",)),
            current_state=_state(artifact),
            artifacts=[artifact],
        )
        is None
    )
    assert (
        match_current_knowledge(
            query=_query(artifact, goal_semantic_signature=GoalSemanticSignature(objective_key="different")),
            current_state=_state(artifact),
            artifacts=[artifact],
        )
        is None
    )

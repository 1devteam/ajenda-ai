from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from backend.services.knowledge import (
    ContextConditionState,
    KnowledgeDecisionCriterion,
    KnowledgeDecisionOption,
    KnowledgeInfluenceDirection,
    build_knowledge_decision_evidence,
    evaluate_knowledge_decision_support,
    resolve_knowledge_applicability,
)
from backend.services.tools.decision_actions import decision_recommend_next_action
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.unit.knowledge.test_knowledge_applicability import NOW, _assertion, _context, _match


def _resolution(*, scope_state=ContextConditionState.ACTIVE):
    query, match = _match()
    context = _context(
        query,
        _assertion("segment:smb", scope_state, evidence=("world-evidence-a",)),
        _assertion("pricing_model_changed", ContextConditionState.INACTIVE),
    )
    retrieval = match.current_state
    from backend.services.knowledge import KnowledgeRetrievalInspectionTrace, KnowledgeRetrievalResult

    result = KnowledgeRetrievalResult(
        query=query,
        matches=(match,),
        candidate_proposition_count=1,
        active_proposition_count=1,
        semantic_match_count=1,
        retrieval_id="knowledge-retrieval-v1:test",
        inspection_trace=KnowledgeRetrievalInspectionTrace(
            candidate_proposition_keys=(retrieval.proposition_key,),
        ),
    )
    return match, resolve_knowledge_applicability(retrieval=result, context=context)


def _evaluate(*, options=None, criteria=None, scope_state=ContextConditionState.ACTIVE):
    match, resolution = _resolution(scope_state=scope_state)
    return match, evaluate_knowledge_decision_support(
        decision_id="decision-430",
        options=options
        or (
            KnowledgeDecisionOption(
                option_id="aligned",
                label="Aligned",
                intervention_key=match.proposition.intervention_key,
            ),
            KnowledgeDecisionOption(option_id="other", label="Other", intervention_key="sales.send_pricing"),
        ),
        criteria=criteria
        or (
            KnowledgeDecisionCriterion(
                criterion_id="outcome",
                label="Outcome",
                objective_key=match.proposition.objective_key,
            ),
            KnowledgeDecisionCriterion(criterion_id="cost", label="Cost", objective_key="implementation_cost"),
        ),
        applicability=resolution,
        evaluated_at=NOW,
    )


def test_exact_semantics_support_only_the_aligned_option_and_criterion() -> None:
    _, result = _evaluate()
    supported = [item for item in result.influences if item.direction == KnowledgeInfluenceDirection.SUPPORTS]
    assert [(item.option_id, item.criterion_id) for item in supported] == [("aligned", "outcome")]
    other = next(item for item in result.influences if item.option_id == "other")
    assert other.direction == KnowledgeInfluenceDirection.NEUTRAL
    assert result.is_decision is result.is_policy is result.is_execution_instruction is False
    assert result.is_independent_observation is False


def test_missing_option_or_criterion_semantics_remain_unresolved_without_prose_matching() -> None:
    match, _ = _resolution()
    _, result = _evaluate(
        options=(
            KnowledgeDecisionOption(
                option_id="prose-only", label="Call them", description=match.proposition.intervention_key
            ),
        ),
        criteria=(KnowledgeDecisionCriterion(criterion_id="labels-only", label="Conversion"),),
    )
    assert {item.direction for item in result.influences} == {KnowledgeInfluenceDirection.UNRESOLVED}
    assert "option_intervention_semantics_missing" in result.influences[0].reason_codes


@pytest.mark.parametrize(
    "state",
    [ContextConditionState.INACTIVE, ContextConditionState.UNKNOWN],
)
def test_ineligible_applicability_never_becomes_decision_evidence(state) -> None:
    _, result = _evaluate(scope_state=state)
    assert all(item.direction == KnowledgeInfluenceDirection.UNRESOLVED for item in result.influences)
    assert all("excluded_from_decision_evidence" in item.reason_codes for item in result.influences)


def test_reordering_is_deterministic_and_preserves_derived_provenance() -> None:
    match, first = _evaluate()
    _, reordered = _evaluate(
        options=tuple(
            reversed(
                (
                    KnowledgeDecisionOption(
                        option_id="aligned", label="Aligned", intervention_key=match.proposition.intervention_key
                    ),
                    KnowledgeDecisionOption(option_id="other", label="Other", intervention_key="sales.send_pricing"),
                )
            )
        ),
        criteria=tuple(
            reversed(
                (
                    KnowledgeDecisionCriterion(
                        criterion_id="outcome", label="Outcome", objective_key=match.proposition.objective_key
                    ),
                    KnowledgeDecisionCriterion(criterion_id="cost", label="Cost", objective_key="implementation_cost"),
                )
            )
        ),
    )
    assert reordered.support_id == first.support_id
    assert reordered.influences == first.influences
    assert "derived_knowledge_not_independent_observation" in first.epistemic_limits
    assert first.supporting_evidence_ids == ("world-evidence-a",)


def test_future_applicability_is_rejected() -> None:
    match, resolution = _resolution()
    with pytest.raises(ValueError, match="future applicability"):
        evaluate_knowledge_decision_support(
            decision_id="decision-430",
            options=(
                KnowledgeDecisionOption(option_id="a", label="A", intervention_key=match.proposition.intervention_key),
            ),
            criteria=(
                KnowledgeDecisionCriterion(criterion_id="c", label="C", objective_key=match.proposition.objective_key),
            ),
            applicability=resolution,
            evaluated_at=NOW - timedelta(seconds=1),
        )


def test_only_eligible_support_becomes_derived_decision_evidence() -> None:
    _, support = _evaluate()
    supported = next(item for item in support.influences if item.direction == KnowledgeInfluenceDirection.SUPPORTS)
    durable_root = str(uuid4())
    facts = build_knowledge_decision_evidence(
        support=support,
        durable_ancestry_by_influence={supported.influence_id: (durable_root,)},
    )

    assert len(facts) == 1
    fact = facts[0]
    assert fact.evidence_id == supported.influence_id
    assert fact.status.value == "inferred"
    assert fact.confidence == 0.5  # Existing EvidenceFact default; not Knowledge arithmetic.
    assert fact.supports_option_ids == [supported.option_id]
    assert fact.supports_criterion_ids == [supported.criterion_id]
    assert fact.lineage is not None
    assert fact.lineage.origin_type.value == "derived_fact"
    assert fact.lineage.root_evidence_ids == (durable_root,)
    assert {item.evidence_id for item in facts} == {supported.influence_id}


def test_eligible_support_without_durable_ancestry_fails_closed() -> None:
    _, support = _evaluate()
    assert build_knowledge_decision_evidence(support=support, durable_ancestry_by_influence={}) == ()


def test_knowledge_fact_changes_canonical_decision_through_existing_algorithm() -> None:
    match, support = _evaluate()
    supported = next(item for item in support.influences if item.direction == KnowledgeInfluenceDirection.SUPPORTS)
    facts = build_knowledge_decision_evidence(
        support=support,
        durable_ancestry_by_influence={supported.influence_id: (str(uuid4()),)},
    )
    context = ActionRuntimeContext(tenant_id="tenant-a", task_id=uuid4(), worker_id="worker", lease_id="lease")
    base = {
        "goal": "Increase conversion",
        "options": [
            {
                "option_id": "aligned",
                "label": "Discovery",
                "intervention_key": match.proposition.intervention_key,
            },
            {"option_id": "other", "label": "Pricing", "intervention_key": "sales.send_pricing"},
        ],
        "criteria": [{"criterion_id": "outcome", "label": "Outcome", "weight": 1.0}],
        "evidence": [
            {
                "evidence_id": str(uuid4()),
                "claim": "Bounded base evidence for pricing",
                "confidence": 0.2,
                "supports_option_ids": ["other"],
                "supports_criterion_ids": ["outcome"],
            }
        ],
    }
    without = decision_recommend_next_action(
        ToolInvocation(action="decision.recommend_next_action", input=base), context
    )
    with_knowledge = decision_recommend_next_action(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                **base,
                "evidence": [
                    *base["evidence"],
                    *(item.model_dump(mode="json") for item in facts),
                ],
            },
        ),
        context,
    )

    assert without.output["recommendation"] == "other"
    assert with_knowledge.output["recommendation"] == "aligned"
    assert with_knowledge.output["algorithm"]["name"] == "weighted_criterion_evidence_v1"
    assert with_knowledge.output["option_scores"][0]["dimension_scores"][0]["weight"] == 1.0
    assert "knowledge_bonus" not in with_knowledge.output["algorithm"]

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.services.ontology.commercial_state import GoalSemanticSignature, KpiDirection, KpiSemanticSignature
from backend.services.ontology.experience_intelligence import (
    ComparabilityStatus,
    ExperienceEpisodeInput,
    ExperiencePatternCandidate,
    ExperiencePatternSemanticContext,
    GoalSemanticBasis,
    IndependenceStatus,
    InterventionSemanticBasis,
    RecurrenceAssessment,
    RecurrenceStrength,
    evaluate_experience_set,
)
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationStatus,
    qualify_pattern_knowledge,
)
from backend.services.ontology.observation_attribution import ObservationTimeProvenance
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
from tests.unit.ontology.test_experience_intelligence import signal


def context(
    *,
    objective="increase_qualification_score",
    kpis=(),
    intervention="sales.schedule_discovery",
    intervention_bases=(InterventionSemanticBasis.DECISION_OWNER,),
    goal_bases=(GoalSemanticBasis.OWNER_EXPLICIT_OBJECTIVE,),
    scope=("segment:smb",),
):
    return ExperiencePatternSemanticContext(
        subject_semantic_signatures=(BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),),
        intervention_key=intervention,
        intervention_semantic_bases=intervention_bases,
        objective_key=objective,
        common_kpi_semantic_signatures=kpis,
        goal_semantic_bases=goal_bases,
        exact_goal_ids=("goal-A",),
        scope_conditions=scope,
    )


def candidate(
    *,
    strength=RecurrenceStrength.SUPPORTED,
    semantic_context=None,
    independent=3,
    strong_contradictions=0,
    dependent=0,
    limited_contradictions=0,
    scope=("segment:smb",),
    conflicts=(),
    support=("ep-1", "ep-2", "ep-3"),
    latest=None,
):
    semantic_context = context(scope=scope) if semantic_context is None else semantic_context
    return ExperiencePatternCandidate(
        candidate_id="candidate-stable",
        partition_key="opaque-compatibility-key",
        recommendation_class=semantic_context.intervention_key if semantic_context else "legacy-prose",
        subject_types=tuple(item.object_type.value for item in semantic_context.subject_semantic_signatures)
        if semantic_context
        else ("opportunity",),
        goal_id="opaque-goal-compatibility",
        supporting_episode_ids=support,
        common_scope_conditions=scope,
        conflicting_scope_conditions=conflicts,
        earliest_evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        latest_evaluated_at=latest or datetime(2026, 1, 3, tzinfo=UTC),
        recurrence=RecurrenceAssessment(
            strength=strength,
            comparability=ComparabilityStatus.COMPARABLE,
            independence=IndependenceStatus.PARTIALLY_INDEPENDENT if dependent else IndependenceStatus.INDEPENDENT,
            independent_support_count=independent,
            dependent_support_count=dependent,
            strong_independent_contradiction_count=strong_contradictions,
            limited_contradiction_count=limited_contradictions,
        ),
        semantic_context=semantic_context,
    )


def test_qualified_happy_path_emits_noncausal_nonpersisted_artifact():
    result = qualify_pattern_knowledge(candidate())
    assert result.status == KnowledgeQualificationStatus.QUALIFIED
    assert result.qualified_knowledge is not None
    assert result.qualified_knowledge.is_knowledge is True
    assert result.qualified_knowledge.is_policy is False
    assert result.qualified_knowledge.is_persisted is False
    assert result.proposition.relationship_type.value == "associated_with_favorable_outcome"


@pytest.mark.parametrize(
    ("semantic_context", "expected"),
    [
        (
            context(
                objective=None,
                kpis=(KpiSemanticSignature(metric="score", direction=KpiDirection.INCREASE),),
                goal_bases=(GoalSemanticBasis.OWNER_KPI_ONLY,),
            ),
            KnowledgeQualificationStatus.PROVISIONAL,
        ),
        (
            context(intervention_bases=(InterventionSemanticBasis.LEGACY_EXPERIENCE_FALLBACK,)),
            KnowledgeQualificationStatus.PROVISIONAL,
        ),
        (
            context(goal_bases=(GoalSemanticBasis.INHERITED_EXPLICIT_OBJECTIVE,)),
            KnowledgeQualificationStatus.PROVISIONAL,
        ),
        (
            context(objective=None, goal_bases=(GoalSemanticBasis.EXACT_GOAL_INSTANCE_FALLBACK,)),
            KnowledgeQualificationStatus.INSUFFICIENT,
        ),
        (context(scope=()), KnowledgeQualificationStatus.PROVISIONAL),
    ],
)
def test_authority_and_scope_caps_fail_closed(semantic_context, expected):
    result = qualify_pattern_knowledge(
        candidate(semantic_context=semantic_context, scope=semantic_context.scope_conditions)
    )
    assert result.status == expected
    assert result.qualified_knowledge is None


def test_missing_context_never_parses_compatibility_strings():
    raw = candidate().model_dump()
    raw["semantic_context"] = None
    raw["goal_id"] = "objective:fake"
    raw["partition_key"] = "kpis:fake"
    result = qualify_pattern_knowledge(ExperiencePatternCandidate.model_validate(raw))
    assert result.status == KnowledgeQualificationStatus.INSUFFICIENT
    assert result.proposition is None


@pytest.mark.parametrize(
    ("strength", "expected"),
    [
        (RecurrenceStrength.EMERGING, KnowledgeQualificationStatus.PROVISIONAL),
        (RecurrenceStrength.WEAK, KnowledgeQualificationStatus.INSUFFICIENT),
        (RecurrenceStrength.CONTESTED, KnowledgeQualificationStatus.CONTESTED),
        (RecurrenceStrength.INVALIDATED, KnowledgeQualificationStatus.INVALIDATED),
    ],
)
def test_recurrence_status_precedence(strength, expected):
    result = qualify_pattern_knowledge(candidate(strength=strength))
    assert result.status == expected
    assert result.qualified_knowledge is None


def test_emerging_recurrence_is_provisional_without_qualification_threshold():
    assert (
        qualify_pattern_knowledge(candidate(strength=RecurrenceStrength.EMERGING, independent=1)).status
        == KnowledgeQualificationStatus.PROVISIONAL
    )


def test_scope_conflict_and_malformed_supported_recurrence_fail_closed():
    assert (
        qualify_pattern_knowledge(candidate(conflicts=("segment:enterprise",))).status
        == KnowledgeQualificationStatus.INSUFFICIENT
    )
    malformed = qualify_pattern_knowledge(candidate(strong_contradictions=1))
    assert malformed.status == KnowledgeQualificationStatus.INSUFFICIENT
    assert "recurrence_contract_inconsistent" in malformed.reason_codes


def test_dependent_support_does_not_erase_three_independent_units_and_counterevidence_is_visible():
    result = qualify_pattern_knowledge(
        candidate(dependent=1, limited_contradictions=1, support=("ep-4", "ep-3", "ep-2", "ep-1"))
    )
    assert result.status == KnowledgeQualificationStatus.QUALIFIED
    assert result.evidence_summary.dependent_support_count == 1
    assert result.evidence_summary.limited_contradiction_count == 1
    assert "limited_counterevidence_present" in result.epistemic_limits


def test_semantic_proposition_identity_is_separate_from_evidence_identity_and_deterministic():
    first = qualify_pattern_knowledge(candidate())
    second = qualify_pattern_knowledge(
        candidate(support=("ep-4", "ep-3", "ep-2", "ep-1"), latest=datetime(2026, 1, 4, tzinfo=UTC))
    )
    reordered = qualify_pattern_knowledge(candidate(support=("ep-3", "ep-1", "ep-2")))
    assert first.proposition.proposition_key == second.proposition.proposition_key
    assert first.qualification_id != second.qualification_id
    assert first.qualification_id == reordered.qualification_id
    other_intervention = context(intervention="sales.send_pricing")
    other_objective = context(objective="increase_reply_rate")
    assert (
        qualify_pattern_knowledge(candidate(semantic_context=other_intervention)).proposition.proposition_key
        != first.proposition.proposition_key
    )
    assert (
        qualify_pattern_knowledge(candidate(semantic_context=other_objective)).proposition.proposition_key
        != first.proposition.proposition_key
    )


def test_real_experience_producer_to_qualified_knowledge_path():
    episodes = []
    for i in (1, 2, 3):
        owner_signal = signal(i).model_copy(
            update={
                "intervention_key": "sales.schedule_discovery",
                "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_qualification_score"),
            }
        )
        episodes.append(
            ExperienceEpisodeInput(
                episode_id=f"ep-{i}",
                signal=owner_signal,
                observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
            )
        )
    produced = evaluate_experience_set(episodes).pattern_candidates[0]
    result = qualify_pattern_knowledge(produced)
    assert produced.semantic_context.objective_key == "increase_qualification_score"
    assert produced.semantic_context.intervention_semantic_bases == (InterventionSemanticBasis.DECISION_OWNER,)
    assert produced.semantic_context.scope_conditions == ("smb",)
    assert result.status == KnowledgeQualificationStatus.QUALIFIED
    assert result.proposition.subject_semantic_signatures[0].object_type == BusinessObjectType.OPPORTUNITY


def test_explicit_action_surface_handoff_returns_evidence():
    registry = get_default_action_registry(rebuild=True)
    runtime = ActionRuntimeContext(tenant_id="tenant", task_id=uuid4(), worker_id="worker", lease_id="lease")
    episodes = []
    for i in (1, 2, 3):
        owner_signal = signal(i).model_copy(
            update={
                "intervention_key": "sales.schedule_discovery",
                "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_qualification_score"),
            }
        )
        episodes.append(
            ExperienceEpisodeInput(
                episode_id=f"ep-{i}",
                signal=owner_signal,
                observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
            )
        )
    recurrence = registry.invoke(
        ToolInvocation(
            action="analysis.assess_experience_recurrence",
            input={"episodes": [episode.model_dump(mode="json") for episode in episodes]},
        ),
        runtime,
    )
    qualification = registry.invoke(
        ToolInvocation(
            action="analysis.qualify_pattern_knowledge",
            input={"candidate": recurrence.output["pattern_candidates"][0]},
        ),
        runtime,
    )
    assert qualification.output["status"] == "qualified"
    assert qualification.side_effect_class == SideEffectClass.NONE
    assert qualification.evidence[0].evidence_type == "action_result_evidence"

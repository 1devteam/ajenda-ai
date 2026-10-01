from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.ontology.commercial_state import (
    GoalSemanticSignature,
    KpiDirection,
    KpiSemanticSignature,
)
from backend.services.ontology.experience_intelligence import ExperienceEpisodeInput, evaluate_experience_set
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationStatus,
    KnowledgeRelationshipType,
    qualify_pattern_knowledge,
)
from backend.services.ontology.observation_attribution import ObservationTimeProvenance
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.unit.ontology.test_experience_intelligence import signal

pytestmark = pytest.mark.integration


def _context(tenant: str, factory) -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=tenant,
        task_id=uuid.uuid4(),
        worker_id="worker",
        lease_id="lease",
        session_factory=factory,
    )


def _qualification(
    *,
    intervention: str,
    indexes: tuple[int, ...],
    effective: bool = True,
    goal_semantics: GoalSemanticSignature | None = None,
):
    episodes = []
    for index in indexes:
        owner_signal = signal(index, scope=("segment=smb",), invalidation=("market_changed",)).model_copy(
            update={
                "intervention_key": intervention,
                "goal_semantic_signature": goal_semantics or GoalSemanticSignature(objective_key="increase_conversion"),
            }
        )
        if not effective:
            from backend.services.ontology.decision_feedback import DecisionEffectivenessStatus

            owner_signal = owner_signal.model_copy(
                update={
                    "effectiveness": owner_signal.effectiveness.model_copy(
                        update={"status": DecisionEffectivenessStatus.INEFFECTIVE}
                    )
                }
            )
        episodes.append(
            ExperienceEpisodeInput(
                episode_id=f"{intervention}-{index}",
                signal=owner_signal,
                observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
            )
        )
    produced = evaluate_experience_set(episodes).pattern_candidates[0]
    return qualify_pattern_knowledge(produced)


def _tenant_counts(factory, tenant: str) -> tuple[int, int]:
    with factory() as session:
        activate_tenant_session(session, tenant)
        return (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant)
            ),
            session.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant)
            ),
        )


def _replace_proposition(qualification, **updates):
    assert qualification.proposition is not None and qualification.qualified_knowledge is not None
    proposition = qualification.proposition.model_copy(update=updates)
    artifact = qualification.qualified_knowledge.model_copy(update={"proposition": proposition})
    return qualification.model_copy(update={"proposition": proposition, "qualified_knowledge": artifact})


def test_real_intelligence_ledger_lifecycle_retrieval_path_is_current_read_only_and_tenant_scoped(
    pg_engine,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other_tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)

    historical = _qualification(intervention="send_followup", indexes=(1, 2, 3))
    invalidated = _qualification(intervention="send_followup", indexes=(10, 11), effective=False)
    current = _qualification(intervention="schedule_demo", indexes=(20, 21, 22))
    subject_superset = _replace_proposition(
        _qualification(intervention="subject_superset", indexes=(24, 25, 26)),
        subject_semantic_signatures=(
            BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT),
            BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),
        ),
    )
    assert historical.proposition is not None and historical.qualified_knowledge is not None
    assert invalidated.proposition is not None
    assert current.proposition is not None and current.qualified_knowledge is not None
    assert historical.proposition.proposition_key == invalidated.proposition.proposition_key

    for qualification in (historical, invalidated, current, subject_superset):
        registry.invoke(
            ToolInvocation(
                action="knowledge.record_qualification",
                input={"result": qualification.model_dump(mode="json")},
            ),
            _context(tenant, factory),
        )

    before = _tenant_counts(factory, tenant)
    query = {
        "subject_semantic_signatures": [
            BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")
        ],
        "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_conversion").model_dump(mode="json"),
    }
    result = registry.invoke(
        ToolInvocation(action="knowledge.retrieve_current", input={"query": query}),
        _context(tenant, factory),
    )

    assert result.output["semantic_match_count"] == 1
    assert result.output["candidate_proposition_count"] == 3
    assert set(result.output["inspection_trace"]["candidate_proposition_keys"]) == {
        historical.proposition.proposition_key,
        current.proposition.proposition_key,
        subject_superset.proposition.proposition_key,
    }
    match = result.output["matches"][0]
    assert match["proposition"]["proposition_key"] == current.proposition.proposition_key
    assert match["current_state"]["lifecycle_status"] == "active"
    assert match["authoritative_artifacts"] == [current.qualified_knowledge.model_dump(mode="json")]
    assert historical.qualified_knowledge.knowledge_id not in {
        item["knowledge_id"] for item in match["authoritative_artifacts"]
    }
    assert match["applicability_determined"] is False
    assert match["proposition"]["scope_conditions"] == ["segment=smb"]
    assert match["proposition"]["invalidation_conditions"] == ["market_changed"]
    assert match["proposition"]["relationship_type"] == "associated_with_favorable_outcome"
    assert "relevance_score" not in match
    assert result.output["is_decision_support"] is False
    assert _tenant_counts(factory, tenant) == before == (4, 3)

    repeated = registry.invoke(
        ToolInvocation(action="knowledge.retrieve_current", input={"query": query}),
        _context(tenant, factory),
    )
    assert repeated.output == result.output
    assert len(repeated.evidence) == len(result.evidence) == 1
    assert repeated.evidence[0].structured_payload == result.evidence[0].structured_payload
    assert repeated.evidence[0].summary == result.evidence[0].summary
    assert repeated.evidence[0].task_id != result.evidence[0].task_id

    hidden = registry.invoke(
        ToolInvocation(action="knowledge.retrieve_current", input={"query": query}),
        _context(other_tenant, factory),
    )
    assert hidden.output["matches"] == []
    assert hidden.output["candidate_proposition_count"] == 0


def test_real_jsonb_goal_discovery_and_owner_produced_kpi_only_boundary(pg_engine) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
    kpi = KpiSemanticSignature(metric="reply_rate", direction=KpiDirection.INCREASE)
    unrelated_kpi = KpiSemanticSignature(metric="cost", direction=KpiDirection.DECREASE)

    exact = _replace_proposition(
        _qualification(intervention="exact_objective", indexes=(30, 31, 32)),
        objective_key="increase_conversion",
        kpi_semantic_signatures=(unrelated_kpi,),
    )
    partial = _qualification(
        intervention="partial_kpi",
        indexes=(40, 41, 42),
        goal_semantics=GoalSemanticSignature(kpis=(kpi,)),
    )
    overselected = _replace_proposition(
        _qualification(intervention="conflicting_objective", indexes=(50, 51, 52)),
        objective_key="decrease_cost",
        kpi_semantic_signatures=(kpi,),
    )
    unrelated = _replace_proposition(
        _qualification(intervention="unrelated", indexes=(60, 61, 62)),
        subject_semantic_signatures=(BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT),),
        objective_key="unrelated",
        kpi_semantic_signatures=(unrelated_kpi,),
    )
    assert partial.status == KnowledgeQualificationStatus.INSUFFICIENT
    assert partial.proposition is not None
    assert partial.proposition.objective_key is None
    assert partial.proposition.kpi_semantic_signatures == (kpi,)
    assert partial.qualified_knowledge is None

    for qualification in (exact, partial, overselected, unrelated):
        registry.invoke(
            ToolInvocation(
                action="knowledge.record_qualification",
                input={"result": qualification.model_dump(mode="json")},
            ),
            _context(tenant, factory),
        )
    assert _tenant_counts(factory, tenant) == (4, 3)

    goal = GoalSemanticSignature(objective_key="increase_conversion", kpis=(kpi,))
    subjects = (BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),)
    with factory() as session:
        activate_tenant_session(session, tenant)
        candidates = KnowledgeRepository(session).list_candidate_proposition_keys_for_retrieval(
            tenant_id=tenant,
            subject_semantic_signatures=subjects,
            goal_semantic_signature=goal,
            intervention_keys=(),
            relationship_types=(KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,),
        )
    assert candidates == sorted(
        [
            exact.proposition.proposition_key,
            overselected.proposition.proposition_key,
        ]
    )

    result = registry.invoke(
        ToolInvocation(
            action="knowledge.retrieve_current",
            input={
                "query": {
                    "subject_semantic_signatures": [item.model_dump(mode="json") for item in subjects],
                    "goal_semantic_signature": goal.model_dump(mode="json"),
                }
            },
        ),
        _context(tenant, factory),
    )
    matched = {item["proposition"]["proposition_key"]: item for item in result.output["matches"]}
    assert set(matched) == {exact.proposition.proposition_key}
    assert partial.proposition.proposition_key not in candidates
    assert partial.proposition.proposition_key not in matched
    assert result.output["inspection_trace"]["candidate_proposition_keys"] == candidates
    assert result.output["semantic_match_count"] == 1
    assert set(result.evidence[0].structured_payload["inspected_candidate_proposition_keys"]) == set(candidates)

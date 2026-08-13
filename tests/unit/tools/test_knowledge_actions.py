from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.services.knowledge import (
    ContextConditionAssertion,
    ContextConditionState,
    CurrentKnowledgeState,
    KnowledgeApplicabilityContext,
    KnowledgeLedgerWriteResult,
    KnowledgeLedgerWriteStatus,
    KnowledgeLifecycleStatus,
    KnowledgeRetrievalInspectionTrace,
    KnowledgeRetrievalQuery,
    KnowledgeRetrievalResult,
)
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.knowledge_actions import _normalize_decision_evidence_ids
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
from tests.unit.knowledge.test_knowledge_decision_support import NOW, _resolution
from tests.unit.ontology.test_knowledge_qualification import candidate


def _context(*, session_factory=None) -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-A",
        task_id=uuid4(),
        worker_id="worker",
        lease_id="lease",
        session_factory=session_factory,
    )


def test_knowledge_action_is_registered_as_governed_internal_write() -> None:
    definition = get_default_action_registry(rebuild=True).get("knowledge.record_qualification")
    assert definition.provider == "ajenda_knowledge"
    assert definition.side_effect_class == SideEffectClass.INTERNAL_WRITE


def test_knowledge_synthetic_ids_are_normalized_in_every_decision_evidence_field() -> None:
    root_a, root_b = str(uuid4()), str(uuid4())
    synthetic = "knowledge-influence-v1:synthetic"
    output, applied = _normalize_decision_evidence_ids(
        {
            "supporting_evidence_ids": ["ordinary", synthetic],
            "option_scores": [
                {
                    "option_id": "a",
                    "supporting_evidence_ids": [synthetic],
                    "dimension_scores": [{"criterion_id": "c", "evidence_ids": [synthetic]}],
                }
            ],
        },
        ancestry_by_derived_id={synthetic: (root_a, root_b)},
    )

    assert output["supporting_evidence_ids"] == ["ordinary", root_a, root_b]
    score = output["option_scores"][0]
    assert score["supporting_evidence_ids"] == [root_a, root_b]
    assert score["dimension_scores"][0]["evidence_ids"] == [root_a, root_b]
    assert score["knowledge_influence_ids"] == [synthetic]
    assert applied == (synthetic,)


def test_knowledge_action_injects_fact_into_canonical_decision_and_preserves_base_evidence(
    monkeypatch,
) -> None:
    match, resolution = _resolution()
    durable_root = str(uuid4())
    retrieval = resolution.retrieval
    monkeypatch.setattr(
        "backend.services.tools.knowledge_actions.retrieve_current_knowledge",
        Mock(return_value=retrieval),
    )
    monkeypatch.setattr(
        "backend.services.tools.knowledge_actions._durable_knowledge_ancestry",
        lambda _session, **kwargs: {
            influence.influence_id: (durable_root,)
            for influence in kwargs["support"].influences
            if influence.direction.value == "supports"
        },
    )
    options = [
        {
            "option_id": "aligned",
            "label": "Discovery",
            "intervention_key": match.proposition.intervention_key,
        },
        {"option_id": "other", "label": "Pricing", "intervention_key": "sales.send_pricing"},
    ]
    base_id = str(uuid4())
    decision = {
        "goal": "Increase conversion",
        "options": options,
        "criteria": [{"criterion_id": "outcome", "label": "Outcome", "weight": 1.0}],
        "evidence": [
            {
                "evidence_id": base_id,
                "claim": "Pricing has bounded base support",
                "confidence": 0.2,
                "supports_option_ids": ["other"],
                "supports_criterion_ids": ["outcome"],
            }
        ],
    }
    context = _context(session_factory=Mock(return_value=Mock()))
    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="knowledge.inform_decision",
            input={
                "decision_id": "decision-430",
                "decision": decision,
                "options": options,
                "criteria": [
                    {
                        "criterion_id": "outcome",
                        "label": "Outcome",
                        "weight": 1.0,
                        "objective_key": match.proposition.objective_key,
                    }
                ],
                "query": retrieval.query.model_dump(mode="json"),
                "applicability_context": resolution.evaluations
                and {
                    "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                    "subject_semantic_signatures": retrieval.query.subject_semantic_signatures,
                    "goal_semantic_signature": retrieval.query.goal_semantic_signature,
                    "condition_assertions": [
                        {
                            "condition_key": "segment:smb",
                            "state": "active",
                            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                            "evidence_ids": [durable_root],
                            "observed_at": NOW,
                            "verification_basis": "independently_verified",
                        },
                        {
                            "condition_key": "pricing_model_changed",
                            "state": "inactive",
                            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                            "observed_at": NOW,
                            "verification_basis": "independently_verified",
                        },
                    ],
                    "evaluated_at": NOW,
                },
            },
        ),
        context,
    )

    decision_result = result.output["decision_result"]
    assert decision_result["recommendation"] == "aligned"
    assert decision_result["algorithm"]["name"] == "weighted_criterion_evidence_v1"
    assert decision_result["knowledge_decision_support"]["applied_influence_ids"]
    assert all(
        not identity.startswith("knowledge-influence-v1:")
        for score in decision_result["option_scores"]
        for identity in score["supporting_evidence_ids"]
    )
    assert any(fact["evidence_id"] == base_id for fact in result.output["decision_input"]["evidence"])
    assert result.output["decision_input"]["criteria"][0]["weight"] == decision["criteria"][0]["weight"]
    assert result.evidence[0].lineage is not None
    assert result.evidence[0].lineage.origin_type.value == "derived_fact"
    assert result.evidence[0].lineage.root_evidence_ids == (durable_root,)
    assert result.evidence[0].provenance["is_independent_observation"] is False


def test_consolidation_action_is_registered_as_governed_internal_write() -> None:
    definition = get_default_action_registry(rebuild=True).get("knowledge.consolidate_learning_history")
    assert definition.provider == "ajenda_knowledge"
    assert definition.side_effect_class == SideEffectClass.INTERNAL_WRITE


def test_knowledge_lifecycle_action_is_registered_as_internal_read() -> None:
    definition = get_default_action_registry(rebuild=True).get("knowledge.resolve_current_state")
    assert definition.provider == "ajenda_knowledge"
    assert definition.side_effect_class == SideEffectClass.INTERNAL_READ


def test_knowledge_retrieval_action_is_read_only_and_uses_context_tenant(monkeypatch) -> None:
    query = KnowledgeRetrievalQuery(
        subject_semantic_signatures=(BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),),
        goal_semantic_signature=GoalSemanticSignature(objective_key="increase_conversion"),
    )
    retrieval = KnowledgeRetrievalResult(
        query=query,
        matches=(),
        candidate_proposition_count=0,
        active_proposition_count=0,
        semantic_match_count=0,
        retrieval_id="knowledge-retrieval-v1:test",
        inspection_trace=KnowledgeRetrievalInspectionTrace(
            candidate_proposition_keys=("candidate-rejected", "candidate-match"),
            lifecycle_projection_ids=("projection-rejected", "projection-match"),
            authoritative_qualification_ids=("qualification-rejected", "qualification-match"),
            artifact_knowledge_ids_loaded=("artifact-rejected", "artifact-match"),
        ),
        reason_codes=("no_current_semantic_knowledge_match",),
    )
    service = Mock(return_value=retrieval)
    monkeypatch.setattr("backend.services.tools.knowledge_actions.retrieve_current_knowledge", service)
    session = Mock()
    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(action="knowledge.retrieve_current", input={"query": query.model_dump(mode="json")}),
        _context(session_factory=Mock(return_value=session)),
    )
    service.assert_called_once_with(session, tenant_id="tenant-A", query=query)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
    assert result.side_effect_class == SideEffectClass.INTERNAL_READ
    assert result.evidence[0].structured_payload["retrieval_id"] == retrieval.retrieval_id
    assert result.records_inspected == [
        "knowledge_proposition:candidate-match",
        "knowledge_proposition:candidate-rejected",
        "knowledge_qualification:qualification-match",
        "knowledge_qualification:qualification-rejected",
        "knowledge_artifact:artifact-match",
        "knowledge_artifact:artifact-rejected",
    ]
    assert result.evidence[0].structured_payload["inspected_lifecycle_projection_ids"] == [
        "projection-match",
        "projection-rejected",
    ]


def test_knowledge_applicability_runs_canonical_retrieval_as_tenant_read(monkeypatch) -> None:
    from datetime import UTC, datetime

    query = KnowledgeRetrievalQuery(
        subject_semantic_signatures=(BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),),
        goal_semantic_signature=GoalSemanticSignature(objective_key="increase_conversion"),
    )
    retrieval = KnowledgeRetrievalResult(
        query=query,
        matches=(),
        candidate_proposition_count=0,
        active_proposition_count=0,
        semantic_match_count=0,
        retrieval_id="knowledge-retrieval-v1:none",
        inspection_trace=KnowledgeRetrievalInspectionTrace(candidate_proposition_keys=("candidate",)),
        reason_codes=("no_current_semantic_knowledge_match",),
    )
    context = KnowledgeApplicabilityContext(
        subject_refs=(BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-123"),),
        subject_semantic_signatures=query.subject_semantic_signatures,
        goal_semantic_signature=query.goal_semantic_signature,
        condition_assertions=(
            ContextConditionAssertion(
                condition_key="segment:smb",
                state=ContextConditionState.ACTIVE,
                evidence_ids=("ev-context",),
                observed_at=datetime(2026, 8, 13, tzinfo=UTC),
                verification_basis=ObservationVerificationBasis.SOURCE_SUPPLIED_UNDER_CONTRACT,
            ),
        ),
        evaluated_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    service = Mock(return_value=retrieval)
    monkeypatch.setattr("backend.services.tools.knowledge_actions.retrieve_current_knowledge", service)
    session = Mock()
    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="knowledge.evaluate_applicability",
            input={"query": query.model_dump(mode="json"), "context": context.model_dump(mode="json")},
        ),
        _context(session_factory=Mock(return_value=session)),
    )
    service.assert_called_once_with(session, tenant_id="tenant-A", query=query)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
    assert result.side_effect_class == SideEffectClass.INTERNAL_READ
    assert result.output["evaluations"] == []
    assert result.records_changed == []
    assert result.records_inspected == ["knowledge_proposition:candidate"]
    assert result.evidence[0].evidence_source == "knowledge_applicability"
    assert result.evidence[0].provenance["referenced_evidence_not_inspected"] == []


def test_knowledge_lifecycle_action_uses_context_tenant_and_emits_evidence(monkeypatch) -> None:
    session = Mock()
    state = CurrentKnowledgeState(
        proposition_key="proposition-A",
        lifecycle_status=KnowledgeLifecycleStatus.ABSENT,
        evaluation_frontier=None,
        authoritative_qualification_ids=(),
        authoritative_knowledge_ids=(),
        historical_qualification_count=0,
        reason_codes=("no_qualification_history",),
        lifecycle_projection_id="knowledge-lifecycle-v1:test",
    )
    resolver = Mock(return_value=state)
    monkeypatch.setattr("backend.services.tools.knowledge_actions.resolve_current_knowledge_state", resolver)

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(action="knowledge.resolve_current_state", input={"proposition_key": "proposition-A"}),
        _context(session_factory=Mock(return_value=session)),
    )

    resolver.assert_called_once_with(session, tenant_id="tenant-A", proposition_key="proposition-A")
    session.commit.assert_not_called()
    session.close.assert_called_once_with()
    assert result.output["lifecycle_status"] == "absent"
    assert result.evidence[0].structured_payload["algorithm"] == "knowledge_lifecycle_resolution_v1"
    assert result.side_effect_class == SideEffectClass.INTERNAL_READ


def test_knowledge_lifecycle_action_fails_closed_without_primary_session_factory() -> None:
    invocation = ToolInvocation(action="knowledge.resolve_current_state", input={"proposition_key": "proposition-A"})
    with pytest.raises(RuntimeError, match="primary session factory"):
        get_default_action_registry(rebuild=True).invoke(invocation, _context())


def test_knowledge_action_fails_closed_without_primary_session_factory() -> None:
    result = qualify_pattern_knowledge(candidate())
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    with pytest.raises(RuntimeError, match="primary session factory"):
        get_default_action_registry(rebuild=True).invoke(invocation, _context())


def test_propositionless_result_is_reported_ineligible_without_session() -> None:
    result = qualify_pattern_knowledge(candidate().model_copy(update={"semantic_context": None}))
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    action_result = get_default_action_registry(rebuild=True).invoke(invocation, _context())

    assert action_result.output["status"] == "not_ledger_eligible"
    assert action_result.output["persistence_committed"] is False
    assert action_result.records_changed == []
    assert action_result.evidence[0].evidence_type == "action_result_evidence"


def test_successful_action_commit_is_the_only_source_of_committed_truth(monkeypatch) -> None:
    result = qualify_pattern_knowledge(candidate())
    session = Mock()
    staged = KnowledgeLedgerWriteResult(
        status=KnowledgeLedgerWriteStatus.RECORDED,
        qualification_id=result.qualification_id,
        proposition_key=result.proposition.proposition_key,
        qualification_record_id=uuid4(),
        knowledge_id=result.qualified_knowledge.knowledge_id,
        artifact_record_id=uuid4(),
        qualification_created=True,
        artifact_created=True,
        persistence_committed=False,
    )
    monkeypatch.setattr(
        "backend.services.tools.knowledge_actions.record_knowledge_qualification", Mock(return_value=staged)
    )
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    action_result = get_default_action_registry(rebuild=True).invoke(
        invocation, _context(session_factory=Mock(return_value=session))
    )

    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
    assert action_result.output["persistence_committed"] is True
    assert action_result.evidence[0].structured_payload["persistence_committed"] is True


def test_commit_failure_rolls_back_and_returns_no_success(monkeypatch) -> None:
    result = qualify_pattern_knowledge(candidate())
    session = Mock()
    session.commit.side_effect = RuntimeError("commit failed")
    staged = KnowledgeLedgerWriteResult(
        status=KnowledgeLedgerWriteStatus.RECORDED,
        qualification_id=result.qualification_id,
        proposition_key=result.proposition.proposition_key,
        qualification_record_id=uuid4(),
        knowledge_id=result.qualified_knowledge.knowledge_id,
        artifact_record_id=uuid4(),
        qualification_created=True,
        artifact_created=True,
        persistence_committed=False,
    )
    monkeypatch.setattr(
        "backend.services.tools.knowledge_actions.record_knowledge_qualification", Mock(return_value=staged)
    )
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        get_default_action_registry(rebuild=True).invoke(
            invocation, _context(session_factory=Mock(return_value=session))
        )

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()

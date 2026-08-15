from datetime import UTC, datetime
from types import SimpleNamespace
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
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.knowledge_actions import _validate_applicability_evidence
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
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


@pytest.mark.parametrize("lineage_kind", ["missing", "derived", "wrong_identity"])
def test_applicability_evidence_requires_explicit_matching_source_observation_lineage(lineage_kind: str) -> None:
    evidence_id = uuid4()
    mission_id = uuid4()
    provenance = {}
    if lineage_kind != "missing":
        provenance["evidence_lineage"] = EvidenceLineage(
            artifact_evidence_id=str(uuid4()) if lineage_kind == "wrong_identity" else str(evidence_id),
            origin_type=(
                EvidenceOriginType.DERIVED_FACT if lineage_kind == "derived" else EvidenceOriginType.SOURCE_OBSERVATION
            ),
            root_evidence_ids=(str(uuid4()),) if lineage_kind == "derived" else (),
            resolution=(
                EvidenceLineageResolution.KNOWN if lineage_kind == "derived" else EvidenceLineageResolution.UNKNOWN
            ),
        ).model_dump(mode="json")
    record = SimpleNamespace(
        id=evidence_id,
        mission_id=mission_id,
        structured_payload={"observed_at": datetime(2026, 8, 13, tzinfo=UTC).isoformat()},
        provenance_metadata=provenance,
    )
    repository = Mock()
    repository.get_for_tenant.return_value = record

    with pytest.raises(ValueError, match=r"lineage|derived evidence"):
        _validate_applicability_evidence(
            repository=repository,
            tenant_id="tenant-A",
            mission_id=mission_id,
            evaluated_at=datetime(2026, 8, 13, tzinfo=UTC),
            evidence_ids={str(evidence_id)},
        )


def test_applicability_evidence_accepts_matching_source_observation_lineage() -> None:
    evidence_id = uuid4()
    mission_id = uuid4()
    record = SimpleNamespace(
        id=evidence_id,
        mission_id=mission_id,
        structured_payload={"observed_at": datetime(2026, 8, 13, tzinfo=UTC).isoformat()},
        provenance_metadata={
            "evidence_lineage": EvidenceLineage(
                artifact_evidence_id=str(evidence_id),
                origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                resolution=EvidenceLineageResolution.UNKNOWN,
            ).model_dump(mode="json")
        },
    )
    repository = Mock()
    repository.get_for_tenant.return_value = record

    _validate_applicability_evidence(
        repository=repository,
        tenant_id="tenant-A",
        mission_id=mission_id,
        evaluated_at=datetime(2026, 8, 13, tzinfo=UTC),
        evidence_ids={str(evidence_id)},
    )

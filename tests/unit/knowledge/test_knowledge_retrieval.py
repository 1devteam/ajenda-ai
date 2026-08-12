from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.services.knowledge import (
    CurrentKnowledgeState,
    KnowledgeLedgerIntegrityError,
    KnowledgeLifecycleStatus,
    KnowledgeRetrievalQuery,
    match_current_knowledge,
    retrieve_current_knowledge,
)
from backend.services.knowledge.knowledge_retrieval import _retrieval_id, _validate_artifact_record
from backend.services.ontology.commercial_state import (
    GoalSemanticComparisonStatus,
    GoalSemanticSignature,
    KpiDirection,
    KpiSemanticSignature,
)
from backend.services.ontology.knowledge_qualification import KnowledgeRelationshipType, qualify_pattern_knowledge
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


def test_query_canonicalizes_all_semantic_sets_before_use() -> None:
    account = BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT)
    opportunity = BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY)
    conversion = KpiSemanticSignature(metric="conversion_rate", direction=KpiDirection.INCREASE)
    reply = KpiSemanticSignature(metric="reply_rate", direction=KpiDirection.INCREASE)
    canonical = KnowledgeRetrievalQuery(
        subject_semantic_signatures=(account, opportunity),
        goal_semantic_signature=GoalSemanticSignature(objective_key="goal", kpis=(conversion, reply)),
        intervention_keys=("SEND_FOLLOWUP", "send_followup"),
        relationship_types=(KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,),
    )
    reordered_duplicates = KnowledgeRetrievalQuery(
        subject_semantic_signatures=(opportunity, account, opportunity),
        goal_semantic_signature=GoalSemanticSignature(objective_key="goal", kpis=(reply, conversion, reply)),
        intervention_keys=("send_followup", "SEND_FOLLOWUP", "send_followup"),
        relationship_types=(
            KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,
            KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,
        ),
    )
    assert reordered_duplicates == canonical
    assert reordered_duplicates.subject_semantic_signatures == (account, opportunity)
    assert reordered_duplicates.goal_semantic_signature.kpis == (conversion, reply)
    assert reordered_duplicates.intervention_keys == ("SEND_FOLLOWUP", "send_followup")
    assert _retrieval_id(canonical, ()) == _retrieval_id(reordered_duplicates, ())


def test_goal_semantic_regressions_preserve_owner_comparison() -> None:
    artifact = _artifact()
    kpi = KpiSemanticSignature(metric="reply_rate", direction=KpiDirection.INCREASE)
    proposition = artifact.proposition.model_copy(update={"objective_key": None, "kpi_semantic_signatures": (kpi,)})
    partial_artifact = artifact.model_copy(update={"proposition": proposition})
    partial_state = _state(partial_artifact)

    objective_and_kpi = KnowledgeRetrievalQuery(
        subject_semantic_signatures=proposition.subject_semantic_signatures,
        goal_semantic_signature=GoalSemanticSignature(objective_key="increase_conversion", kpis=(kpi,)),
    )
    partial = match_current_knowledge(
        query=objective_and_kpi, current_state=partial_state, artifacts=[partial_artifact]
    )
    assert partial is not None
    assert partial.goal_comparison.status == GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT

    kpi_only = objective_and_kpi.model_copy(update={"goal_semantic_signature": GoalSemanticSignature(kpis=(kpi,))})
    assert (
        match_current_knowledge(query=kpi_only, current_state=partial_state, artifacts=[partial_artifact]) is not None
    )

    conflicting = artifact.proposition.model_copy(
        update={"objective_key": "decrease_cost", "kpi_semantic_signatures": (kpi,)}
    )
    conflicting_artifact = artifact.model_copy(update={"proposition": conflicting})
    assert (
        match_current_knowledge(
            query=objective_and_kpi,
            current_state=_state(conflicting_artifact),
            artifacts=[conflicting_artifact],
        )
        is None
    )

    different_kpi = KpiSemanticSignature(metric="conversion_rate", direction=KpiDirection.INCREASE)
    assert (
        match_current_knowledge(
            query=KnowledgeRetrievalQuery(
                subject_semantic_signatures=proposition.subject_semantic_signatures,
                goal_semantic_signature=GoalSemanticSignature(kpis=(different_kpi,)),
            ),
            current_state=partial_state,
            artifacts=[partial_artifact],
        )
        is None
    )


def test_authoritative_artifact_set_integrity_fails_closed() -> None:
    artifact = _artifact()
    state = _state(artifact)
    with pytest.raises(KnowledgeLedgerIntegrityError, match="lifecycle authority"):
        match_current_knowledge(query=_query(artifact), current_state=state, artifacts=[])
    duplicate_state = state.model_copy(
        update={"authoritative_knowledge_ids": (artifact.knowledge_id, artifact.knowledge_id)}
    )
    with pytest.raises(KnowledgeLedgerIntegrityError, match="lifecycle authority"):
        match_current_knowledge(query=_query(artifact), current_state=duplicate_state, artifacts=[artifact, artifact])
    different = artifact.model_copy(
        update={
            "knowledge_id": "knowledge:different",
            "proposition": artifact.proposition.model_copy(update={"intervention_key": "different"}),
        }
    )
    multi_state = state.model_copy(
        update={"authoritative_knowledge_ids": (artifact.knowledge_id, different.knowledge_id)}
    )
    with pytest.raises(KnowledgeLedgerIntegrityError, match="disagree on proposition"):
        match_current_knowledge(query=_query(artifact), current_state=multi_state, artifacts=[artifact, different])


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("knowledge_id", "bad-knowledge"),
        ("proposition_key", "bad-proposition"),
        ("qualification_id", "bad-qualification"),
        ("source_candidate_id", "bad-source"),
        ("algorithm", "bad-algorithm"),
        ("proposition_payload", {"bad": "payload"}),
    ],
)
def test_artifact_record_column_disagreement_fails_closed(field, bad_value) -> None:
    artifact = _artifact()
    values = {
        "artifact_payload": artifact.model_dump(mode="json"),
        "knowledge_id": artifact.knowledge_id,
        "proposition_key": artifact.proposition.proposition_key,
        "qualification_id": artifact.qualification_id,
        "source_candidate_id": artifact.source_candidate_id,
        "algorithm": artifact.algorithm,
        "proposition_payload": artifact.proposition.model_dump(mode="json"),
    }
    values[field] = bad_value
    with pytest.raises(KnowledgeLedgerIntegrityError, match="columns disagree"):
        _validate_artifact_record(SimpleNamespace(**values))


def test_retrieval_trace_includes_non_active_and_semantically_rejected_candidates(monkeypatch) -> None:
    matched = _artifact()
    rejected = matched.model_copy(
        update={
            "knowledge_id": "knowledge:rejected",
            "qualification_id": "qualification:rejected",
            "proposition": matched.proposition.model_copy(
                update={
                    "proposition_key": "proposition:rejected",
                    "subject_semantic_signatures": (
                        BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT),
                        *matched.proposition.subject_semantic_signatures,
                    ),
                }
            ),
        }
    )
    matched = matched.model_copy(
        update={"proposition": matched.proposition.model_copy(update={"proposition_key": "proposition:matched"})}
    )
    states = {
        "proposition:non-active": CurrentKnowledgeState(
            proposition_key="proposition:non-active",
            lifecycle_status=KnowledgeLifecycleStatus.INVALIDATED,
            evaluation_frontier=None,
            authoritative_qualification_ids=("qualification:invalidated",),
            authoritative_knowledge_ids=(),
            historical_qualification_count=2,
            lifecycle_projection_id="projection:invalidated",
        ),
        "proposition:rejected": _state(rejected).model_copy(update={"lifecycle_projection_id": "projection:rejected"}),
        "proposition:matched": _state(matched).model_copy(update={"lifecycle_projection_id": "projection:matched"}),
    }

    def record(artifact):
        return SimpleNamespace(
            artifact_payload=artifact.model_dump(mode="json"),
            knowledge_id=artifact.knowledge_id,
            proposition_key=artifact.proposition.proposition_key,
            qualification_id=artifact.qualification_id,
            source_candidate_id=artifact.source_candidate_id,
            algorithm=artifact.algorithm,
            proposition_payload=artifact.proposition.model_dump(mode="json"),
        )

    class RepositoryStub:
        def __init__(self, session) -> None:
            assert session is caller_session

        def list_candidate_proposition_keys_for_retrieval(self, **kwargs):
            return ["proposition:rejected", "proposition:non-active", "proposition:matched"]

        def list_artifacts_for_knowledge_ids(self, *, knowledge_ids, **kwargs):
            by_id = {matched.knowledge_id: matched, rejected.knowledge_id: rejected}
            return [record(by_id[item]) for item in reversed(knowledge_ids)]

    caller_session = object()
    monkeypatch.setattr("backend.services.knowledge.knowledge_retrieval.KnowledgeRepository", RepositoryStub)
    monkeypatch.setattr(
        "backend.services.knowledge.knowledge_retrieval.resolve_current_knowledge_state",
        lambda session, *, tenant_id, proposition_key: states[proposition_key],
    )
    result = retrieve_current_knowledge(caller_session, tenant_id="tenant-A", query=_query(matched))
    assert result.semantic_match_count == 1
    assert result.inspection_trace.candidate_proposition_keys == (
        "proposition:matched",
        "proposition:non-active",
        "proposition:rejected",
    )
    assert result.inspection_trace.lifecycle_projection_ids == (
        "projection:invalidated",
        "projection:matched",
        "projection:rejected",
    )
    assert result.inspection_trace.authoritative_qualification_ids == tuple(
        sorted(("qualification:invalidated", "qualification:rejected", matched.qualification_id))
    )
    assert result.inspection_trace.artifact_knowledge_ids_loaded == tuple(
        sorted(("knowledge:rejected", matched.knowledge_id))
    )

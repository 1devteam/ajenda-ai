from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.services.knowledge.knowledge_ledger import KnowledgeLedgerIntegrityError
from backend.services.knowledge.knowledge_lifecycle import (
    KnowledgeLifecycleHistoryItem,
    KnowledgeLifecycleStatus,
    resolve_current_knowledge_state,
    resolve_knowledge_lifecycle,
)
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationStatus,
    qualify_pattern_knowledge,
)
from tests.unit.ontology.test_knowledge_qualification import candidate

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 2, 1, tzinfo=UTC)
T3 = datetime(2026, 3, 1, tzinfo=UTC)


def _result(status: KnowledgeQualificationStatus, when: datetime | None, suffix: str = ""):
    base = qualify_pattern_knowledge(candidate(latest=when))
    if when is None:
        base = base.model_copy(
            update={"evidence_summary": base.evidence_summary.model_copy(update={"latest_evaluated_at": None})}
        )
    qualification_id = f"{base.qualification_id}{suffix}"
    artifact = base.qualified_knowledge
    if status == KnowledgeQualificationStatus.QUALIFIED:
        artifact = artifact.model_copy(
            update={
                "qualification_id": qualification_id,
                "knowledge_id": f"{artifact.knowledge_id}{suffix}",
                "qualified_through_evaluated_at": when,
            }
        )
    else:
        artifact = None
    return base.model_copy(
        update={"qualification_id": qualification_id, "status": status, "qualified_knowledge": artifact}
    )


def _item(status: KnowledgeQualificationStatus, when: datetime | None, suffix: str = ""):
    result = _result(status, when, suffix)
    return KnowledgeLifecycleHistoryItem(
        qualification_record_id=uuid.uuid4(),
        qualification=result,
        evaluation_watermark=when,
        knowledge_record_id=uuid.uuid4() if result.qualified_knowledge else None,
        knowledge_artifact=result.qualified_knowledge,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (KnowledgeQualificationStatus.PROVISIONAL, KnowledgeLifecycleStatus.PROVISIONAL),
        (KnowledgeQualificationStatus.QUALIFIED, KnowledgeLifecycleStatus.ACTIVE),
        (KnowledgeQualificationStatus.INSUFFICIENT, KnowledgeLifecycleStatus.ABSENT),
        (KnowledgeQualificationStatus.CONTESTED, KnowledgeLifecycleStatus.CONTESTED),
        (KnowledgeQualificationStatus.INVALIDATED, KnowledgeLifecycleStatus.INVALIDATED),
    ],
)
def test_single_assessment_mapping(status, expected) -> None:
    assert resolve_knowledge_lifecycle([_item(status, T1)]).lifecycle_status == expected


def test_empty_history_is_absent_for_the_explicit_proposition() -> None:
    state = resolve_knowledge_lifecycle([], proposition_key="proposition-P1")
    assert state.lifecycle_status == KnowledgeLifecycleStatus.ABSENT
    assert state.proposition_key == "proposition-P1"
    assert state.historical_qualification_count == 0
    assert state.reason_codes == ("no_qualification_history",)


def test_empty_history_requires_proposition_identity_and_hashes_it() -> None:
    with pytest.raises(ValueError, match="proposition_key is required"):
        resolve_knowledge_lifecycle([])

    p1 = resolve_knowledge_lifecycle([], proposition_key="proposition-P1")
    p2 = resolve_knowledge_lifecycle([], proposition_key="proposition-P2")
    assert p1.lifecycle_projection_id != p2.lifecycle_projection_id


def test_supplied_proposition_must_agree_with_nonempty_history() -> None:
    item = _item(KnowledgeQualificationStatus.PROVISIONAL, T1)
    with pytest.raises(ValueError, match="disagrees"):
        resolve_knowledge_lifecycle([item], proposition_key="other-proposition")


@pytest.mark.parametrize(
    ("timeline", "expected"),
    [
        (
            (KnowledgeQualificationStatus.QUALIFIED, KnowledgeQualificationStatus.CONTESTED),
            KnowledgeLifecycleStatus.CONTESTED,
        ),
        (
            (KnowledgeQualificationStatus.QUALIFIED, KnowledgeQualificationStatus.INVALIDATED),
            KnowledgeLifecycleStatus.INVALIDATED,
        ),
        (
            (KnowledgeQualificationStatus.QUALIFIED, KnowledgeQualificationStatus.PROVISIONAL),
            KnowledgeLifecycleStatus.PROVISIONAL,
        ),
        (
            (KnowledgeQualificationStatus.QUALIFIED, KnowledgeQualificationStatus.INSUFFICIENT),
            KnowledgeLifecycleStatus.ABSENT,
        ),
        (
            (KnowledgeQualificationStatus.INVALIDATED, KnowledgeQualificationStatus.QUALIFIED),
            KnowledgeLifecycleStatus.ACTIVE,
        ),
    ],
)
def test_newer_evaluation_controls_regression_and_requalification(timeline, expected) -> None:
    history = [_item(timeline[0], T1, "-old"), _item(timeline[1], T2, "-new")]
    assert resolve_knowledge_lifecycle(history).lifecycle_status == expected


def test_qualified_invalidated_qualified_requalifies() -> None:
    state = resolve_knowledge_lifecycle(
        [
            _item(KnowledgeQualificationStatus.QUALIFIED, T1, "-1"),
            _item(KnowledgeQualificationStatus.INVALIDATED, T2, "-2"),
            _item(KnowledgeQualificationStatus.QUALIFIED, T3, "-3"),
        ]
    )
    assert state.lifecycle_status == KnowledgeLifecycleStatus.ACTIVE
    assert state.authoritative_qualification_ids[0].endswith("-3")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeLifecycleStatus.ACTIVE,
        ),
        (
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeQualificationStatus.PROVISIONAL,
            KnowledgeLifecycleStatus.CONTESTED,
        ),
        (
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeQualificationStatus.INSUFFICIENT,
            KnowledgeLifecycleStatus.CONTESTED,
        ),
        (
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeQualificationStatus.CONTESTED,
            KnowledgeLifecycleStatus.CONTESTED,
        ),
        (
            KnowledgeQualificationStatus.QUALIFIED,
            KnowledgeQualificationStatus.INVALIDATED,
            KnowledgeLifecycleStatus.INVALIDATED,
        ),
        (
            KnowledgeQualificationStatus.PROVISIONAL,
            KnowledgeQualificationStatus.INSUFFICIENT,
            KnowledgeLifecycleStatus.CONTESTED,
        ),
    ],
)
def test_same_frontier_matrix(left, right, expected) -> None:
    state = resolve_knowledge_lifecycle([_item(left, T2, "-a"), _item(right, T2, "-b")])
    assert state.lifecycle_status == expected
    assert len(state.authoritative_qualification_ids) == 2
    assert bool(state.authoritative_knowledge_ids) is (expected == KnowledgeLifecycleStatus.ACTIVE)


def test_late_arrival_and_input_order_do_not_change_projection() -> None:
    newer = _item(KnowledgeQualificationStatus.INVALIDATED, T2, "-new")
    older = _item(KnowledgeQualificationStatus.QUALIFIED, T1, "-late")
    assert resolve_knowledge_lifecycle([newer, older]) == resolve_knowledge_lifecycle([older, newer])


def test_undated_rules_fail_conservatively() -> None:
    one = _item(KnowledgeQualificationStatus.QUALIFIED, None, "-one")
    assert resolve_knowledge_lifecycle([one, one]).lifecycle_status == KnowledgeLifecycleStatus.ACTIVE
    unresolved = resolve_knowledge_lifecycle([one, _item(KnowledgeQualificationStatus.PROVISIONAL, None, "-two")])
    assert unresolved.lifecycle_status == KnowledgeLifecycleStatus.CONTESTED
    assert "temporal_authority_unresolved" in unresolved.reason_codes
    known = resolve_knowledge_lifecycle([one, _item(KnowledgeQualificationStatus.INVALIDATED, T2, "-known")])
    assert known.lifecycle_status == KnowledgeLifecycleStatus.INVALIDATED
    assert one.qualification.qualification_id in known.unordered_qualification_ids


def test_mixed_propositions_are_rejected() -> None:
    first = _item(KnowledgeQualificationStatus.PROVISIONAL, T1, "-a")
    proposition = first.qualification.proposition.model_copy(update={"proposition_key": "other"})
    second_result = first.qualification.model_copy(update={"proposition": proposition, "qualification_id": "other-q"})
    second = first.model_copy(update={"qualification_record_id": uuid.uuid4(), "qualification": second_result})
    with pytest.raises(ValueError, match="exactly one proposition"):
        resolve_knowledge_lifecycle([first, second])


def test_history_shape_fails_closed_for_missing_or_forbidden_artifact() -> None:
    qualified = _result(KnowledgeQualificationStatus.QUALIFIED, T1)
    with pytest.raises(ValidationError, match="requires a knowledge artifact"):
        KnowledgeLifecycleHistoryItem(
            qualification_record_id=uuid.uuid4(), qualification=qualified, evaluation_watermark=T1
        )
    provisional = _result(KnowledgeQualificationStatus.PROVISIONAL, T1)
    with pytest.raises(ValidationError, match="must not have"):
        KnowledgeLifecycleHistoryItem(
            qualification_record_id=uuid.uuid4(),
            qualification=provisional,
            evaluation_watermark=T1,
            knowledge_record_id=uuid.uuid4(),
            knowledge_artifact=qualified.qualified_knowledge,
        )


def test_artifact_identity_and_proposition_disagreement_fail_closed() -> None:
    qualified = _result(KnowledgeQualificationStatus.QUALIFIED, T1)
    for artifact in (
        qualified.qualified_knowledge.model_copy(update={"qualification_id": "wrong"}),
        qualified.qualified_knowledge.model_copy(
            update={"proposition": qualified.proposition.model_copy(update={"proposition_key": "wrong"})}
        ),
    ):
        with pytest.raises(ValidationError, match="disagrees"):
            KnowledgeLifecycleHistoryItem(
                qualification_record_id=uuid.uuid4(),
                qualification=qualified,
                evaluation_watermark=T1,
                knowledge_record_id=uuid.uuid4(),
                knowledge_artifact=artifact,
            )


def test_read_adapter_discovers_artifact_by_foreign_key_then_rejects_copied_identity_corruption(
    monkeypatch,
) -> None:
    provisional = _result(KnowledgeQualificationStatus.PROVISIONAL, T1)
    qualification_record_id = uuid.uuid4()
    qualification_record = KnowledgeQualificationRecord(
        id=qualification_record_id,
        tenant_id="tenant-A",
        qualification_id=provisional.qualification_id,
        proposition_key=provisional.proposition.proposition_key,
        qualification_status=provisional.status.value,
        source_candidate_id=provisional.source_candidate_id,
        evaluation_watermark=T1,
        qualification_payload=provisional.model_dump(mode="json"),
        algorithm=provisional.algorithm,
    )
    qualified = _result(KnowledgeQualificationStatus.QUALIFIED, T1, "-artifact")
    corrupt_artifact = qualified.qualified_knowledge.model_copy(update={"qualification_id": "WRONG"})
    artifact_record = KnowledgeArtifactRecord(
        id=uuid.uuid4(),
        tenant_id="tenant-A",
        qualification_record_id=qualification_record_id,
        knowledge_id=corrupt_artifact.knowledge_id,
        proposition_key=corrupt_artifact.proposition.proposition_key,
        qualification_id="WRONG",
        source_candidate_id=corrupt_artifact.source_candidate_id,
        qualified_through_evaluated_at=corrupt_artifact.qualified_through_evaluated_at,
        proposition_payload=corrupt_artifact.proposition.model_dump(mode="json"),
        artifact_payload=corrupt_artifact.model_dump(mode="json"),
        algorithm=corrupt_artifact.algorithm,
    )

    class RepositoryStub:
        def __init__(self, session) -> None:
            assert session is caller_session

        def list_qualifications_for_proposition(self, **values):
            assert values == {"tenant_id": "tenant-A", "proposition_key": provisional.proposition.proposition_key}
            return [qualification_record]

        def list_artifacts_for_qualification_record_ids(self, **values):
            assert values == {
                "tenant_id": "tenant-A",
                "qualification_record_ids": [qualification_record_id],
            }
            return [artifact_record]

    caller_session = object()
    monkeypatch.setattr(
        "backend.services.knowledge.knowledge_lifecycle.KnowledgeRepository",
        RepositoryStub,
    )

    with pytest.raises(KnowledgeLedgerIntegrityError, match="artifact record columns disagree"):
        resolve_current_knowledge_state(
            caller_session,
            tenant_id="tenant-A",
            proposition_key=provisional.proposition.proposition_key,
        )

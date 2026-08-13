from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.services.durable_experience_consolidation import (
    DurableExperienceConsolidationService,
    DurableLearningHistoryError,
)
from backend.services.knowledge.knowledge_ledger import KnowledgeLedgerWriteResult, KnowledgeLedgerWriteStatus
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.decision_feedback import DecisionEpisodeReference
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from tests.unit.ontology.test_experience_intelligence import signal


class History:
    def __init__(self, records: list[EvidenceRecord]) -> None:
        self.records = records
        self.tenants: list[str] = []

    def list_candidates_for_tenant(self, *, tenant_id: str) -> list[EvidenceRecord]:
        self.tenants.append(tenant_id)
        return self.records


def canonical_signal(index: int, *, evaluated_at: datetime | None = None, episode_id: str | None = None):
    base = signal(index)
    return base.model_copy(
        update={
            "episode_reference": DecisionEpisodeReference(
                episode_id=episode_id or f"episode-{index}",
                decision_id=base.decision_id,
                recommendation_evidence_id=f"recommendation-{index}",
                mission_id=str(uuid4()),
                recommendation_execution_task_id=str(uuid4()),
                outcome_evaluation_evidence_id=f"outcome-{index}",
            ),
            "subject_semantic_signatures": (
                BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY),
            ),
            "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_conversion"),
            "intervention_key": "sales.schedule_discovery",
            "observation_verification_basis": ObservationVerificationBasis.SOURCE_SUPPLIED_UNDER_CONTRACT,
            "evaluated_at": evaluated_at or base.evaluated_at,
        }
    )


def record(index: int, payload: object, *, created_at: datetime | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        id=uuid4(),
        tenant_id="tenant-A",
        mission_id=uuid4(),
        evidence_type="execution_trace",
        evidence_source="decision_episode_materialization",
        summary="learning",
        structured_payload=payload,
        provenance_metadata={
            "action_name": "analysis.materialize_decision_learning_signal",
            "evidence_role": "decision_learning_signal",
        },
        materialization_reference={"action": "analysis.materialize_decision_learning_signal"},
        created_at=created_at or datetime(2026, 2, index, tzinfo=UTC),
    )


def ledger_write(*_: object, **__: object) -> KnowledgeLedgerWriteResult:
    return KnowledgeLedgerWriteResult(
        status=KnowledgeLedgerWriteStatus.RECORDED,
        qualification_id="qualification",
        proposition_key="proposition",
        qualification_record_id=uuid4(),
        persistence_committed=False,
    )


def test_consolidates_owner_signals_in_evaluated_chronology_through_existing_authorities(monkeypatch) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    signals = [canonical_signal(i, evaluated_at=base_time + timedelta(hours=i)) for i in (1, 2, 3)]
    records = [
        record(1, signals[0].model_dump(mode="json"), created_at=base_time + timedelta(hours=13)),
        record(2, signals[1].model_dump(mode="json"), created_at=base_time + timedelta(hours=11)),
        record(3, signals[2].model_dump(mode="json"), created_at=base_time + timedelta(hours=12)),
    ]
    writer = Mock(side_effect=ledger_write)
    monkeypatch.setattr("backend.services.durable_experience_consolidation.record_knowledge_qualification", writer)
    history = History(records)

    result = DurableExperienceConsolidationService(history=history).consolidate(Mock(), tenant_id="tenant-A")

    assert history.tenants == ["tenant-A"]
    candidate = result.experience.pattern_candidates[0]
    assert candidate.recurrence.independent_support_count == 3
    assert candidate.earliest_evaluated_at == signals[0].evaluated_at
    assert candidate.latest_evaluated_at == signals[2].evaluated_at
    assert result.qualifications[0].qualification.status.value == "qualified"
    writer.assert_called_once()


def test_duplicate_authoritative_episode_does_not_multiply_recurrence(monkeypatch) -> None:
    first = canonical_signal(1, episode_id="same-episode")
    duplicate = record(2, first.model_dump(mode="json"))
    monkeypatch.setattr("backend.services.durable_experience_consolidation.record_knowledge_qualification", Mock())
    original = record(1, first.model_dump(mode="json"))
    result = DurableExperienceConsolidationService(history=History([original, duplicate])).consolidate(
        Mock(), tenant_id="tenant-A"
    )
    assert result.experience.pattern_candidates == ()
    assert len(result.duplicate_evidence_record_ids) == 1
    assert result.duplicate_evidence_record_ids[0] in {str(original.id), str(duplicate.id)}


def test_malformed_canonical_history_fails_closed_before_ledger_write(monkeypatch) -> None:
    writer = Mock()
    monkeypatch.setattr("backend.services.durable_experience_consolidation.record_knowledge_qualification", writer)
    malformed = record(1, {"signal_id": "not-a-valid-signal"})
    with pytest.raises(DurableLearningHistoryError, match=str(malformed.id)):
        DurableExperienceConsolidationService(history=History([malformed])).consolidate(Mock(), tenant_id="tenant-A")
    writer.assert_not_called()


def test_reader_cannot_return_foreign_tenant_history(monkeypatch) -> None:
    writer = Mock()
    monkeypatch.setattr("backend.services.durable_experience_consolidation.record_knowledge_qualification", writer)
    foreign = record(1, canonical_signal(1).model_dump(mode="json"))
    foreign.tenant_id = "tenant-B"
    with pytest.raises(DurableLearningHistoryError, match="foreign-tenant"):
        DurableExperienceConsolidationService(history=History([foreign])).consolidate(Mock(), tenant_id="tenant-A")
    writer.assert_not_called()


def test_legacy_signal_is_visible_but_not_upgraded(monkeypatch) -> None:
    legacy = canonical_signal(1).model_copy(update={"episode_reference": None})
    monkeypatch.setattr("backend.services.durable_experience_consolidation.record_knowledge_qualification", Mock())
    result = DurableExperienceConsolidationService(
        history=History([record(1, legacy.model_dump(mode="json"))])
    ).consolidate(Mock(), tenant_id="tenant-A")
    assert result.legacy_signal_ids == (legacy.signal_id,)
    assert result.authoritative_episode_ids == ()
    assert result.experience.signatures[0].episode_id == f"legacy:{legacy.signal_id}"

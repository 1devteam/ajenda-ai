"""Production composition of durable learning history into Knowledge Ledger events."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.domain.evidence import EvidenceRecord
from backend.repositories.durable_learning_signal_repository import MATERIALIZATION_ACTION
from backend.services.knowledge.knowledge_ledger import (
    KnowledgeLedgerWriteResult,
    record_knowledge_qualification,
)
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.experience_intelligence import (
    ExperienceEpisodeInput,
    ExperienceIntelligenceResult,
    evaluate_experience_set,
)
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationResult,
    qualify_pattern_knowledge,
)
from backend.services.ontology.observation_attribution import (
    ObservationTimeProvenance,
    ObservationVerificationBasis,
)

LEARNING_SIGNAL_EVIDENCE_ROLE = "decision_learning_signal"


class DurableLearningHistoryError(RuntimeError):
    """Canonical durable history is corrupt or has contradictory provenance."""

    def __init__(self, message: str, *, evidence_ids: Sequence[uuid.UUID]) -> None:
        self.evidence_ids = tuple(str(item) for item in evidence_ids)
        super().__init__(f"{message}: {', '.join(self.evidence_ids)}")


class LearningHistoryReader(Protocol):
    def list_candidates_for_tenant(self, *, tenant_id: str) -> list[EvidenceRecord]: ...


class ConsolidatedQualification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    qualification: KnowledgeQualificationResult
    ledger_write: KnowledgeLedgerWriteResult


class ExperienceConsolidationResult(BaseModel):
    """Inspectable inventory of accepted, bounded, and rejected durable history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    records_inspected: tuple[str, ...] = ()
    valid_learning_signal_ids: tuple[str, ...] = ()
    authoritative_episode_ids: tuple[str, ...] = ()
    legacy_signal_ids: tuple[str, ...] = ()
    duplicate_evidence_record_ids: tuple[str, ...] = ()
    malformed_signal_ids: tuple[str, ...] = ()
    experience: ExperienceIntelligenceResult
    qualifications: tuple[ConsolidatedQualification, ...] = ()
    limitations: tuple[str, ...] = Field(
        default=(
            "durable_history_is_evidence_not_knowledge",
            "experience_remains_semantic_authority",
            "non_causal_consolidation",
            "no_applicability_or_runtime_execution",
        )
    )


def _artifact_action(record: EvidenceRecord) -> str:
    provenance_action = record.provenance_metadata.get("action_name")
    materialization_action = (record.materialization_reference or {}).get("action")
    if provenance_action and materialization_action and provenance_action != materialization_action:
        raise DurableLearningHistoryError(
            "durable learning artifact has contradictory action provenance", evidence_ids=[record.id]
        )
    action = provenance_action or materialization_action
    if not isinstance(action, str) or action != MATERIALIZATION_ACTION:
        raise DurableLearningHistoryError(
            "candidate is not owned by the canonical materialization action", evidence_ids=[record.id]
        )
    return action


def _observation_provenance(signal: DecisionLearningSignal) -> ObservationTimeProvenance:
    return {
        ObservationVerificationBasis.SOURCE_SUPPLIED_UNDER_CONTRACT: ObservationTimeProvenance.SOURCE_VERIFIED,
        ObservationVerificationBasis.INDEPENDENTLY_VERIFIED: ObservationTimeProvenance.SOURCE_VERIFIED,
        ObservationVerificationBasis.SYSTEM_DERIVED: ObservationTimeProvenance.DERIVED,
        ObservationVerificationBasis.CALLER_ASSERTED: ObservationTimeProvenance.CALLER_ASSERTED,
        ObservationVerificationBasis.UNKNOWN: ObservationTimeProvenance.UNKNOWN,
    }[signal.observation_verification_basis]


def _episode_input(signal: DecisionLearningSignal) -> ExperienceEpisodeInput:
    reference = signal.episode_reference
    return ExperienceEpisodeInput(
        episode_id=reference.episode_id if reference else f"legacy:{signal.signal_id}",
        signal=signal,
        observation_time_provenance=_observation_provenance(signal),
    )


class DurableExperienceConsolidationService:
    """Compose existing authorities without redefining any intelligence semantics."""

    def __init__(self, *, history: LearningHistoryReader) -> None:
        self._history = history

    def consolidate(self, session: Session, *, tenant_id: str) -> ExperienceConsolidationResult:
        records = self._history.list_candidates_for_tenant(tenant_id=tenant_id)
        parsed: list[tuple[EvidenceRecord, DecisionLearningSignal]] = []
        malformed: list[uuid.UUID] = []
        for record in records:
            try:
                if record.tenant_id != tenant_id:
                    raise DurableLearningHistoryError(
                        "history reader returned foreign-tenant evidence", evidence_ids=[record.id]
                    )
                _artifact_action(record)
                if record.provenance_metadata.get("evidence_role") != LEARNING_SIGNAL_EVIDENCE_ROLE:
                    raise ValueError("canonical learning artifact role is absent")
                parsed.append((record, DecisionLearningSignal.model_validate(record.structured_payload)))
            except DurableLearningHistoryError:
                raise
            except Exception:
                malformed.append(record.id)
        if malformed:
            raise DurableLearningHistoryError("malformed canonical learning history", evidence_ids=malformed)

        # Stable logical identity prevents persistence replay from becoming recurrence.
        by_episode: dict[str, tuple[EvidenceRecord, DecisionLearningSignal]] = {}
        duplicate_record_ids: list[str] = []
        for record, signal in sorted(parsed, key=lambda item: (item[1].evaluated_at, str(item[0].id))):
            episode = _episode_input(signal)
            previous = by_episode.get(episode.episode_id)
            if previous is not None:
                if previous[1] != signal:
                    raise DurableLearningHistoryError(
                        "logical episode identity has conflicting learning payloads",
                        evidence_ids=[previous[0].id, record.id],
                    )
                duplicate_record_ids.append(str(record.id))
                continue
            by_episode[episode.episode_id] = (record, signal)

        episodes = [_episode_input(item[1]) for item in by_episode.values()]
        experience = evaluate_experience_set(episodes)
        qualifications: list[ConsolidatedQualification] = []
        for candidate in experience.pattern_candidates:
            qualification = qualify_pattern_knowledge(candidate)
            write = record_knowledge_qualification(session, tenant_id=tenant_id, result=qualification)
            qualifications.append(ConsolidatedQualification(qualification=qualification, ledger_write=write))

        return ExperienceConsolidationResult(
            records_inspected=tuple(str(record.id) for record in records),
            valid_learning_signal_ids=tuple(sorted(signal.signal_id for _, signal in parsed)),
            authoritative_episode_ids=tuple(
                sorted(signal.episode_reference.episode_id for _, signal in parsed if signal.episode_reference)
            ),
            legacy_signal_ids=tuple(
                sorted(signal.signal_id for _, signal in parsed if signal.episode_reference is None)
            ),
            duplicate_evidence_record_ids=tuple(sorted(duplicate_record_ids)),
            malformed_signal_ids=(),
            experience=experience,
            qualifications=tuple(qualifications),
        )

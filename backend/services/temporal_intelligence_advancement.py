"""Bounded post-commit advancement between canonical intelligence owners.

This module decides only whether one of the two explicitly supported transitions
may be scheduled.  The scheduled ``tool.invoke`` task remains subject to the
normal queue, policy, worker-lease, dispatcher, action, and EvidenceBridge path.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.decision_episode_materialization import (
    DecisionEpisodeMaterializationRequest,
    DecisionEpisodeMaterializationService,
)
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.outcome import OutcomeEvaluation
from backend.services.tools.evidence_bridge import require_canonical_tool_action_evidence

OUTCOME_ACTION = "analysis.evaluate_outcome"
RECOMMENDATION_ACTION = "decision.recommend_next_action"
MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"
CONSOLIDATION_ACTION = "knowledge.consolidate_learning_history"
_NAMESPACE = uuid.NAMESPACE_URL


class TemporalTransition(StrEnum):
    """The complete, deliberately non-extensible transition set."""

    OUTCOME_TO_DECISION_EPISODE = "outcome_to_decision_episode_materialization"
    LEARNING_SIGNAL_TO_EXPERIENCE = "learning_signal_to_experience_consolidation"


class TemporalAdvancementState(StrEnum):
    """Distinguish ordinary ineligibility, rejection, execution, and failure."""

    NOT_ELIGIBLE = "not_eligible"
    ELIGIBLE = "eligible"
    ALREADY_ADVANCED = "already_advanced"
    ADVANCED = "advanced"
    BLOCKED = "blocked"
    FAILED = "failed"


class TemporalAdvancementResult(BaseModel):
    """Inspectable outcome of evaluating one durable upstream artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    transition: TemporalTransition
    state: TemporalAdvancementState
    source_evidence_id: str
    downstream_task_id: str | None = None
    reason: str


def _task_id(transition: TemporalTransition, tenant_id: str, source_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"ajenda:temporal-intelligence:v1:{transition.value}:{tenant_id}:{source_id}")


class TemporalIntelligenceAdvancementService:
    """Evaluate and schedule only the next existing canonical intelligence owner."""

    def __init__(self, *, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue

    def advance_completed_artifact(self, *, tenant_id: str, source_evidence_id: uuid.UUID) -> TemporalAdvancementResult:
        """Evaluate a durable EvidenceBridge row and schedule its bounded successor."""

        record = EvidenceRepository(self._session).get_for_tenant(evidence_id=source_evidence_id, tenant_id=tenant_id)
        if record is None:
            return self._result(
                TemporalTransition.OUTCOME_TO_DECISION_EPISODE,
                TemporalAdvancementState.BLOCKED,
                source_evidence_id,
                "source evidence is inaccessible in the active tenant",
            )
        action = record.provenance_metadata.get("action_name")
        if action == OUTCOME_ACTION:
            return self._advance_outcome(tenant_id=tenant_id, outcome_record=record)
        if action == MATERIALIZATION_ACTION:
            return self._advance_learning_signal(tenant_id=tenant_id, signal_record=record)
        return self._result(
            TemporalTransition.OUTCOME_TO_DECISION_EPISODE,
            TemporalAdvancementState.NOT_ELIGIBLE,
            source_evidence_id,
            "artifact owner has no bounded temporal transition",
        )

    def _advance_outcome(self, *, tenant_id: str, outcome_record: EvidenceRecord) -> TemporalAdvancementResult:
        transition = TemporalTransition.OUTCOME_TO_DECISION_EPISODE
        try:
            require_canonical_tool_action_evidence(
                session=self._session,
                record=outcome_record,
                expected_action=OUTCOME_ACTION,
                expected_role=None,
            )
            outcome = OutcomeEvaluation.model_validate(outcome_record.structured_payload)
            recommendation = self._unique_recommendation(tenant_id=tenant_id, mission_id=outcome_record.mission_id)
            if recommendation is None:
                return self._result(
                    transition,
                    TemporalAdvancementState.NOT_ELIGIBLE,
                    outcome_record.id,
                    "exactly one canonical mission recommendation is required",
                )
            raw_execution_ids = (
                outcome.attribution_evidence.execution_evidence_ids if outcome.attribution_evidence is not None else []
            )
            if not raw_execution_ids:
                return self._result(
                    transition,
                    TemporalAdvancementState.NOT_ELIGIBLE,
                    outcome_record.id,
                    "outcome does not establish canonical execution evidence ancestry",
                )
            request = DecisionEpisodeMaterializationRequest(
                recommendation_evidence_id=recommendation.id,
                outcome_evaluation_evidence_id=outcome_record.id,
                execution_evidence_ids=[uuid.UUID(item) for item in raw_execution_ids],
            )
            # Preflight delegates every semantic/provenance/chronology gate to the
            # existing owner; the coordinator does not reproduce those rules.
            materialized = DecisionEpisodeMaterializationService(
                session=self._session,
                evidence=EvidenceRepository(self._session),
                tasks=ExecutionTaskRepository(self._session),
            ).materialize(tenant_id=tenant_id, request=request)
            existing = self._existing_learning_signal(
                tenant_id=tenant_id,
                episode_id=materialized.episode_reference.episode_id,
            )
            if existing is not None:
                return self._result(
                    transition,
                    TemporalAdvancementState.ALREADY_ADVANCED,
                    outcome_record.id,
                    "canonical decision episode already exists",
                )
            return self._schedule(
                tenant_id=tenant_id,
                mission_id=outcome_record.mission_id,
                source=outcome_record,
                transition=transition,
                action=MATERIALIZATION_ACTION,
                action_input=request.model_dump(mode="json"),
            )
        except (ValueError, TypeError) as exc:
            return self._result(transition, TemporalAdvancementState.BLOCKED, outcome_record.id, str(exc))
        except Exception as exc:
            return self._result(transition, TemporalAdvancementState.FAILED, outcome_record.id, str(exc))

    def _advance_learning_signal(self, *, tenant_id: str, signal_record: EvidenceRecord) -> TemporalAdvancementResult:
        transition = TemporalTransition.LEARNING_SIGNAL_TO_EXPERIENCE
        try:
            require_canonical_tool_action_evidence(
                session=self._session,
                record=signal_record,
                expected_action=MATERIALIZATION_ACTION,
                expected_role="decision_learning_signal",
            )
            signal = DecisionLearningSignal.model_validate(signal_record.structured_payload)
            if signal.episode_reference is None:
                return self._result(
                    transition,
                    TemporalAdvancementState.NOT_ELIGIBLE,
                    signal_record.id,
                    "learning signal lacks an authoritative decision episode",
                )
            return self._schedule(
                tenant_id=tenant_id,
                mission_id=signal_record.mission_id,
                source=signal_record,
                transition=transition,
                action=CONSOLIDATION_ACTION,
                action_input={},
            )
        except (ValueError, TypeError) as exc:
            return self._result(transition, TemporalAdvancementState.BLOCKED, signal_record.id, str(exc))
        except Exception as exc:
            return self._result(transition, TemporalAdvancementState.FAILED, signal_record.id, str(exc))

    def _schedule(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        source: EvidenceRecord,
        transition: TemporalTransition,
        action: str,
        action_input: dict[str, object],
    ) -> TemporalAdvancementResult:
        task_id = _task_id(transition, tenant_id, source.id)
        existing = self._session.get(ExecutionTask, task_id)
        if existing is not None:
            if existing.tenant_id != tenant_id:
                return self._result(transition, TemporalAdvancementState.BLOCKED, source.id, "task identity conflict")
            return self._result(
                transition,
                TemporalAdvancementState.ALREADY_ADVANCED,
                source.id,
                "deterministic downstream task already exists",
                task_id,
            )
        task = ExecutionTask(
            id=task_id,
            tenant_id=tenant_id,
            mission_id=mission_id,
            title=f"Temporal intelligence: {transition.value}",
            description=f"Advance canonical evidence {source.id} to its next existing owner",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {"schema_version": 1, "action": action, "input": action_input},
                "temporal_intelligence": {
                    "schema_version": 1,
                    "transition": transition.value,
                    "source_evidence_id": str(source.id),
                },
            },
        )
        self._session.add(task)
        self._session.flush()
        # Persist the recoverable task before queue admission. Each authority owns
        # its own transaction; failure never rolls back the upstream artifact.
        self._session.commit()
        try:
            queued = ExecutionCoordinator(self._session, self._queue).queue_task(tenant_id=tenant_id, task_id=task_id)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        if not queued.ok:
            return self._result(
                transition,
                TemporalAdvancementState.BLOCKED,
                source.id,
                queued.reason or "runtime admission denied",
                task_id,
            )
        return self._result(
            transition,
            TemporalAdvancementState.ADVANCED,
            source.id,
            "canonical next-stage task admitted to the queue",
            task_id,
        )

    def _unique_recommendation(self, *, tenant_id: str, mission_id: uuid.UUID) -> EvidenceRecord | None:
        statement = select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.mission_id == mission_id,
            EvidenceRecord.provenance_metadata["evidence_role"].astext == "decision_recommendation_result",
            or_(
                EvidenceRecord.provenance_metadata["action_name"].astext == RECOMMENDATION_ACTION,
                EvidenceRecord.provenance_metadata["action_name"].astext == "knowledge.inform_decision",
            ),
        )
        records = list(self._session.scalars(statement))
        return records[0] if len(records) == 1 else None

    def _existing_learning_signal(self, *, tenant_id: str, episode_id: str) -> EvidenceRecord | None:
        statement = select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.provenance_metadata["action_name"].astext == MATERIALIZATION_ACTION,
            EvidenceRecord.provenance_metadata["evidence_role"].astext == "decision_learning_signal",
            EvidenceRecord.provenance_metadata["episode_id"].astext == episode_id,
        )
        records = list(self._session.scalars(statement))
        for record in records:
            require_canonical_tool_action_evidence(
                session=self._session,
                record=record,
                expected_action=MATERIALIZATION_ACTION,
                expected_role="decision_learning_signal",
            )
        if len(records) > 1:
            raise ValueError("duplicate canonical learning signals conflict for one episode")
        return records[0] if records else None

    @staticmethod
    def _result(
        transition: TemporalTransition,
        state: TemporalAdvancementState,
        source_id: uuid.UUID,
        reason: str,
        task_id: uuid.UUID | None = None,
    ) -> TemporalAdvancementResult:
        return TemporalAdvancementResult(
            transition=transition,
            state=state,
            source_evidence_id=str(source_id),
            downstream_task_id=str(task_id) if task_id else None,
            reason=reason,
        )

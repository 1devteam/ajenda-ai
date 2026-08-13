"""Authority for reconstructing learning episodes from durable owner artifacts.

Decision identity, decision semantics, execution identity, outcome identity, and
learning identity remain separate authorities.  This service only connects them
through tenant-scoped durable provenance; request callers cannot author history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.services.ontology.decision_feedback import (
    DecisionEpisodeReference,
    DecisionExecutionObservation,
    DecisionFeedbackResult,
    ExecutionFidelity,
    evaluate_decision_feedback,
)
from backend.services.ontology.decision_snapshot_builder import build_decision_snapshot_from_recommendation
from backend.services.ontology.outcome import OutcomeEvaluation
from backend.services.tools.schemas import ActionResult, DecisionRecommendInput, SideEffectClass

RECOMMENDATION_ACTION = "decision.recommend_next_action"
KNOWLEDGE_INFORMED_RECOMMENDATION_ACTION = "knowledge.inform_decision"
OUTCOME_ACTION = "analysis.evaluate_outcome"
MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"
_IDENTITY_NAMESPACE = uuid.NAMESPACE_URL


class DecisionEpisodeMaterializationRequest(BaseModel):
    """Artifact references accepted from a caller; no semantic assertions."""

    model_config = ConfigDict(extra="forbid")

    recommendation_evidence_id: uuid.UUID
    outcome_evaluation_evidence_id: uuid.UUID
    execution_evidence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class DecisionEpisodeInspectionTrace(BaseModel):
    """Immutable inventory of repository records read during materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_evidence_id: str
    recommendation_execution_task_id: str
    supporting_evidence_ids: tuple[str, ...] = ()
    outcome_evaluation_evidence_id: str
    execution_evidence_ids: tuple[str, ...] = ()

    def resource_references(self) -> list[str]:
        """Return deterministic, typed, de-duplicated inspection references."""

        evidence_ids = sorted(
            {
                self.recommendation_evidence_id,
                *self.supporting_evidence_ids,
                self.outcome_evaluation_evidence_id,
                *self.execution_evidence_ids,
            }
        )
        return [
            *(f"evidence:{evidence_id}" for evidence_id in evidence_ids),
            f"execution_task:{self.recommendation_execution_task_id}",
        ]


class DecisionEpisodeMaterializationResult(BaseModel):
    """The canonical feedback result and the durable artifacts that establish it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_reference: DecisionEpisodeReference
    inspection_trace: DecisionEpisodeInspectionTrace
    feedback: DecisionFeedbackResult


class EvidenceReader(Protocol):
    def get_for_tenant(self, *, evidence_id: uuid.UUID, tenant_id: str) -> EvidenceRecord | None: ...


class TaskReader(Protocol):
    def get_for_tenant(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask | None: ...


def _stable_identity(kind: str, *parts: str) -> str:
    canonical = ":".join(("ajenda", "decision-episode", "v1", kind, *parts))
    return f"{kind}_{uuid.uuid5(_IDENTITY_NAMESPACE, canonical).hex}"


def decision_id_for_recommendation(*, tenant_id: str, evidence_id: uuid.UUID) -> str:
    """Derive decision identity solely from the tenant-owned recommendation event."""

    return _stable_identity("dec", tenant_id, str(evidence_id), RECOMMENDATION_ACTION)


def _artifact_action(record: EvidenceRecord) -> str | None:
    action = record.provenance_metadata.get("action_name")
    reference = record.materialization_reference or {}
    materialized_action = reference.get("action")
    if action is not None and materialized_action is not None and action != materialized_action:
        raise ValueError("durable evidence action provenance is contradictory")
    resolved = action or materialized_action
    return resolved if isinstance(resolved, str) and resolved else None


def _parse_event_time(
    record: EvidenceRecord, field: str, *, payload: dict[str, object] | None = None
) -> datetime | None:
    raw = (payload or record.structured_payload).get(field)
    if raw is None:
        raw = record.provenance_metadata.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"durable {field} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"durable {field} must include a timezone")
    return parsed


class DecisionEpisodeMaterializationService:
    """Sole owner of durable decision-to-learning-episode reconstruction."""

    def __init__(self, *, evidence: EvidenceReader, tasks: TaskReader) -> None:
        self._evidence = evidence
        self._tasks = tasks

    def materialize(
        self,
        *,
        tenant_id: str,
        request: DecisionEpisodeMaterializationRequest,
    ) -> DecisionEpisodeMaterializationResult:
        recommendation = self._required_evidence(
            tenant_id=tenant_id,
            evidence_id=request.recommendation_evidence_id,
            role="recommendation",
        )
        recommendation_action = _artifact_action(recommendation)
        if recommendation_action not in {
            RECOMMENDATION_ACTION,
            KNOWLEDGE_INFORMED_RECOMMENDATION_ACTION,
        }:
            raise ValueError(
                "durable artifact does not represent decision.recommend_next_action "
                "or its governed knowledge-informed composition"
            )
        if recommendation.provenance_metadata.get("evidence_role") != "decision_recommendation_result":
            raise ValueError("recommendation artifact has the wrong durable evidence role")
        if recommendation.execution_task_id is None:
            raise ValueError("recommendation artifact requires execution-task provenance")

        recommendation_task = self._tasks.get_for_tenant(
            task_id=recommendation.execution_task_id,
            tenant_id=tenant_id,
        )
        if recommendation_task is None:
            raise ValueError("decision episode artifact is inaccessible")
        if recommendation_task.mission_id != recommendation.mission_id:
            raise ValueError("recommendation task and evidence mission provenance disagree")
        invocation = recommendation_task.metadata_json.get("tool_invocation")
        if not isinstance(invocation, dict) or invocation.get("action") != recommendation_action:
            raise ValueError("recommendation task does not prove the expected decision action")
        recommendation_payload = recommendation.structured_payload
        raw_input = invocation.get("input")
        if recommendation_action == KNOWLEDGE_INFORMED_RECOMMENDATION_ACTION:
            if recommendation.provenance_metadata.get("delegated_decision_action") != RECOMMENDATION_ACTION:
                raise ValueError("knowledge-informed recommendation lacks canonical Decision delegation")
            raw_input = recommendation_payload.get("decision_input")
            nested_result = recommendation_payload.get("decision_result")
            if not isinstance(nested_result, dict):
                raise ValueError("knowledge-informed recommendation lacks canonical Decision output")
            recommendation_payload = nested_result
        if not isinstance(raw_input, dict):
            raise ValueError("recommendation task does not contain durable structured input")
        recommendation_input = DecisionRecommendInput.model_validate(raw_input)
        decided_at = _parse_event_time(recommendation, "decided_at", payload=recommendation_payload)
        if decided_at is None:
            raise ValueError("recommendation artifact does not establish decision chronology")

        raw_supporting_ids = recommendation_payload.get("supporting_evidence_ids", [])
        if not isinstance(raw_supporting_ids, list) or not all(isinstance(item, str) for item in raw_supporting_ids):
            raise ValueError("recommendation supporting evidence identities must be a list of UUID strings")
        supporting_ids = sorted({self._uuid(item) for item in raw_supporting_ids}, key=str)
        supporting = [
            self._required_evidence(tenant_id=tenant_id, evidence_id=evidence_id, role="supporting")
            for evidence_id in supporting_ids
        ]
        self._require_same_mission(recommendation, supporting, "supporting evidence")
        facts_by_id = {fact.evidence_id: fact for fact in recommendation_input.evidence}
        for record in supporting:
            fact = facts_by_id.get(str(record.id))
            if fact is None:
                raise ValueError("durable supporting evidence was not part of the recommendation input")
            durable_lineage = record.provenance_metadata.get("evidence_lineage")
            if fact.lineage is not None and durable_lineage is not None:
                if fact.lineage.model_dump(mode="json") != durable_lineage:
                    raise ValueError("recommendation input lineage contradicts durable supporting evidence")
        decision_id = decision_id_for_recommendation(
            tenant_id=tenant_id,
            evidence_id=request.recommendation_evidence_id,
        )
        recommendation_result = ActionResult(
            action=RECOMMENDATION_ACTION,
            provider=str(recommendation.provenance_metadata.get("tool_provider") or "ajenda_decision"),
            side_effect_class=SideEffectClass.NONE,
            output=recommendation_payload,
            summary=recommendation.summary,
            confidence=recommendation.confidence,
        )
        snapshot = build_decision_snapshot_from_recommendation(
            decision_id=decision_id,
            tenant_id=tenant_id,
            recommendation_input=recommendation_input,
            recommendation_result=recommendation_result,
            evidence_records=[recommendation, *supporting],
            decided_at=decided_at,
        )

        outcome_record = self._required_evidence(
            tenant_id=tenant_id,
            evidence_id=request.outcome_evaluation_evidence_id,
            role="outcome",
        )
        self._require_action(outcome_record, OUTCOME_ACTION)
        self._require_same_mission(recommendation, [outcome_record], "outcome evidence")
        outcome = OutcomeEvaluation.model_validate(outcome_record.structured_payload)
        if outcome.evaluated_at < decided_at:
            raise ValueError("outcome evaluation cannot precede the durable decision event")
        if outcome.observed_at is not None and outcome.observed_at < decided_at:
            raise ValueError("outcome observation cannot precede the durable decision event")

        execution_ids_to_resolve = sorted(set(request.execution_evidence_ids), key=str)
        execution_records = [
            self._required_evidence(tenant_id=tenant_id, evidence_id=evidence_id, role="execution")
            for evidence_id in execution_ids_to_resolve
        ]
        self._require_same_mission(recommendation, execution_records, "execution evidence")
        execution = self._execution_observation(snapshot.intervention_key, execution_records)
        if (
            execution.executed_at is not None
            and outcome.observed_at is not None
            and outcome.observed_at < execution.executed_at
        ):
            raise ValueError("outcome observation cannot precede proven execution")

        execution_ids = tuple(sorted(str(item.id) for item in execution_records))
        episode_id = _stable_identity(
            "dep",
            tenant_id,
            str(recommendation.id),
            str(outcome_record.id),
            *execution_ids,
        )
        reference = DecisionEpisodeReference(
            episode_id=episode_id,
            decision_id=decision_id,
            recommendation_evidence_id=str(recommendation.id),
            mission_id=str(recommendation.mission_id),
            recommendation_execution_task_id=str(recommendation.execution_task_id),
            outcome_evaluation_evidence_id=str(outcome_record.id),
            execution_evidence_ids=execution_ids,
        )
        feedback = evaluate_decision_feedback(
            snapshot=snapshot,
            execution=execution,
            outcome=outcome,
            feedback_id=_stable_identity("dfb", episode_id),
            signal_id=_stable_identity("sig", episode_id),
            episode_reference=reference,
            evaluated_at=outcome.evaluated_at,
        )
        inspection_trace = DecisionEpisodeInspectionTrace(
            recommendation_evidence_id=str(recommendation.id),
            recommendation_execution_task_id=str(recommendation.execution_task_id),
            supporting_evidence_ids=tuple(sorted({str(record.id) for record in supporting})),
            outcome_evaluation_evidence_id=str(outcome_record.id),
            execution_evidence_ids=execution_ids,
        )
        return DecisionEpisodeMaterializationResult(
            episode_reference=reference,
            inspection_trace=inspection_trace,
            feedback=feedback,
        )

    def _required_evidence(self, *, tenant_id: str, evidence_id: uuid.UUID, role: str) -> EvidenceRecord:
        record = self._evidence.get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)
        if record is None:
            raise ValueError(f"decision episode {role} artifact is inaccessible")
        return record

    @staticmethod
    def _require_action(record: EvidenceRecord, expected: str) -> None:
        if _artifact_action(record) != expected:
            raise ValueError(f"durable artifact does not represent {expected}")

    @staticmethod
    def _require_same_mission(anchor: EvidenceRecord, records: list[EvidenceRecord], label: str) -> None:
        if any(record.mission_id != anchor.mission_id for record in records):
            raise ValueError(f"{label} mission provenance disagrees with the recommendation")

    @staticmethod
    def _uuid(value: object) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("supporting evidence identity must be a durable UUID") from exc

    @staticmethod
    def _execution_observation(
        intervention_key: str | None,
        records: list[EvidenceRecord],
    ) -> DecisionExecutionObservation:
        if not records:
            return DecisionExecutionObservation(fidelity=ExecutionFidelity.EXECUTION_UNKNOWN)
        actions = {_artifact_action(record) for record in records}
        if None in actions or len(actions) != 1:
            raise ValueError("execution artifacts must establish one unambiguous executed action")
        executed_action = next(iter(actions))
        if executed_action in {RECOMMENDATION_ACTION, OUTCOME_ACTION, MATERIALIZATION_ACTION}:
            raise ValueError("semantic analysis artifacts cannot stand in for execution evidence")
        times = [_parse_event_time(record, "executed_at") for record in records]
        known_times = {item for item in times if item is not None}
        if len(known_times) > 1:
            raise ValueError("execution artifacts contain contradictory execution chronology")
        fidelity = (
            ExecutionFidelity.EXECUTED_AS_RECOMMENDED
            if intervention_key is not None and executed_action == intervention_key
            else ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION
        )
        return DecisionExecutionObservation(
            fidelity=fidelity,
            executed_action_ref=executed_action,
            execution_evidence_ids=sorted(str(record.id) for record in records),
            execution_event_ids=sorted(str(record.execution_task_id) for record in records if record.execution_task_id),
            executed_at=next(iter(known_times), None),
            material_variations=([] if fidelity == ExecutionFidelity.EXECUTED_AS_RECOMMENDED else ["action_mismatch"]),
        )

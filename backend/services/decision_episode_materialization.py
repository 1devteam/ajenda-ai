"""Authority for reconstructing learning episodes from durable owner artifacts.

Decision identity, decision semantics, execution identity, outcome identity, and
learning identity remain separate authorities.  This service only connects them
through tenant-scoped durable provenance; request callers cannot author history.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.business_understanding import BusinessMeasurement, BusinessMeasurementPairing, BusinessNeedRevision
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
)
from backend.services.ontology.business_impact_observation import BusinessImpactObservation
from backend.services.ontology.decision_feedback import (
    DecisionEpisodeReference,
    DecisionExecutionObservation,
    DecisionFeedbackResult,
    ExecutionFidelity,
    evaluate_decision_feedback,
)
from backend.services.ontology.decision_snapshot_builder import build_decision_snapshot_from_recommendation
from backend.services.ontology.evidence_lineage import EvidenceOriginType
from backend.services.ontology.outcome import OutcomeEvaluation
from backend.services.tools.evidence_bridge import require_canonical_tool_action_evidence
from backend.services.tools.schemas import ActionResult, DecisionRecommendInput, EvidenceFact, SideEffectClass

RECOMMENDATION_ACTION = "decision.recommend_next_action"
OUTCOME_ACTION = "analysis.evaluate_outcome"
MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"
_IDENTITY_NAMESPACE = uuid.NAMESPACE_URL


class DecisionEpisodeMaterializationRequest(BaseModel):
    """Artifact references accepted from a caller; no semantic assertions."""

    model_config = ConfigDict(extra="forbid")

    recommendation_evidence_id: uuid.UUID | None = None
    outcome_evaluation_evidence_id: uuid.UUID | None = None
    execution_evidence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    impact_revision_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_materialization_mode(self) -> DecisionEpisodeMaterializationRequest:
        legacy = self.recommendation_evidence_id is not None or self.outcome_evaluation_evidence_id is not None
        impact = self.impact_revision_id is not None
        if legacy == impact:
            raise ValueError("materialization requires exactly one episode provenance mode")
        if legacy:
            if self.recommendation_evidence_id is None or self.outcome_evaluation_evidence_id is None:
                raise ValueError("mission decision materialization requires recommendation and outcome evidence")
        elif self.execution_evidence_ids:
            raise ValueError("business impact materialization must not claim execution evidence")
        return self


class DecisionEpisodeInspectionTrace(BaseModel):
    """Immutable inventory of repository records read during materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_evidence_id: str | None = None
    recommendation_execution_task_id: str | None = None
    supporting_evidence_ids: tuple[str, ...] = ()
    outcome_evaluation_evidence_id: str | None = None
    execution_evidence_ids: tuple[str, ...] = ()
    impact_revision_id: str | None = None
    accepted_measurement_pairing_id: str | None = None
    baseline_measurement_id: str | None = None
    observed_measurement_id: str | None = None

    def resource_references(self) -> list[str]:
        """Return deterministic, typed, de-duplicated inspection references."""

        evidence_ids = sorted(
            {
                *([self.recommendation_evidence_id] if self.recommendation_evidence_id else []),
                *self.supporting_evidence_ids,
                *([self.outcome_evaluation_evidence_id] if self.outcome_evaluation_evidence_id else []),
                *self.execution_evidence_ids,
            }
        )
        return [
            *(f"evidence:{evidence_id}" for evidence_id in evidence_ids),
            *(
                [f"execution_task:{self.recommendation_execution_task_id}"]
                if self.recommendation_execution_task_id
                else []
            ),
            *([f"business_need_revision:{self.impact_revision_id}"] if self.impact_revision_id else []),
            *(
                [f"business_measurement_pairing:{self.accepted_measurement_pairing_id}"]
                if self.accepted_measurement_pairing_id
                else []
            ),
            *([f"business_measurement:{self.baseline_measurement_id}"] if self.baseline_measurement_id else []),
            *([f"business_measurement:{self.observed_measurement_id}"] if self.observed_measurement_id else []),
        ]


class DecisionEpisodeMaterializationResult(BaseModel):
    """The canonical feedback result and the durable artifacts that establish it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_reference: DecisionEpisodeReference
    inspection_trace: DecisionEpisodeInspectionTrace
    feedback: DecisionFeedbackResult | None = None
    business_impact_observation: BusinessImpactObservation | None = None

    @model_validator(mode="after")
    def validate_result_kind(self) -> DecisionEpisodeMaterializationResult:
        if self.episode_reference.episode_kind == "business_impact":
            if self.feedback is not None or self.business_impact_observation is None:
                raise ValueError("business impact episode cannot be presented as Decision feedback")
        elif self.feedback is None or self.business_impact_observation is not None:
            raise ValueError("mission decision episode requires Decision feedback only")
        return self


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


def _parse_event_time(record: EvidenceRecord, field: str) -> datetime | None:
    raw = record.structured_payload.get(field)
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

    def __init__(self, *, session: Session, evidence: EvidenceReader, tasks: TaskReader) -> None:
        self._session = session
        self._evidence = evidence
        self._tasks = tasks

    def materialize(
        self,
        *,
        tenant_id: str,
        request: DecisionEpisodeMaterializationRequest,
    ) -> DecisionEpisodeMaterializationResult:
        if request.impact_revision_id is not None:
            return self._materialize_business_impact(tenant_id=tenant_id, impact_revision_id=request.impact_revision_id)
        assert request.recommendation_evidence_id is not None
        assert request.outcome_evaluation_evidence_id is not None
        recommendation = self._required_evidence(
            tenant_id=tenant_id,
            evidence_id=request.recommendation_evidence_id,
            role="recommendation",
        )
        artifact_action = _artifact_action(recommendation)
        composed = artifact_action == "knowledge.inform_decision"
        if artifact_action != RECOMMENDATION_ACTION and not composed:
            raise ValueError(f"durable artifact does not represent {RECOMMENDATION_ACTION}")
        expected_task_action = "knowledge.inform_decision" if composed else RECOMMENDATION_ACTION
        if recommendation.provenance_metadata.get("evidence_role") != "decision_recommendation_result":
            raise ValueError("recommendation artifact has the wrong durable evidence role")
        require_canonical_tool_action_evidence(
            session=self._session,
            record=recommendation,
            expected_action=expected_task_action,
            expected_role="decision_recommendation_result",
        )
        if composed and (
            recommendation.provenance_metadata.get("composed_action") != RECOMMENDATION_ACTION
            or recommendation.provenance_metadata.get("composition_schema_version") != 1
        ):
            raise ValueError("Knowledge recommendation does not prove canonical Decision composition")
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
        if not isinstance(invocation, dict) or invocation.get("action") != expected_task_action:
            raise ValueError("recommendation task does not prove the expected decision action")
        raw_input = invocation.get("input")
        if not isinstance(raw_input, dict):
            raise ValueError("recommendation task does not contain durable structured input")
        if composed:
            from backend.services.tools.knowledge_actions import KnowledgeInformedDecisionSupportInput

            owner_input = KnowledgeInformedDecisionSupportInput.model_validate(raw_input)
            raw_decision_input = recommendation.structured_payload.get("decision_input")
            raw_scoring_input = recommendation.structured_payload.get("scoring_decision_input")
            recommendation_output = recommendation.structured_payload.get("decision_result")
            if (
                not isinstance(raw_decision_input, dict)
                or not isinstance(raw_scoring_input, dict)
                or not isinstance(recommendation_output, dict)
            ):
                raise ValueError("Knowledge recommendation lacks scoring/materialization Decision input/output")
            recommendation_input = DecisionRecommendInput.model_validate(raw_decision_input)
            scoring_input = DecisionRecommendInput.model_validate(raw_scoring_input)
            self._validate_composed_decision_input(owner_input.decision, scoring_input)
            self._validate_materialization_decision_input(scoring_input, recommendation_input)
        else:
            recommendation_input = DecisionRecommendInput.model_validate(raw_input)
            recommendation_output = recommendation.structured_payload
        decided_at = _parse_event_time(recommendation, "decided_at")
        if decided_at is None and composed:
            raw_decided_at = recommendation_output.get("decided_at")
            if isinstance(raw_decided_at, str):
                decided_at = datetime.fromisoformat(raw_decided_at.replace("Z", "+00:00"))
                if decided_at.tzinfo is None or decided_at.utcoffset() is None:
                    raise ValueError("durable decided_at must include a timezone")
        if decided_at is None:
            raise ValueError("recommendation artifact does not establish decision chronology")

        raw_supporting_ids = recommendation_output.get("supporting_evidence_ids", [])
        if not isinstance(raw_supporting_ids, list) or not all(isinstance(item, str) for item in raw_supporting_ids):
            raise ValueError("recommendation supporting evidence identities must be a list of UUID strings")
        supporting_ids = sorted({self._uuid(item) for item in raw_supporting_ids}, key=str)
        supporting = [
            self._required_evidence(tenant_id=tenant_id, evidence_id=evidence_id, role="supporting")
            for evidence_id in supporting_ids
        ]
        for record in supporting:
            matching_facts = [
                fact
                for fact in recommendation_input.evidence
                if fact.evidence_id == str(record.id) or str(record.id) in fact.durable_source_evidence_ids
            ]
            if not matching_facts:
                raise ValueError("durable supporting evidence was not part of the recommendation input")
            historical_knowledge_source = composed and any(
                str(record.id) in fact.durable_source_evidence_ids
                and fact.lineage is not None
                and fact.lineage.origin_type == EvidenceOriginType.DERIVED_FACT
                for fact in matching_facts
            )
            if historical_knowledge_source and (
                _artifact_action(record) != MATERIALIZATION_ACTION
                or record.provenance_metadata.get("evidence_role") != "decision_learning_signal"
            ):
                raise ValueError("Knowledge ancestry is not a durable Decision learning signal")
            if historical_knowledge_source:
                require_canonical_tool_action_evidence(
                    session=self._session,
                    record=record,
                    expected_action=MATERIALIZATION_ACTION,
                    expected_role="decision_learning_signal",
                )
            if not historical_knowledge_source and record.mission_id != recommendation.mission_id:
                raise ValueError("supporting evidence mission provenance disagrees with the recommendation")
            durable_lineage = record.provenance_metadata.get("evidence_lineage")
            for fact in matching_facts:
                if (
                    not historical_knowledge_source
                    and fact.evidence_id == str(record.id)
                    and fact.lineage is not None
                    and durable_lineage is not None
                    and (fact.lineage.model_dump(mode="json") != durable_lineage)
                ):
                    raise ValueError("recommendation input lineage contradicts durable supporting evidence")
        decision_id = decision_id_for_recommendation(
            tenant_id=tenant_id,
            evidence_id=request.recommendation_evidence_id,
        )
        recommendation_result = ActionResult(
            action=RECOMMENDATION_ACTION,
            provider=str(recommendation.provenance_metadata.get("tool_provider") or "ajenda_decision"),
            side_effect_class=SideEffectClass.NONE,
            output=recommendation_output,
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
        require_canonical_tool_action_evidence(
            session=self._session,
            record=outcome_record,
            expected_action=OUTCOME_ACTION,
            expected_role=None,
        )
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
        for record in execution_records:
            executed_action = _artifact_action(record)
            if executed_action is None:
                raise ValueError("execution artifact does not establish an action owner")
            require_canonical_tool_action_evidence(
                session=self._session,
                record=record,
                expected_action=executed_action,
                expected_role=None,
            )
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

    def _materialize_business_impact(
        self,
        *,
        tenant_id: str,
        impact_revision_id: uuid.UUID,
    ) -> DecisionEpisodeMaterializationResult:
        """Materialize one verified Layer-2 impact episode without inventing work.

        This is deliberately not a recommendation-task reconstruction.  The
        selected candidate and frozen successor contract come from the later
        measurement's immutable reference; the outcome comes from canonical
        evidence; and execution remains explicitly unknown.
        """

        impact_revision = self._session.scalar(
            select(BusinessNeedRevision).where(
                BusinessNeedRevision.id == impact_revision_id,
                BusinessNeedRevision.tenant_id == tenant_id,
                BusinessNeedRevision.status == "impact_monitored",
            )
        )
        if impact_revision is None or not isinstance(impact_revision.impact_assessment, dict):
            raise ValueError("business impact revision is inaccessible or incomplete")
        impact = impact_revision.impact_assessment
        pairing_id = self._uuid(impact.get("accepted_measurement_pairing_id"))
        evidence_id = self._uuid(impact.get("outcome_evidence_id"))
        evaluation_id = impact.get("outcome_evaluation_id")
        baseline_id = self._uuid(impact.get("baseline_measurement_id"))
        observed_id = self._uuid(impact.get("observed_measurement_id"))
        if not isinstance(evaluation_id, str) or not evaluation_id:
            raise ValueError("business impact revision lacks an outcome evaluation identity")

        pairing = self._session.scalar(
            select(BusinessMeasurementPairing).where(
                BusinessMeasurementPairing.id == pairing_id,
                BusinessMeasurementPairing.tenant_id == tenant_id,
            )
        )
        if (
            pairing is None
            or pairing.status != "evaluated"
            or pairing.impact_revision_id != impact_revision.id
            or pairing.outcome_evidence_id != evidence_id
            or pairing.outcome_evaluation_id != evaluation_id
            or pairing.baseline_measurement_id != baseline_id
            or pairing.observed_measurement_id != observed_id
            or pairing.need_id != impact_revision.need_id
            or pairing.need_revision_id != impact_revision.previous_revision_id
        ):
            raise ValueError("business impact revision contradicts its accepted measurement pairing")

        baseline = self._measurement_for_tenant(tenant_id=tenant_id, measurement_id=baseline_id)
        observed = self._measurement_for_tenant(tenant_id=tenant_id, measurement_id=observed_id)
        reference = observed.intended_measurement_reference
        if not isinstance(reference, dict):
            raise ValueError("business impact episode requires a frozen successor measurement contract")
        strategy = reference.get("strategy_lineage")
        contract = reference.get("measurement_contract")
        if (
            pairing.successor_contract_id != reference.get("contract_id")
            or not isinstance(strategy, dict)
            or not isinstance(contract, dict)
            or strategy.get("need_id") != impact_revision.need_id
            or strategy.get("need_revision") != pairing.need_revision
            or contract.get("baseline_measurement_id") != str(baseline.id)
        ):
            raise ValueError("business impact episode contradicts its frozen successor contract")
        candidate = strategy.get("selected_candidate_response_key")
        if not isinstance(candidate, str) or not candidate:
            raise ValueError("business impact episode lacks selected candidate provenance")

        # Reconstruct the successor contract from the immutable persisted mission
        # snapshot, rather than trusting a copy embedded in the later measurement.
        try:
            BusinessUnderstandingService(self._session).require_frozen_successor_reference(
                tenant_id=tenant_id, measurement=observed
            )
        except BusinessUnderstandingValidationError as exc:
            raise ValueError("business impact episode contradicts persisted successor mission authority") from exc

        try:
            assessment_id = self._uuid(strategy.get("assessment_id"))
        except ValueError as exc:
            raise ValueError("business impact episode has no valid originating assessment identity") from exc
        assessment = BusinessUnderstandingRepository(self._session).get_assessment_for_tenant(
            tenant_id=tenant_id, assessment_id=assessment_id
        )
        assessment_payload = assessment.assessment_json if assessment is not None else None
        candidates = assessment_payload.get("candidate_responses") if isinstance(assessment_payload, dict) else None
        if (
            assessment is None
            or assessment.need_id != impact_revision.need_id
            or assessment.need_revision != pairing.need_revision
            or assessment.assessment_fingerprint != strategy.get("assessment_fingerprint")
            or not isinstance(candidates, list)
            or not any(isinstance(item, dict) and item.get("response_key") == candidate for item in candidates)
        ):
            raise ValueError("business impact episode contradicts its originating assessment authority")

        outcome_record = self._required_evidence(tenant_id=tenant_id, evidence_id=evidence_id, role="outcome")
        self._require_action(outcome_record, OUTCOME_ACTION)
        require_canonical_tool_action_evidence(
            session=self._session,
            record=outcome_record,
            expected_action=OUTCOME_ACTION,
            expected_role=None,
        )
        outcome = OutcomeEvaluation.model_validate(outcome_record.structured_payload)
        if outcome.outcome_evaluation_id != evaluation_id or outcome.accepted_measurement_pairing_id != pairing.id:
            raise ValueError("canonical outcome evidence contradicts the accepted pairing")
        if pairing.evaluated_at != outcome.evaluated_at:
            raise ValueError("accepted pairing evaluation timestamp contradicts canonical outcome evidence")

        episode_id = _stable_identity(
            "bip",
            tenant_id,
            str(impact_revision.id),
            str(pairing.id),
            str(outcome_record.id),
            outcome.outcome_evaluation_id,
        )
        provenance = {
            "impact_revision_id": str(impact_revision.id),
            "need_id": impact_revision.need_id,
            "accepted_measurement_pairing_id": str(pairing.id),
            "baseline_measurement_id": str(baseline.id),
            "observed_measurement_id": str(observed.id),
            "outcome_evidence_id": str(outcome_record.id),
            "outcome_evaluation_id": outcome.outcome_evaluation_id,
            "frozen_successor_contract": reference,
        }
        episode_reference = DecisionEpisodeReference(
            schema_version=2,
            episode_id=episode_id,
            decision_id=None,
            episode_kind="business_impact",
            outcome_evaluation_evidence_id=str(outcome_record.id),
            business_impact_provenance=provenance,
        )
        source_kinds = {"customer_attested", "source_verified"}
        if baseline.source_kind not in source_kinds or observed.source_kind not in source_kinds:
            raise ValueError("business impact has an unrecognized measurement source trust class")
        observation = BusinessImpactObservation(
            signal_id=_stable_identity("bio", episode_id),
            episode_reference=episode_reference,
            selected_candidate_response_key=candidate,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=observed.id,
            baseline_source_kind=cast(Literal["customer_attested", "source_verified"], baseline.source_kind),
            observed_source_kind=cast(Literal["customer_attested", "source_verified"], observed.source_kind),
            goal_id=outcome.goal_id,
            subject_refs=tuple(outcome.subject_refs),
            kpi_semantic_signatures=outcome.kpi_semantic_signatures,
            kpi_deltas=tuple(outcome.kpi_deltas),
            outcome_evaluation_id=outcome.outcome_evaluation_id,
            outcome_status=outcome.status,
            measured_outcome_attribution=outcome.attribution,
            observation_verification_basis=outcome.observation_timing.verification_basis,
            observed_at=observed.observed_at,
            evaluated_at=outcome.evaluated_at,
        )
        trace = DecisionEpisodeInspectionTrace(
            outcome_evaluation_evidence_id=str(outcome_record.id),
            impact_revision_id=str(impact_revision.id),
            accepted_measurement_pairing_id=str(pairing.id),
            baseline_measurement_id=str(baseline.id),
            observed_measurement_id=str(observed.id),
        )
        return DecisionEpisodeMaterializationResult(
            episode_reference=episode_reference,
            inspection_trace=trace,
            business_impact_observation=observation,
        )

    @staticmethod
    def _validate_composed_decision_input(
        owner_input: DecisionRecommendInput,
        composed_input: DecisionRecommendInput,
    ) -> None:
        """Prove Knowledge only appended derived facts and composition context."""

        owner_dump = owner_input.model_dump(mode="json", exclude={"evidence", "context"})
        composed_dump = composed_input.model_dump(mode="json", exclude={"evidence", "context"})
        if owner_dump != composed_dump:
            raise ValueError("Knowledge composition changed Decision-owned semantics")
        owner_facts = [item.model_dump(mode="json") for item in owner_input.evidence]
        composed_facts = [item.model_dump(mode="json") for item in composed_input.evidence]
        if composed_facts[: len(owner_facts)] != owner_facts:
            raise ValueError("Knowledge composition changed caller-provided Decision evidence")
        derived = composed_input.evidence[len(owner_facts) :]
        if any(
            fact.lineage is None
            or fact.lineage.origin_type != EvidenceOriginType.DERIVED_FACT
            or not fact.durable_source_evidence_ids
            for fact in derived
        ):
            raise ValueError("Knowledge composition appended non-derived Decision evidence")
        expected_context = {
            key: value for key, value in composed_input.context.items() if key != "knowledge_decision_support"
        }
        if expected_context != owner_input.context:
            raise ValueError("Knowledge composition changed caller-provided Decision context")

    @staticmethod
    def _validate_materialization_decision_input(
        scoring_input: DecisionRecommendInput,
        materialization_input: DecisionRecommendInput,
    ) -> None:
        """Prove durable-ID normalization preserved the scored derived semantics."""

        scoring_owner = scoring_input.model_dump(mode="json", exclude={"evidence"})
        materialization_owner = materialization_input.model_dump(mode="json", exclude={"evidence"})
        if scoring_owner != materialization_owner:
            raise ValueError("Knowledge materialization changed canonical Decision input semantics")

        ordinary_scoring = [fact for fact in scoring_input.evidence if not fact.durable_source_evidence_ids]
        ordinary_materialized = [
            fact for fact in materialization_input.evidence if not fact.durable_source_evidence_ids
        ]
        if ordinary_scoring != ordinary_materialized:
            raise ValueError("Knowledge materialization changed caller-provided Decision evidence")

        def semantic_payload(fact: object) -> str:
            parsed = EvidenceFact.model_validate(fact)
            return json.dumps(
                parsed.model_dump(
                    mode="json",
                    exclude={"evidence_id", "lineage", "durable_source_evidence_ids"},
                ),
                sort_keys=True,
                separators=(",", ":"),
            )

        expected = sorted(
            (
                source_id,
                semantic_payload(fact),
            )
            for fact in scoring_input.evidence
            for source_id in fact.durable_source_evidence_ids
        )
        actual = sorted(
            (
                fact.evidence_id,
                semantic_payload(fact),
            )
            for fact in materialization_input.evidence
            if fact.durable_source_evidence_ids
        )
        if expected != actual or any(
            fact.durable_source_evidence_ids != [fact.evidence_id]
            for fact in materialization_input.evidence
            if fact.durable_source_evidence_ids
        ):
            raise ValueError("Knowledge materialization evidence ancestry disagrees with scored support")

    def _required_evidence(self, *, tenant_id: str, evidence_id: uuid.UUID, role: str) -> EvidenceRecord:
        record = self._evidence.get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)
        if record is None:
            raise ValueError(f"decision episode {role} artifact is inaccessible")
        return record

    def _measurement_for_tenant(self, *, tenant_id: str, measurement_id: uuid.UUID) -> BusinessMeasurement:
        measurement = self._session.scalar(
            select(BusinessMeasurement).where(
                BusinessMeasurement.id == measurement_id,
                BusinessMeasurement.tenant_id == tenant_id,
            )
        )
        if measurement is None:
            raise ValueError("business impact measurement is inaccessible")
        return measurement

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

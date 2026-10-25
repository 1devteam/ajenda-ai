"""Business-understanding validation and append-only service boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.business_understanding import BusinessMeasurement, BusinessNeedRevision, BusinessObservation, utcnow
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.business_understanding_repository import (
    BusinessNeedRevisionConflict,
    BusinessUnderstandingRepository,
)
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.mission_composition.proposal_store import get_proposal
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.evaluation import GoalProgressStatus, evaluate_goal_progress
from backend.services.ontology.outcome import OutcomeEvaluation, OutcomeStatus
from backend.services.ontology.types import BusinessObjectRef

ObservationSourceKind = Literal[
    "business_profile",
    "tenant_internal_record",
    "evidence",
    "outcome_review",
    "knowledge_artifact",
    "external_provider",
    "customer_instruction",
]


class BusinessUnderstandingValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_kind: ObservationSourceKind
    reference: dict[str, Any]


def canonical_subject_keys(subjects: Sequence[BusinessObjectRef | dict[str, Any]]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (ref.object_type.value, ref.object_id)
        for ref in (
            item if isinstance(item, BusinessObjectRef) else BusinessObjectRef.model_validate(item) for item in subjects
        )
    )


class BusinessUnderstandingService:
    """Preserves attributed claims without mutating their source owners.

    This service has no TaskDispatcher, WorkerRuntimeService, provider, or
    charter dependency.  A need can be persisted, challenged, or resolved only
    as a declarative hypothesis; it cannot grant execution authority.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = BusinessUnderstandingRepository(session)

    @staticmethod
    def source_fingerprint(reference: dict[str, Any]) -> str:
        payload = json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    def record_observation(
        self,
        *,
        tenant_id: str,
        source: SourceReference,
        observation_summary: str,
        subject_references: list[dict[str, Any]],
        observed_at: datetime,
        confidence: float | None,
        limitations: list[dict[str, Any]],
        measurement_fingerprint: str | None = None,
        contradicts_observation_id: uuid.UUID | None = None,
        corrects_observation_id: uuid.UUID | None = None,
        producer: str,
    ) -> BusinessObservation:
        if not observation_summary.strip():
            raise BusinessUnderstandingValidationError("observation_summary must be non-empty")
        if not producer.strip():
            raise BusinessUnderstandingValidationError("producer must be non-empty")
        self._validate_source(tenant_id=tenant_id, source=source)
        self._validate_related_observation(
            tenant_id=tenant_id,
            observation_id=contradicts_observation_id,
            field_name="contradicts_observation_id",
        )
        self._validate_related_observation(
            tenant_id=tenant_id,
            observation_id=corrects_observation_id,
            field_name="corrects_observation_id",
        )
        return self._repository.add_observation(
            BusinessObservation(
                tenant_id=tenant_id,
                source_kind=source.source_kind,
                source_reference=dict(source.reference),
                source_fingerprint=self.source_fingerprint(source.reference),
                measurement_fingerprint=measurement_fingerprint,
                producer=producer.strip(),
                subject_references=list(subject_references),
                observation_summary=observation_summary.strip(),
                observed_at=observed_at,
                confidence=confidence,
                limitations=list(limitations),
                contradicts_observation_id=contradicts_observation_id,
                corrects_observation_id=corrects_observation_id,
            )
        )

    def ingest_measurement(
        self,
        *,
        tenant_id: str,
        goal: Goal,
        kpis: list[Kpi],
        subject_references: list[dict[str, Any]],
        source_kind: Literal["customer_attested", "source_verified"],
        source_reference: dict[str, Any],
        source_version: str,
        measurement_period_start: datetime | None,
        measurement_period_end: datetime | None,
        observed_at: datetime,
        successor_mission_id: uuid.UUID | None = None,
        limitations: list[dict[str, Any]],
        confidence: float | None,
        producer: str,
    ) -> tuple[BusinessMeasurement, BusinessNeedRevision | None]:
        """Persist an attributed measurement and feed existing recognition."""
        if not source_version.strip():
            raise BusinessUnderstandingValidationError("source_version must be non-empty")
        self._validate_measurement_timing(
            observed_at=observed_at,
            period_start=measurement_period_start,
            period_end=measurement_period_end,
        )
        if not kpis or any(kpi.goal_id != goal.goal_id for kpi in kpis):
            raise BusinessUnderstandingValidationError("all KPI values must belong to the supplied goal")
        expected_subjects = canonical_subject_keys(goal.subject_refs)
        supplied_subjects = canonical_subject_keys(subject_references)
        if expected_subjects != supplied_subjects:
            raise BusinessUnderstandingValidationError("measurement subjects must match goal subjects")
        metric = ", ".join(sorted(kpi.metric for kpi in kpis))
        intended_measurement_reference = self._resolve_intended_measurement_reference(
            tenant_id=tenant_id,
            successor_mission_id=successor_mission_id,
            subject_references=subject_references,
            objective_key=goal.objective_key or goal.goal_id,
            metric=metric,
            observed_at=observed_at,
            measurement_period_start=measurement_period_start,
            measurement_period_end=measurement_period_end,
        )
        payload = {
            "goal_id": goal.goal_id,
            "objective_key": goal.objective_key,
            "subjects": subject_references,
            "source": source_reference,
            "source_kind": source_kind,
            "source_version": source_version,
            "period_start": measurement_period_start.isoformat() if measurement_period_start else None,
            "period_end": measurement_period_end.isoformat() if measurement_period_end else None,
            "observed_at": observed_at.isoformat(),
            "kpis": [k.model_dump(mode="json") for k in sorted(kpis, key=lambda item: item.kpi_id)],
            "intended_measurement_contract_id": (
                intended_measurement_reference.get("contract_id") if intended_measurement_reference else None
            ),
        }
        if source_kind == "source_verified":
            raise BusinessUnderstandingValidationError(
                "source_verified measurements require an authorized internal adapter"
            )
        fingerprint = self.source_fingerprint(payload)
        measurement = self._repository.get_measurement_by_fingerprint_for_tenant(
            tenant_id=tenant_id, fingerprint=fingerprint
        )
        if measurement is None:
            candidate = BusinessMeasurement(
                tenant_id=tenant_id,
                subject_references=subject_references,
                objective_key=goal.objective_key or goal.goal_id,
                metric=metric,
                values=[k.model_dump(mode="json") for k in kpis],
                value=None,
                unit="",
                period_start=measurement_period_start,
                period_end=measurement_period_end,
                observed_at=observed_at,
                captured_at=utcnow(),
                source_kind=source_kind,
                source_reference=source_reference,
                source_version=source_version,
                source_content_fingerprint=fingerprint,
                intended_measurement_reference=intended_measurement_reference,
                limitations=[*limitations, {"code": f"provenance:{source_kind}"}],
                confidence=confidence,
            )
            try:
                measurement = self._repository.add_measurement(candidate)
            except IntegrityError:
                measurement = self._repository.get_measurement_by_fingerprint_for_tenant(
                    tenant_id=tenant_id, fingerprint=fingerprint
                )
                if measurement is None:
                    raise
        need = self.recognize_goal_gap(
            tenant_id=tenant_id,
            goal=goal,
            kpis=kpis,
            source=SourceReference(
                source_kind="customer_instruction",
                reference={"source_id": str(measurement.id)},
            ),
            observed_at=observed_at,
            producer=producer,
        )
        return measurement, need

    def _resolve_intended_measurement_reference(
        self,
        *,
        tenant_id: str,
        successor_mission_id: uuid.UUID | None,
        subject_references: list[dict[str, Any]],
        objective_key: str,
        metric: str,
        observed_at: datetime,
        measurement_period_start: datetime | None = None,
        measurement_period_end: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a frozen successor contract for an independently ingested measurement.

        The mission snapshot is only a reference contract.  This method does
        not infer an observation from mission completion, assess comparability,
        mutate a need, or create outcome/learning evidence.
        """

        if successor_mission_id is None:
            return None
        mission = MissionRepository(self._session).get_reference_for_tenant(
            mission_id=successor_mission_id,
            tenant_id=tenant_id,
        )
        if mission is None:
            raise BusinessUnderstandingValidationError("successor mission was not found for tenant")
        metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
        intake = metadata.get("mission_intake")
        context = intake.get("context") if isinstance(intake, dict) else None
        composition = context.get("composition") if isinstance(context, dict) else None
        if not isinstance(composition, dict):
            raise BusinessUnderstandingValidationError("successor mission has no immutable semantic snapshot")
        snapshot = composition.get("semantic_snapshot")
        if not isinstance(snapshot, dict):
            raise BusinessUnderstandingValidationError("successor mission has no immutable semantic snapshot")
        assessment = snapshot.get("business_need_assessment_reference")
        need = snapshot.get("business_need_reference")
        if not isinstance(assessment, dict) or not isinstance(need, dict):
            raise BusinessUnderstandingValidationError("successor mission has no business need measurement contract")
        advancement = assessment.get("response_advancement")
        if not isinstance(advancement, dict):
            raise BusinessUnderstandingValidationError(
                "successor mission has no selected response measurement contract"
            )
        intended = advancement.get("intended_measurement")
        baseline = advancement.get("baseline_measurement")
        if not isinstance(intended, dict) or not isinstance(baseline, dict):
            raise BusinessUnderstandingValidationError("successor measurement contract is invalid")
        expected_subjects = intended.get("subject_references")
        expected_objective = intended.get("objective_key")
        expected_metric = intended.get("metric")
        not_before_raw = intended.get("not_before")
        try:
            not_before = datetime.fromisoformat(str(not_before_raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise BusinessUnderstandingValidationError("successor measurement contract has invalid chronology") from exc
        if (
            not isinstance(expected_subjects, list)
            or not isinstance(expected_objective, str)
            or not expected_objective
            or not isinstance(expected_metric, str)
            or not expected_metric
            or (not_before.tzinfo is None)
            or (not_before.utcoffset() is None)
        ):
            raise BusinessUnderstandingValidationError("successor measurement contract is invalid")
        if canonical_subject_keys(expected_subjects) != canonical_subject_keys(subject_references):
            raise BusinessUnderstandingValidationError(
                "measurement subjects do not match successor measurement contract"
            )
        if expected_objective != objective_key:
            raise BusinessUnderstandingValidationError(
                "measurement objective does not match successor measurement contract"
            )
        if expected_metric != metric:
            raise BusinessUnderstandingValidationError(
                "measurement metric does not match successor measurement contract"
            )
        if (
            observed_at <= not_before
            or (measurement_period_start is not None and measurement_period_start <= not_before)
            or (measurement_period_end is not None and measurement_period_end <= not_before)
        ):
            raise BusinessUnderstandingValidationError(
                "measurement period must follow the successor measurement baseline"
            )
        required_strings = {
            "need_id": need.get("need_id"),
            "assessment_id": assessment.get("assessment_id"),
            "assessment_fingerprint": assessment.get("assessment_fingerprint"),
            "selected_candidate_response_key": advancement.get("selected_candidate_response_key"),
            "baseline_measurement_id": intended.get("baseline_measurement_id"),
            "baseline_source_content_fingerprint": baseline.get("source_content_fingerprint"),
            "semantic_snapshot_id": snapshot.get("snapshot_id"),
            "semantic_snapshot_sha256": snapshot.get("content_sha256"),
        }
        if any(not isinstance(value, str) or not value for value in required_strings.values()):
            raise BusinessUnderstandingValidationError("successor measurement contract is invalid")
        revision = need.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise BusinessUnderstandingValidationError("successor measurement contract has invalid need revision")
        if baseline.get("measurement_id") != intended.get("baseline_measurement_id"):
            raise BusinessUnderstandingValidationError("successor measurement contract baseline is contradictory")
        reference = {
            "schema_version": 1,
            "successor_mission_id": str(mission.id),
            "successor_proposal_id": composition.get("reviewed_proposal_id") or composition.get("proposal_id"),
            "semantic_snapshot_id": required_strings["semantic_snapshot_id"],
            "semantic_snapshot_sha256": required_strings["semantic_snapshot_sha256"],
            "strategy_lineage": {
                "need_id": required_strings["need_id"],
                "need_revision": revision,
                "assessment_id": required_strings["assessment_id"],
                "assessment_fingerprint": required_strings["assessment_fingerprint"],
                "selected_candidate_response_key": required_strings["selected_candidate_response_key"],
            },
            "measurement_contract": {
                "baseline_measurement_id": required_strings["baseline_measurement_id"],
                "baseline_source_content_fingerprint": required_strings["baseline_source_content_fingerprint"],
                "subject_references": list(expected_subjects),
                "objective_key": expected_objective,
                "metric": expected_metric,
                "not_before": not_before.isoformat(),
            },
            "grants_execution_authority": False,
        }
        reference["contract_id"] = self.source_fingerprint(reference)
        return reference

    def recognize_goal_gap(
        self,
        *,
        tenant_id: str,
        goal: Goal,
        kpis: list[Kpi],
        source: SourceReference,
        observed_at: datetime,
        producer: str,
    ) -> BusinessNeedRevision | None:
        """Recognize a durable need from an evaluated goal gap.

        This is deliberately bounded: it records an observation and a
        hypothesis only when the existing goal evaluator reports a gap. It
        never composes a mission or treats the KPI as a causal explanation.
        The caller owns the surrounding transaction, so both records commit
        atomically or neither is usable.
        """
        evaluation = evaluate_goal_progress(goal=goal, kpis=kpis, evaluated_at=observed_at)
        objective_key = goal.objective_key or goal.goal_id
        subject_references = [item.model_dump(mode="json") for item in goal.subject_refs]
        condition_key = hashlib.sha256(
            json.dumps(
                {"goal_id": goal.goal_id, "kpi_ids": sorted(k.kpi_id for k in kpis), "subjects": subject_references},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        source_fingerprint = self.source_fingerprint(source.reference)
        # Measurement identity is based on the source version and actual
        # business values, never on evaluation timestamps or invocation IDs.
        measurement_fingerprint = self._recognition_measurement_fingerprint(
            source_reference=source.reference,
            goal_id=goal.goal_id,
            kpis=[item.model_dump(mode="json") for item in kpis],
        )
        existing = self._repository.find_active_need_for_identity(
            tenant_id=tenant_id,
            objective_key=objective_key,
            subject_references=subject_references,
            condition_key=condition_key,
        )
        if (
            evaluation.status
            in {
                GoalProgressStatus.ON_TRACK,
                GoalProgressStatus.ACHIEVED,
                GoalProgressStatus.INSUFFICIENT_DATA,
            }
            and existing is None
        ):
            return None
        observation = self._repository.get_observation_by_source_fingerprint_for_tenant(
            tenant_id=tenant_id, source_fingerprint=source_fingerprint, measurement_fingerprint=measurement_fingerprint
        )
        if observation is None:
            try:
                observation = self.record_observation(
                    tenant_id=tenant_id,
                    source=source,
                    observation_summary=(
                        f"Goal condition requires attention: {goal.name}"
                        if evaluation.status in {GoalProgressStatus.AT_RISK, GoalProgressStatus.OFF_TRACK}
                        else f"Goal condition observed: {goal.name} ({evaluation.status.value})"
                    ),
                    subject_references=subject_references,
                    observed_at=observed_at,
                    confidence=None,
                    limitations=[{"code": "goal_gap_is_not_causal_explanation"}],
                    producer=producer,
                    measurement_fingerprint=measurement_fingerprint,
                )
            except IntegrityError:
                observation = self._repository.get_observation_by_source_fingerprint_for_tenant(
                    tenant_id=tenant_id,
                    source_fingerprint=source_fingerprint,
                    measurement_fingerprint=measurement_fingerprint,
                )
                if observation is None:
                    raise
        objective_reference = {"objective_key": objective_key, "condition_key": condition_key}
        existing = self._repository.find_active_need_for_identity(
            tenant_id=tenant_id,
            objective_key=objective_key,
            subject_references=subject_references,
            condition_key=condition_key,
        )
        if (
            evaluation.status
            in {
                GoalProgressStatus.ON_TRACK,
                GoalProgressStatus.ACHIEVED,
                GoalProgressStatus.INSUFFICIENT_DATA,
            }
            and existing is None
        ):
            return None
        if existing is not None and any(
            str(item.get("observation_id")) == str(observation.id)
            for item in existing.observation_references
            if isinstance(item, dict)
        ):
            return existing
        prior_observation_ids = [
            uuid.UUID(str(item["observation_id"]))
            for item in (existing.observation_references if existing is not None else [])
            if isinstance(item, dict) and item.get("observation_id")
        ]
        observation_ids = list(dict.fromkeys([*prior_observation_ids, observation.id]))
        stable_need_id = (
            existing.need_id
            if existing is not None
            else self._stable_need_id(
                tenant_id=tenant_id,
                objective_key=objective_key,
                condition_key=condition_key,
                subject_references=subject_references,
            )
        )
        try:
            return self.append_need_revision(
                tenant_id=tenant_id,
                need_id=stable_need_id,
                expected_revision=existing.revision if existing is not None else 0,
                origin="observed",
                status=(
                    "monitoring"
                    if evaluation.status in {GoalProgressStatus.ON_TRACK, GoalProgressStatus.ACHIEVED}
                    else existing.status
                )
                if existing is not None
                else "recognized",
                subject_references=subject_references,
                objective_reference=objective_reference,
                condition_summary=f"Goal '{goal.name}' is {evaluation.status.value}",
                uncertainty=(
                    existing.uncertainty if existing is not None else [{"code": "causal_explanation_unresolved"}]
                ),
                priority=existing.priority if existing is not None else None,
                confidence=existing.confidence if existing is not None else None,
                observation_ids=observation_ids,
                related_need_references=existing.related_need_references if existing is not None else [],
                candidate_responses=existing.candidate_responses if existing is not None else [],
                proposal_references=existing.proposal_references if existing is not None else [],
                mission_references=existing.mission_references if existing is not None else [],
                impact_assessment=existing.impact_assessment if existing is not None else None,
                resolution_observation_ids=[
                    uuid.UUID(str(item["observation_id"]))
                    for item in (existing.resolution_observation_references if existing is not None else [])
                    if isinstance(item, dict) and item.get("observation_id")
                ],
                producer=producer,
            )
        except BusinessNeedRevisionConflict:
            concurrent = self._repository.get_latest_need_for_tenant(tenant_id=tenant_id, need_id=stable_need_id)
            if concurrent is not None and any(
                str(item.get("observation_id")) == str(observation.id)
                for item in concurrent.observation_references
                if isinstance(item, dict)
            ):
                return concurrent
            raise

    def record_canonical_measurement_impact(
        self,
        *,
        tenant_id: str,
        need_id: str,
        expected_revision: int,
        baseline_measurement_id: uuid.UUID,
        observed_measurement_id: uuid.UUID,
        outcome_evidence_id: uuid.UUID,
        producer: str,
        mission_reference: dict[str, Any] | None = None,
    ) -> tuple[BusinessNeedRevision, OutcomeEvaluation]:
        """Attach a canonical outcome evaluation to comparable measurements.

        The outcome must already exist as canonical runtime evidence. This
        method validates that its KPI deltas and chronology correspond to the
        durable baseline and later measurement; it never manufactures outcome
        or causal evidence from mission completion.
        """
        current = self._repository.get_need_revision_for_tenant(
            tenant_id=tenant_id, need_id=need_id, revision=expected_revision
        )
        if current is None:
            raise BusinessUnderstandingValidationError("need revision was not found for tenant")
        baseline = self._repository.get_measurement_for_tenant(
            tenant_id=tenant_id, measurement_id=baseline_measurement_id
        )
        later = self._repository.get_measurement_for_tenant(tenant_id=tenant_id, measurement_id=observed_measurement_id)
        if baseline is None or later is None:
            raise BusinessUnderstandingValidationError("impact measurement was not found for tenant")
        self._validate_measurement_comparability(current=current, baseline=baseline, later=later)
        self._validate_successor_measurement_impact_lineage(current=current, baseline=baseline, later=later)
        evidence = EvidenceRepository(self._session).get_for_tenant(
            evidence_id=outcome_evidence_id, tenant_id=tenant_id
        )
        if evidence is None or evidence.provenance_metadata.get("action_name") != "analysis.evaluate_outcome":
            raise BusinessUnderstandingValidationError("canonical outcome evidence was not found for tenant")
        canonical_mission_reference = {"mission_id": str(evidence.mission_id)}
        if mission_reference is not None and mission_reference != canonical_mission_reference:
            raise BusinessUnderstandingValidationError("mission reference does not own canonical outcome evidence")
        try:
            outcome = OutcomeEvaluation.model_validate(evidence.structured_payload)
        except ValueError as exc:
            raise BusinessUnderstandingValidationError("canonical outcome evidence is invalid") from exc
        self._validate_outcome_matches_measurements(outcome=outcome, baseline=baseline, later=later)
        observation = self._repository.get_observation_by_source_fingerprint_for_tenant(
            tenant_id=tenant_id,
            source_fingerprint=self.source_fingerprint({"source_id": str(later.id)}),
            measurement_fingerprint=self._recognition_measurement_fingerprint(
                source_reference={"source_id": str(later.id)},
                goal_id=outcome.goal_id,
                kpis=later.values,
            ),
        )
        if observation is None:
            raise BusinessUnderstandingValidationError("impact observation was not found for measurement")
        expected_subjects = canonical_subject_keys(current.subject_references)
        observed_subjects = canonical_subject_keys(observation.subject_references)
        if expected_subjects != observed_subjects:
            raise BusinessUnderstandingValidationError("impact observation subject does not match outcome")
        prior_ids = {
            str(item.get("observation_id"))
            for item in current.observation_references
            if isinstance(item, dict) and item.get("observation_id")
        }
        prior = self._require_observations(
            tenant_id=tenant_id,
            observation_ids=[uuid.UUID(item) for item in prior_ids if item != str(observation.id)],
        )
        if prior and observation.observed_at <= max(item.observed_at for item in prior):
            raise BusinessUnderstandingValidationError("impact observation must follow the existing need evidence")
        status = "impact_monitored"
        impact = {
            "status": outcome.status.value,
            "evaluation_basis": outcome.model_dump(mode="json"),
            "causation": "unresolved",
            "baseline_measurement_id": str(baseline.id),
            "observed_measurement_id": str(later.id),
            "outcome_evidence_id": str(evidence.id),
        }
        if outcome.status == OutcomeStatus.INCONCLUSIVE:
            impact["status"] = "uncertain"
        revision = self.append_need_revision(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=expected_revision,
            origin="observed",
            status=status,
            subject_references=list(current.subject_references),
            objective_reference=dict(current.objective_reference or {}),
            condition_summary=current.condition_summary,
            uncertainty=[*current.uncertainty, {"code": "impact_causation_requires_attribution"}],
            priority=current.priority,
            confidence=current.confidence,
            observation_ids=[*([uuid.UUID(item) for item in prior_ids]), observation.id],
            related_need_references=list(current.related_need_references),
            candidate_responses=list(current.candidate_responses),
            proposal_references=list(current.proposal_references),
            mission_references=list(
                {
                    str(item["mission_id"]): item
                    for item in [*current.mission_references, canonical_mission_reference]
                    if isinstance(item, dict) and item.get("mission_id")
                }.values()
            ),
            impact_assessment=self._append_impact_history(current.impact_assessment, impact),
            resolution_observation_ids=[
                uuid.UUID(str(item["observation_id"]))
                for item in current.resolution_observation_references
                if isinstance(item, dict) and item.get("observation_id")
            ],
            producer=producer,
        )
        return revision, outcome

    def append_need_revision(
        self,
        *,
        tenant_id: str,
        need_id: str | None,
        expected_revision: int,
        origin: str,
        status: str,
        subject_references: list[dict[str, Any]],
        objective_reference: dict[str, Any] | None,
        condition_summary: str,
        uncertainty: list[dict[str, Any]],
        priority: dict[str, Any] | None,
        confidence: float | None,
        observation_ids: list[uuid.UUID],
        related_need_references: list[dict[str, Any]],
        candidate_responses: list[dict[str, Any]],
        proposal_references: list[dict[str, Any]],
        mission_references: list[dict[str, Any]],
        impact_assessment: dict[str, Any] | None,
        resolution_observation_ids: list[uuid.UUID],
        producer: str,
    ) -> BusinessNeedRevision:
        stable_need_id = need_id or str(uuid.uuid4())
        if expected_revision < 0:
            raise BusinessUnderstandingValidationError("expected_revision must be non-negative")
        if not condition_summary.strip():
            raise BusinessUnderstandingValidationError("condition_summary must be non-empty")
        if not producer.strip():
            raise BusinessUnderstandingValidationError("producer must be non-empty")
        self._validate_objective_reference(objective_reference)
        if not observation_ids:
            raise BusinessUnderstandingValidationError("need revisions require at least one supporting observation")
        observations = self._require_observations(tenant_id=tenant_id, observation_ids=observation_ids)
        resolution_observations = self._require_observations(
            tenant_id=tenant_id,
            observation_ids=resolution_observation_ids,
        )
        if status == "resolved":
            if not resolution_observations:
                raise BusinessUnderstandingValidationError(
                    "resolved need revisions require independently recorded resolution observations"
                )
            if not set(resolution_observation_ids).issubset(set(observation_ids)):
                raise BusinessUnderstandingValidationError("resolution observations must support the resolved revision")
            previous = (
                self._repository.get_need_revision_for_tenant(
                    tenant_id=tenant_id,
                    need_id=stable_need_id,
                    revision=expected_revision,
                )
                if expected_revision > 0
                else None
            )
            prior_observation_ids = {
                str(item.get("observation_id"))
                for item in (previous.observation_references if previous is not None else [])
                if isinstance(item, dict)
            }
            if all(str(item) in prior_observation_ids for item in resolution_observation_ids):
                raise BusinessUnderstandingValidationError(
                    "resolved need revisions require independently recorded impact observations"
                )
            if impact_assessment is None:
                raise BusinessUnderstandingValidationError("resolved need revisions require an impact_assessment")
            self._validate_resolution_consistency(
                previous=previous,
                subject_references=subject_references,
                resolution_observations=resolution_observations,
                impact_assessment=impact_assessment,
            )
        self._validate_related_needs(tenant_id=tenant_id, references=related_need_references)
        self._validate_proposal_references(tenant_id=tenant_id, references=proposal_references)
        self._validate_mission_references(tenant_id=tenant_id, references=mission_references)
        self._validate_candidate_responses(candidate_responses)
        return self._repository.append_need_revision(
            tenant_id=tenant_id,
            need_id=stable_need_id,
            expected_revision=expected_revision,
            values={
                "origin": origin,
                "status": status,
                "subject_references": list(subject_references),
                "objective_reference": dict(objective_reference) if objective_reference is not None else None,
                "condition_summary": condition_summary.strip(),
                "uncertainty": list(uncertainty),
                "priority": dict(priority) if priority is not None else None,
                "confidence": confidence,
                "observation_references": [self._observation_reference(item) for item in observations],
                "related_need_references": list(related_need_references),
                "candidate_responses": list(candidate_responses),
                "proposal_references": list(proposal_references),
                "mission_references": list(mission_references),
                "impact_assessment": self._bounded_impact_assessment(
                    condition_summary=condition_summary,
                    assessment=impact_assessment,
                ),
                "resolution_observation_references": [
                    self._observation_reference(item) for item in resolution_observations
                ],
                "producer": producer.strip(),
            },
        )

    @staticmethod
    def _observation_reference(observation: BusinessObservation) -> dict[str, str]:
        """Preserve source identity without claiming payload verification.

        The source owner validates tenant-scoped identity at write time.  A
        business-need revision does not re-fetch or independently verify the
        underlying source version/content, so its provenance must say so.
        """

        status = (
            "producer_attested_reference"
            if observation.source_kind in {"external_provider", "customer_instruction"}
            else "source_owner_identity_verified_content_version_unavailable"
        )
        return {
            "observation_id": str(observation.id),
            "source_identity_fingerprint": observation.source_fingerprint,
            "source_content_verification": status,
        }

    @staticmethod
    def _subject_keys(references: list[dict[str, Any]]) -> set[str]:
        return {
            json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            for reference in references
            if isinstance(reference, dict)
        }

    def _validate_resolution_consistency(
        self,
        *,
        previous: BusinessNeedRevision | None,
        subject_references: list[dict[str, Any]],
        resolution_observations: list[BusinessObservation],
        impact_assessment: dict[str, Any],
    ) -> None:
        allowed = {"status", "evaluation_basis", "condition_fingerprint"}
        if set(impact_assessment).difference(allowed) or not str(impact_assessment.get("status") or "").strip():
            raise BusinessUnderstandingValidationError("impact assessment is invalid")
        expected_subjects = self._subject_keys(subject_references)
        if expected_subjects and any(
            not expected_subjects.intersection(self._subject_keys(list(item.subject_references)))
            for item in resolution_observations
        ):
            raise BusinessUnderstandingValidationError("resolution observations must concern the need subject")
        if previous is None:
            return
        prior_ids = [
            uuid.UUID(str(item["observation_id"]))
            for item in previous.observation_references
            if isinstance(item, dict) and item.get("observation_id")
        ]
        prior = self._require_observations(tenant_id=previous.tenant_id, observation_ids=prior_ids)
        if prior and max(item.observed_at for item in resolution_observations) <= max(
            item.observed_at for item in prior
        ):
            raise BusinessUnderstandingValidationError(
                "resolution observations must follow the previously observed condition"
            )

    @staticmethod
    def _bounded_impact_assessment(
        *,
        condition_summary: str,
        assessment: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if assessment is None:
            return None
        expected = "sha256:" + hashlib.sha256(condition_summary.strip().encode("utf-8")).hexdigest()
        supplied = assessment.get("condition_fingerprint")
        if supplied is not None and supplied != expected:
            raise BusinessUnderstandingValidationError("impact assessment condition does not match the need")
        result = {
            key: value
            for key, value in assessment.items()
            if key
            in {
                "status",
                "evaluation_basis",
                "history",
                "causation",
                "baseline_measurement_id",
                "observed_measurement_id",
                "outcome_evidence_id",
            }
        }
        result["condition_fingerprint"] = expected
        return result

    @staticmethod
    def _stable_need_id(
        *,
        tenant_id: str,
        objective_key: str,
        condition_key: str,
        subject_references: list[dict[str, Any]],
    ) -> str:
        payload = json.dumps(
            {
                "tenant_id": tenant_id,
                "objective_key": objective_key,
                "condition_key": condition_key,
                "subjects": sorted(subject_references, key=lambda item: json.dumps(item, sort_keys=True)),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"need:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    @classmethod
    def _recognition_measurement_fingerprint(
        cls,
        *,
        source_reference: dict[str, Any],
        goal_id: str | None,
        kpis: list[dict[str, Any]],
    ) -> str:
        return cls.source_fingerprint(
            {
                "source": source_reference,
                "goal_id": goal_id,
                "kpis": [
                    {
                        "kpi_id": item.get("kpi_id"),
                        "metric": item.get("metric"),
                        "current_value": item.get("current_value"),
                        "target_value": item.get("target_value"),
                        "previous_value": item.get("previous_value"),
                        "unit": item.get("unit", ""),
                    }
                    for item in sorted(kpis, key=lambda value: str(value.get("kpi_id") or ""))
                ],
            }
        )

    @staticmethod
    def _validate_measurement_timing(
        *, observed_at: datetime, period_start: datetime | None, period_end: datetime | None
    ) -> None:
        for field_name, value in (
            ("observed_at", observed_at),
            ("measurement_period_start", period_start),
            ("measurement_period_end", period_end),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise BusinessUnderstandingValidationError(f"{field_name} must be timezone-aware")
        if period_start is not None and period_end is not None and period_end < period_start:
            raise BusinessUnderstandingValidationError("measurement period is invalid")
        if period_end is not None and observed_at < period_end:
            raise BusinessUnderstandingValidationError("observed_at cannot precede the measurement period end")

    @staticmethod
    def _append_impact_history(existing: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
        history = []
        if existing:
            history.extend(list(existing.get("history") or []))
            previous = {
                key: value for key, value in existing.items() if key not in {"history", "condition_fingerprint"}
            }
            if previous:
                history.append(previous)
        return {**current, "history": history}

    @staticmethod
    def _validate_measurement_comparability(
        *, current: BusinessNeedRevision, baseline: BusinessMeasurement, later: BusinessMeasurement
    ) -> None:
        if baseline.id == later.id:
            raise BusinessUnderstandingValidationError("impact requires a later distinct measurement")
        if canonical_subject_keys(baseline.subject_references) != canonical_subject_keys(later.subject_references):
            raise BusinessUnderstandingValidationError("impact measurements concern different subjects")
        if canonical_subject_keys(current.subject_references) != canonical_subject_keys(later.subject_references):
            raise BusinessUnderstandingValidationError("impact measurements do not match the need subject")
        if baseline.objective_key != later.objective_key:
            raise BusinessUnderstandingValidationError("impact measurements concern different objectives")
        baseline_metrics = {(item.get("kpi_id"), item.get("metric"), item.get("unit", "")) for item in baseline.values}
        later_metrics = {(item.get("kpi_id"), item.get("metric"), item.get("unit", "")) for item in later.values}
        if baseline_metrics != later_metrics:
            raise BusinessUnderstandingValidationError("impact measurements are not comparable")
        baseline_end = baseline.period_end or baseline.observed_at
        later_start = later.period_start or later.observed_at
        if later_start <= baseline_end or later.observed_at <= baseline.observed_at:
            raise BusinessUnderstandingValidationError("impact measurement chronology is invalid")

    @classmethod
    def _validate_successor_measurement_impact_lineage(
        cls, *, current: BusinessNeedRevision, baseline: BusinessMeasurement, later: BusinessMeasurement
    ) -> None:
        """Honor a later measurement's frozen successor contract at impact admission.

        A reference is provenance, NOT a comparison or outcome evaluation.
        This validates identity/chronology only; canonical outcome evidence
        and the existing impact owner are still independently required.
        Historical later measurements without a successor claim retain the
        existing measurement-comparability rules.
        """
        reference = later.intended_measurement_reference
        if reference is None:
            return
        required = {
            "schema_version",
            "successor_mission_id",
            "successor_proposal_id",
            "semantic_snapshot_id",
            "semantic_snapshot_sha256",
            "strategy_lineage",
            "measurement_contract",
            "grants_execution_authority",
            "contract_id",
        }
        if not isinstance(reference, dict) or set(reference) != required:
            raise BusinessUnderstandingValidationError("successor measurement lineage is invalid")
        strategy = reference.get("strategy_lineage")
        contract = reference.get("measurement_contract")
        if (
            type(reference["schema_version"]) is not int
            or reference["schema_version"] != 1
            or reference["grants_execution_authority"] is not False
            or not isinstance(strategy, dict)
            or set(strategy)
            != {
                "need_id",
                "need_revision",
                "assessment_id",
                "assessment_fingerprint",
                "selected_candidate_response_key",
            }
            or not isinstance(contract, dict)
            or set(contract)
            != {
                "baseline_measurement_id",
                "baseline_source_content_fingerprint",
                "subject_references",
                "objective_key",
                "metric",
                "not_before",
            }
            or any(
                not isinstance(reference.get(key), str) or not reference[key]
                for key in ("successor_mission_id", "semantic_snapshot_id", "semantic_snapshot_sha256")
            )
            or any(
                not isinstance(strategy.get(key), str) or not strategy[key]
                for key in ("need_id", "assessment_id", "assessment_fingerprint", "selected_candidate_response_key")
            )
            or type(strategy.get("need_revision")) is not int
            or strategy["need_revision"] < 1
            or not isinstance(contract.get("subject_references"), list)
            or any(
                not isinstance(contract.get(key), str) or not contract[key]
                for key in (
                    "baseline_measurement_id",
                    "baseline_source_content_fingerprint",
                    "objective_key",
                    "metric",
                    "not_before",
                )
            )
        ):
            raise BusinessUnderstandingValidationError("successor measurement lineage is invalid")
        try:
            expected_id = cls.source_fingerprint({k: v for k, v in reference.items() if k != "contract_id"})
            not_before = datetime.fromisoformat(contract["not_before"].replace("Z", "+00:00"))
            subjects = canonical_subject_keys(contract["subject_references"])
        except (TypeError, ValueError) as exc:
            raise BusinessUnderstandingValidationError("successor measurement lineage is malformed") from exc
        if reference["contract_id"] != expected_id or not_before.tzinfo is None or not_before.utcoffset() is None:
            raise BusinessUnderstandingValidationError("successor measurement contract identity is invalid")
        # A later active revision can retain the original strategy lineage, but
        # an explicitly superseded need is no longer an admissible target for
        # successor-linked impact evidence.  Lifecycle status remains owned by
        # the need revision; this check neither rewrites it nor evaluates an
        # outcome.
        if current.status == "superseded":
            raise BusinessUnderstandingValidationError("successor measurement lineage references a superseded need")
        if (
            strategy["need_id"] != current.need_id
            or strategy["need_revision"] > current.revision
            or contract["baseline_measurement_id"] != str(baseline.id)
            or contract["baseline_source_content_fingerprint"] != baseline.source_content_fingerprint
            or contract["objective_key"] != later.objective_key
            or contract["metric"] != later.metric
            or subjects != canonical_subject_keys(later.subject_references)
            or (later.period_start or later.observed_at) <= not_before
            or (later.period_end is not None and later.period_end <= not_before)
        ):
            raise BusinessUnderstandingValidationError(
                "impact measurements contradict the frozen successor measurement contract"
            )

    @staticmethod
    def _validate_outcome_matches_measurements(
        *, outcome: OutcomeEvaluation, baseline: BusinessMeasurement, later: BusinessMeasurement
    ) -> None:
        baseline_values = {
            str(item.get("kpi_id")): (item.get("current_value"), item.get("target_value"), item.get("metric"))
            for item in baseline.values
        }
        later_values = {
            str(item.get("kpi_id")): (item.get("current_value"), item.get("target_value"), item.get("metric"))
            for item in later.values
        }
        deltas = {item.kpi_id: (item.before, item.after, item.target, item.metric) for item in outcome.kpi_deltas}
        expected = {
            kpi_id: (before[0], later_values[kpi_id][0], later_values[kpi_id][1], before[2])
            for kpi_id, before in baseline_values.items()
            if kpi_id in later_values
        }
        if deltas != expected:
            raise BusinessUnderstandingValidationError("canonical outcome does not match durable measurements")
        resolved_observed_at = outcome.observation_timing.resolved_observed_at
        if resolved_observed_at is None or resolved_observed_at != later.observed_at:
            raise BusinessUnderstandingValidationError("canonical outcome chronology does not match measurement")

    def _validate_source(self, *, tenant_id: str, source: SourceReference) -> None:
        reference = source.reference
        if not reference:
            raise BusinessUnderstandingValidationError("source_reference is required")
        if source.source_kind == "business_profile":
            profile = BusinessProfileRepository(self._session).get_active_profile_for_tenant(tenant_id=tenant_id)
            if profile is None or str(profile.id) != str(reference.get("profile_id")):
                raise BusinessUnderstandingValidationError("business_profile source is not active for tenant")
        elif source.source_kind == "tenant_internal_record":
            record_type = str(reference.get("record_type") or "")
            record_id = str(reference.get("record_id") or "")
            if (
                not record_type
                or not record_id
                or TenantInternalRecordRepository(self._session).read_record(
                    tenant_id=tenant_id, record_type=record_type, record_id=record_id
                )
                is None
            ):
                raise BusinessUnderstandingValidationError("tenant internal record source was not found for tenant")
        elif source.source_kind == "evidence":
            try:
                evidence_id = uuid.UUID(str(reference.get("evidence_id")))
            except (TypeError, ValueError) as exc:
                raise BusinessUnderstandingValidationError("evidence source requires evidence_id") from exc
            if EvidenceRepository(self._session).get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id) is None:
                raise BusinessUnderstandingValidationError("evidence source was not found for tenant")
        elif source.source_kind == "outcome_review":
            try:
                review_id = uuid.UUID(str(reference.get("review_id")))
            except (TypeError, ValueError) as exc:
                raise BusinessUnderstandingValidationError("outcome review source requires review_id") from exc
            if OutcomeReviewRepository(self._session).get_for_tenant(review_id=review_id, tenant_id=tenant_id) is None:
                raise BusinessUnderstandingValidationError("outcome review source was not found for tenant")
        elif source.source_kind == "knowledge_artifact":
            knowledge_id = str(reference.get("knowledge_id") or "")
            if (
                not knowledge_id
                or KnowledgeRepository(self._session).get_artifact_for_tenant(
                    tenant_id=tenant_id, knowledge_id=knowledge_id
                )
                is None
            ):
                raise BusinessUnderstandingValidationError("knowledge source was not found for tenant")
        elif source.source_kind in {"external_provider", "customer_instruction"}:
            if not str(reference.get("source_id") or "").strip():
                raise BusinessUnderstandingValidationError(
                    "external and instruction sources require an opaque source_id"
                )
        else:  # defensive for direct service callers
            raise BusinessUnderstandingValidationError("unsupported observation source kind")

    def _validate_related_observation(
        self, *, tenant_id: str, observation_id: uuid.UUID | None, field_name: str
    ) -> None:
        if (
            observation_id is not None
            and self._repository.get_observation_for_tenant(observation_id=observation_id, tenant_id=tenant_id) is None
        ):
            raise BusinessUnderstandingValidationError(f"{field_name} was not found for tenant")

    def _require_observations(self, *, tenant_id: str, observation_ids: list[uuid.UUID]) -> list[BusinessObservation]:
        if not observation_ids:
            return []
        found: list[BusinessObservation] = []
        for observation_id in dict.fromkeys(observation_ids):
            observation = self._repository.get_observation_for_tenant(
                observation_id=observation_id,
                tenant_id=tenant_id,
            )
            if observation is None:
                raise BusinessUnderstandingValidationError("observation reference was not found for tenant")
            found.append(observation)
        return found

    def _validate_related_needs(self, *, tenant_id: str, references: list[dict[str, Any]]) -> None:
        for reference in references:
            need_id = str(reference.get("need_id") or "")
            revision = reference.get("revision")
            if (
                not need_id
                or not isinstance(revision, int)
                or self._repository.get_need_revision_for_tenant(
                    tenant_id=tenant_id, need_id=need_id, revision=revision
                )
                is None
            ):
                raise BusinessUnderstandingValidationError("related need reference was not found for tenant")

    @staticmethod
    def _validate_objective_reference(reference: dict[str, Any] | None) -> None:
        """Objectives are descriptive until the ontology gains a durable owner.

        A caller cannot smuggle an unverified foreign-record identifier into the
        need lineage.  Supporting facts belong in tenant-validated observations.
        """

        if reference is None:
            return
        allowed_fields = {"objective_key", "objective_summary", "condition_key"}
        if set(reference).difference(allowed_fields) or not str(reference.get("objective_key") or "").strip():
            raise BusinessUnderstandingValidationError("objective reference is invalid")
        summary = reference.get("objective_summary")
        if summary is not None and not isinstance(summary, str):
            raise BusinessUnderstandingValidationError("objective reference is invalid")
        condition_key = reference.get("condition_key")
        if condition_key is not None and (not isinstance(condition_key, str) or not condition_key.strip()):
            raise BusinessUnderstandingValidationError("objective reference is invalid")

    def _validate_proposal_references(self, *, tenant_id: str, references: list[dict[str, Any]]) -> None:
        for reference in references:
            proposal_id = str(reference.get("proposal_id") or "").strip()
            if not proposal_id or set(reference).difference({"proposal_id"}):
                raise BusinessUnderstandingValidationError("proposal reference is invalid")
            if get_proposal(tenant_id=tenant_id, proposal_id=proposal_id, db=self._session) is None:
                raise BusinessUnderstandingValidationError("proposal reference was not found for tenant")

    def _validate_mission_references(self, *, tenant_id: str, references: list[dict[str, Any]]) -> None:
        repository = MissionRepository(self._session)
        for reference in references:
            try:
                mission_id = uuid.UUID(str(reference.get("mission_id")))
            except (TypeError, ValueError) as exc:
                raise BusinessUnderstandingValidationError("mission reference is invalid") from exc
            if set(reference).difference({"mission_id"}):
                raise BusinessUnderstandingValidationError("mission reference is invalid")
            if repository.get_reference_for_tenant(mission_id=mission_id, tenant_id=tenant_id) is None:
                raise BusinessUnderstandingValidationError("mission reference was not found for tenant")

    @staticmethod
    def _validate_candidate_responses(responses: list[dict[str, Any]]) -> None:
        for response in responses:
            if not str(response.get("response_key") or "").strip():
                raise BusinessUnderstandingValidationError("candidate response requires response_key")
            if response.get("grants_execution_authority") is True:
                raise BusinessUnderstandingValidationError("candidate responses cannot grant execution authority")

"""Business-understanding validation and append-only service boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.domain.business_understanding import BusinessNeedRevision, BusinessObservation
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.mission_composition.proposal_store import get_proposal
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.evaluation import GoalProgressStatus, evaluate_goal_progress
from backend.services.ontology.outcome import ObservedOutcome, OutcomeExpectation, OutcomeStatus, evaluate_outcome

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
        if evaluation.status in {
            GoalProgressStatus.ON_TRACK,
            GoalProgressStatus.ACHIEVED,
            GoalProgressStatus.INSUFFICIENT_DATA,
        }:
            return None
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
        measurement_fingerprint = self.source_fingerprint(
            {
                "source": source.reference,
                "goal_id": goal.goal_id,
                "kpis": [
                    {
                        "kpi_id": k.kpi_id,
                        "metric": k.metric,
                        "current_value": k.current_value,
                        "target_value": k.target_value,
                        "previous_value": k.previous_value,
                        "unit": k.unit,
                    }
                    for k in sorted(kpis, key=lambda item: item.kpi_id)
                ],
            }
        )
        observation = self._repository.get_observation_by_source_fingerprint_for_tenant(
            tenant_id=tenant_id, source_fingerprint=source_fingerprint, measurement_fingerprint=measurement_fingerprint
        ) or self.record_observation(
            tenant_id=tenant_id,
            source=source,
            observation_summary=f"Goal condition requires attention: {goal.name}",
            subject_references=subject_references,
            observed_at=observed_at,
            confidence=None,
            limitations=[{"code": "goal_gap_is_not_causal_explanation"}],
            producer=producer,
            measurement_fingerprint=measurement_fingerprint,
        )
        objective_reference = {"objective_key": objective_key, "condition_key": condition_key}
        existing = self._repository.find_active_need_for_identity(
            tenant_id=tenant_id,
            objective_key=objective_key,
            subject_references=subject_references,
            condition_key=condition_key,
        )
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
        return self.append_need_revision(
            tenant_id=tenant_id,
            need_id=existing.need_id if existing is not None else None,
            expected_revision=existing.revision if existing is not None else 0,
            origin="observed",
            status=existing.status if existing is not None else "recognized",
            subject_references=subject_references,
            objective_reference=objective_reference,
            condition_summary=f"Goal '{goal.name}' is {evaluation.status.value}",
            uncertainty=(existing.uncertainty if existing is not None else [{"code": "causal_explanation_unresolved"}]),
            priority=existing.priority if existing is not None else None,
            confidence=existing.confidence if existing is not None else None,
            observation_ids=observation_ids,
            related_need_references=[],
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

    def record_independent_impact(
        self,
        *,
        tenant_id: str,
        need_id: str,
        expected_revision: int,
        expectation: OutcomeExpectation,
        observed: ObservedOutcome,
        observation_id: uuid.UUID,
        producer: str,
        mission_reference: dict[str, Any] | None = None,
    ) -> tuple[BusinessNeedRevision, Any]:
        """Evaluate later business evidence and append a need revision.

        Mission completion is merely lineage; only the independent observed
        outcome determines the impact status. ``evaluate_outcome`` retains
        attribution uncertainty and never upgrades temporal association to
        causation.
        """
        outcome = evaluate_outcome(expectation=expectation, observed=observed)
        current = self._repository.get_need_revision_for_tenant(
            tenant_id=tenant_id, need_id=need_id, revision=expected_revision
        )
        if current is None:
            raise BusinessUnderstandingValidationError("need revision was not found for tenant")
        observation = self._repository.get_observation_for_tenant(observation_id=observation_id, tenant_id=tenant_id)
        if observation is None:
            raise BusinessUnderstandingValidationError("impact observation was not found for tenant")
        expected_subjects = {json.dumps(item, sort_keys=True) for item in expectation.subject_refs}
        observed_subjects = {json.dumps(item, sort_keys=True) for item in observation.subject_references}
        if expected_subjects and not expected_subjects.intersection(observed_subjects):
            raise BusinessUnderstandingValidationError("impact observation subject does not match outcome")
        prior_ids = {
            str(item.get("observation_id"))
            for item in current.observation_references
            if isinstance(item, dict) and item.get("observation_id")
        }
        prior = self._require_observations(tenant_id=tenant_id, observation_ids=[uuid.UUID(item) for item in prior_ids])
        if prior and observation.observed_at <= max(item.observed_at for item in prior):
            raise BusinessUnderstandingValidationError("impact observation must follow the existing need evidence")
        status = "impact_monitored"
        impact = {
            "status": outcome.status.value,
            "evaluation_basis": outcome.model_dump(mode="json"),
            "causation": "unresolved",
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
            condition_summary=f"Independent impact observed for {expectation.goal.name}",
            uncertainty=[*current.uncertainty, {"code": "impact_causation_requires_attribution"}],
            priority=None,
            confidence=None,
            observation_ids=[*([uuid.UUID(item) for item in prior_ids]), observation_id],
            related_need_references=list(current.related_need_references),
            candidate_responses=list(current.candidate_responses),
            proposal_references=list(current.proposal_references),
            mission_references=[*current.mission_references, *([mission_reference] if mission_reference else [])],
            impact_assessment=impact,
            resolution_observation_ids=[],
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
        result = {key: value for key, value in assessment.items() if key in {"status", "evaluation_basis"}}
        result["condition_fingerprint"] = expected
        return result

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

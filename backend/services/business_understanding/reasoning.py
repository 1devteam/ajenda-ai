"""Deterministic, non-authoritative assessment of a business need.

This coordinates existing ontology evaluation with business-understanding
lineage. It does not route jobs, resolve credentials, admit work, or invoke a
provider. Catalog coverage is reported only as a planning limitation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from backend.domain.business_understanding import BusinessNeedAssessment, BusinessNeedRevision
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.services.business_understanding.service import canonical_subject_keys
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionSupportResult,
    KnowledgeInfluenceDirection,
)
from backend.services.mission_composition.job_catalog import list_business_jobs
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.evaluation import EvaluationResult, GoalProgressStatus, evaluate_goal_progress


class NeedCauseHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cause_key: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2000)
    supporting_observation_ids: tuple[uuid.UUID, ...] = ()
    contradicting_observation_ids: tuple[uuid.UUID, ...] = ()


class NeedCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    response_key: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2000)
    requested_outcomes: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    supporting_observation_ids: tuple[uuid.UUID, ...] = ()
    contradicting_observation_ids: tuple[uuid.UUID, ...] = ()


class NeedAssessmentRequest(BaseModel):
    """Structured reasoning inputs; source owners remain outside this model."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal | None = None
    kpis: tuple[Kpi, ...] = ()
    hypotheses: tuple[NeedCauseHypothesis, ...] = ()
    candidate_responses: tuple[NeedCandidateResponse, ...] = ()
    # This is a previously produced, bounded decision-support result.  The
    # assessment does not retrieve, qualify, or promote knowledge itself.
    knowledge_support: KnowledgeDecisionSupportResult | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("evaluated_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _goal_and_kpis_agree(self) -> NeedAssessmentRequest:
        if self.goal is None and self.kpis:
            raise ValueError("kpis require a goal")
        if self.goal is not None and any(kpi.goal_id != self.goal.goal_id for kpi in self.kpis):
            raise ValueError("all kpis must belong to the supplied goal")
        return self


class AssessedCause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cause_key: str
    summary: str
    status: Literal["supported", "contradicted", "conflicted", "unresolved"]
    supporting_observation_ids: tuple[str, ...] = ()
    contradicting_observation_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class AssessedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    response_key: str
    summary: str
    requested_outcomes: tuple[str, ...] = ()
    catalog_job_keys: tuple[str, ...] = ()
    unsupported_outcomes: tuple[str, ...] = ()
    evidence_status: Literal["supported", "contradicted", "conflicted", "unresolved"]
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    capability_status: Literal["catalog_supported", "partially_mapped", "unmapped"]
    knowledge_support_status: Literal["not_provided", "supports", "opposes", "conditional", "unresolved"]
    knowledge_influence_ids: tuple[str, ...] = ()
    grants_execution_authority: Literal[False] = False


class BusinessNeedAssessmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    assessment_id: uuid.UUID
    tenant_id: str
    need_id: str
    need_revision: int
    condition_summary: str
    goal_evaluation: EvaluationResult | None = None
    supporting_observation_ids: tuple[str, ...]
    contradictory_observation_ids: tuple[str, ...]
    causes: tuple[AssessedCause, ...]
    candidate_responses: tuple[AssessedResponse, ...]
    information_gaps: tuple[str, ...]
    recommended_next_step: Literal[
        "investigate_further", "seek_clarification", "consider_response", "insufficient_evidence"
    ]
    improvement_evidence_requirements: tuple[str, ...]
    knowledge_support_id: str | None = None
    knowledge_epistemic_limits: tuple[str, ...] = ()
    evaluated_at: datetime
    producer: str
    assessment_fingerprint: str
    grants_execution_authority: Literal[False] = False


def _reference_ids(need: BusinessNeedRevision) -> set[uuid.UUID]:
    values: set[uuid.UUID] = set()
    for item in need.observation_references:
        try:
            values.add(uuid.UUID(str(item.get("observation_id"))))
        except (TypeError, ValueError, AttributeError):
            continue
    return values


EvidenceStatus = Literal["supported", "contradicted", "conflicted", "unresolved"]


def _evidence_status(*, supporting: tuple[uuid.UUID, ...], contradicting: tuple[uuid.UUID, ...]) -> EvidenceStatus:
    if supporting and contradicting:
        return "conflicted"
    if supporting:
        return "supported"
    if contradicting:
        return "contradicted"
    return "unresolved"


def _knowledge_status(
    directions: set[KnowledgeInfluenceDirection],
) -> Literal["not_provided", "supports", "opposes", "conditional", "unresolved"]:
    if not directions:
        return "not_provided"
    # Conflicting or unresolved knowledge must never be collapsed into a
    # recommendation.  In particular, supports + opposes is evidence of a
    # conflict, not a reason to prefer the positive influence.
    if KnowledgeInfluenceDirection.SUPPORTS in directions and KnowledgeInfluenceDirection.OPPOSES in directions:
        return "unresolved"
    if KnowledgeInfluenceDirection.UNRESOLVED in directions or KnowledgeInfluenceDirection.NEUTRAL in directions:
        return "unresolved"
    if KnowledgeInfluenceDirection.SUPPORTS in directions:
        return "supports"
    if KnowledgeInfluenceDirection.OPPOSES in directions:
        return "opposes"
    if KnowledgeInfluenceDirection.CONDITIONAL in directions:
        return "conditional"
    return "unresolved"


class BusinessNeedReasoningService:
    """Produces a durable assessment using existing ontology and catalog owners."""

    def __init__(self, repository: BusinessUnderstandingRepository) -> None:
        self._repository = repository

    def assess(
        self,
        *,
        tenant_id: str,
        need_id: str,
        revision: int,
        request: NeedAssessmentRequest,
        producer: str,
    ) -> BusinessNeedAssessmentResult:
        if not producer.strip():
            raise ValueError("producer must be non-empty")
        need = self._repository.get_need_revision_for_tenant(tenant_id=tenant_id, need_id=need_id, revision=revision)
        if need is None:
            raise ValueError("business need revision was not found for tenant")
        allowed_observation_ids = _reference_ids(need)
        for item in request.hypotheses:
            references = set(item.supporting_observation_ids) | set(item.contradicting_observation_ids)
            if not references.issubset(allowed_observation_ids):
                raise ValueError("assessment evidence must be attributed to the assessed need revision")
        for response in request.candidate_responses:
            references = set(response.supporting_observation_ids) | set(response.contradicting_observation_ids)
            if not references.issubset(allowed_observation_ids):
                raise ValueError("assessment evidence must be attributed to the assessed need revision")

        if request.goal is not None:
            originating_subjects = canonical_subject_keys(need.subject_references)
            goal_subjects = canonical_subject_keys(request.goal.subject_refs)
            if originating_subjects != goal_subjects:
                raise ValueError("assessment goal subjects must match the originating business need")
            originating_objective = need.objective_reference
            if not isinstance(originating_objective, dict):
                raise ValueError("originating business need has an invalid objective reference")
            expected_objective = originating_objective.get("objective_key")
            actual_objective = request.goal.objective_key or request.goal.goal_id
            if not isinstance(expected_objective, str) or expected_objective != actual_objective:
                raise ValueError("assessment goal objective must match the originating business need")

        goal_evaluation = (
            evaluate_goal_progress(goal=request.goal, kpis=list(request.kpis), evaluated_at=request.evaluated_at)
            if request.goal is not None
            else None
        )
        causes = tuple(
            AssessedCause(
                cause_key=item.cause_key,
                summary=item.summary,
                status=_evidence_status(
                    supporting=item.supporting_observation_ids,
                    contradicting=item.contradicting_observation_ids,
                ),
                supporting_observation_ids=tuple(str(value) for value in item.supporting_observation_ids),
                contradicting_observation_ids=tuple(str(value) for value in item.contradicting_observation_ids),
                confidence=(
                    0.75 if item.supporting_observation_ids and not item.contradicting_observation_ids else 0.35
                ),
            )
            for item in request.hypotheses
        )
        contradictory_observation_ids = {
            observation_id
            for hypothesis in request.hypotheses
            for observation_id in hypothesis.contradicting_observation_ids
        }
        contradictory_observation_ids.update(
            observation_id
            for response in request.candidate_responses
            for observation_id in response.contradicting_observation_ids
        )
        supporting_observation_ids = {
            observation_id
            for hypothesis in request.hypotheses
            for observation_id in hypothesis.supporting_observation_ids
        }
        supporting_observation_ids.update(
            observation_id
            for response in request.candidate_responses
            for observation_id in response.supporting_observation_ids
        )
        outcome_jobs = {
            outcome: tuple(job.job_key for job in list_business_jobs() if outcome in job.supported_outcomes)
            for response in request.candidate_responses
            for outcome in response.requested_outcomes
        }
        knowledge_by_response: dict[str, tuple[str, ...]] = {}
        knowledge_directions_by_response: dict[str, set[KnowledgeInfluenceDirection]] = {}
        if request.knowledge_support is not None:
            response_keys = {item.response_key for item in request.candidate_responses}
            for influence in request.knowledge_support.influences:
                if influence.option_id not in response_keys:
                    continue
                knowledge_by_response[influence.option_id] = tuple(
                    sorted({*knowledge_by_response.get(influence.option_id, ()), influence.influence_id})
                )
                knowledge_directions_by_response.setdefault(influence.option_id, set()).add(influence.direction)
        responses: list[AssessedResponse] = []
        for response in request.candidate_responses:
            catalog_jobs = tuple(
                dict.fromkeys(key for outcome in response.requested_outcomes for key in outcome_jobs.get(outcome, ()))
            )
            unsupported = tuple(outcome for outcome in response.requested_outcomes if not outcome_jobs.get(outcome))
            if catalog_jobs and not unsupported:
                capability_status: Literal["catalog_supported", "partially_mapped", "unmapped"] = "catalog_supported"
            elif catalog_jobs:
                capability_status = "partially_mapped"
            else:
                capability_status = "unmapped"
            responses.append(
                AssessedResponse(
                    response_key=response.response_key,
                    summary=response.summary,
                    requested_outcomes=response.requested_outcomes,
                    catalog_job_keys=catalog_jobs,
                    unsupported_outcomes=unsupported,
                    evidence_status=_evidence_status(
                        supporting=response.supporting_observation_ids,
                        contradicting=response.contradicting_observation_ids,
                    ),
                    dependencies=response.dependencies,
                    assumptions=response.assumptions,
                    tradeoffs=response.tradeoffs,
                    capability_status=capability_status,
                    knowledge_support_status=_knowledge_status(
                        knowledge_directions_by_response.get(response.response_key, set())
                    ),
                    knowledge_influence_ids=knowledge_by_response.get(response.response_key, ()),
                )
            )
        gaps: list[str] = []
        if goal_evaluation is None:
            gaps.append("objective_or_kpi_context_unavailable")
        elif goal_evaluation.status == GoalProgressStatus.INSUFFICIENT_DATA:
            gaps.extend(gap.code for gap in goal_evaluation.progress_gaps)
        if any(cause.status == "unresolved" for cause in causes):
            gaps.append("causal_explanations_unresolved")
        if not responses:
            gaps.append("candidate_responses_unassessed")
        if goal_evaluation is None or goal_evaluation.status == GoalProgressStatus.INSUFFICIENT_DATA:
            next_step: Literal[
                "investigate_further", "seek_clarification", "consider_response", "insufficient_evidence"
            ] = "insufficient_evidence"
        elif any(
            response.evidence_status == "supported"
            and response.knowledge_support_status not in {"opposes", "unresolved"}
            for response in responses
        ) or any(
            response.knowledge_support_status == "supports" and response.evidence_status == "supported"
            for response in responses
        ):
            next_step = "consider_response"
        elif causes:
            next_step = "investigate_further"
        else:
            next_step = "seek_clarification"

        payload = {
            "schema_version": 1,
            "tenant_id": tenant_id,
            "need_id": need_id,
            "need_revision": revision,
            "condition_summary": need.condition_summary,
            "goal_evaluation": goal_evaluation.model_dump(mode="json") if goal_evaluation else None,
            "supporting_observation_ids": sorted(str(item) for item in supporting_observation_ids),
            "contradictory_observation_ids": sorted(str(item) for item in contradictory_observation_ids),
            "causes": [item.model_dump(mode="json") for item in causes],
            "candidate_responses": [item.model_dump(mode="json") for item in responses],
            "information_gaps": sorted(set(gaps)),
            "recommended_next_step": next_step,
            "improvement_evidence_requirements": (
                "independent follow-up business observation",
                "objective or KPI measurement after the response",
            ),
            "knowledge_support_id": request.knowledge_support.support_id if request.knowledge_support else None,
            "knowledge_epistemic_limits": (
                request.knowledge_support.epistemic_limits if request.knowledge_support is not None else ()
            ),
            "evaluated_at": request.evaluated_at.isoformat(),
            "producer": producer.strip(),
            "grants_execution_authority": False,
        }
        fingerprint = (
            "sha256:"
            + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        )
        existing = self._repository.get_assessment_by_fingerprint_for_tenant(
            tenant_id=tenant_id,
            need_id=need_id,
            need_revision=revision,
            fingerprint=fingerprint,
        )
        if existing is not None:
            assessment = existing
        else:
            try:
                assessment = self._repository.add_assessment(
                    BusinessNeedAssessment(
                        tenant_id=tenant_id,
                        need_id=need_id,
                        need_revision=revision,
                        need_revision_id=need.id,
                        assessment_json=payload,
                        assessment_fingerprint=fingerprint,
                        producer=producer.strip(),
                    )
                )
            except IntegrityError:
                recovered = self._repository.get_assessment_by_fingerprint_for_tenant(
                    tenant_id=tenant_id,
                    need_id=need_id,
                    need_revision=revision,
                    fingerprint=fingerprint,
                )
                if recovered is None:
                    raise
                assessment = recovered
        return BusinessNeedAssessmentResult.model_validate(
            {**payload, "assessment_id": assessment.id, "assessment_fingerprint": fingerprint}
        )

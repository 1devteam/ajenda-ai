"""Evaluation + Outcome + Decision Feedback Intelligence — analysis abilities.

``analysis.evaluate_goal_progress``: deterministic Goal/KPI/State assessment.
``analysis.evaluate_outcome``: expected vs observed outcome delta.
``analysis.assess_attribution_integrity``: earned, non-causal attribution.
``analysis.materialize_decision_learning_signal``: durable decision episode authority.
``analysis.compare_experiences``: semantic partition/comparison only.
``analysis.assess_experience_recurrence``: multi-candidate recurrence eligibility.
``analysis.qualify_pattern_knowledge``: deterministic bounded knowledge qualification.

Does not persist reviews, recommend next actions, execute work, or modify
weighted_criterion_evidence_v1. Observation ≠ pattern ≠ knowledge ≠ policy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.decision_episode_materialization import (
    DecisionEpisodeMaterializationRequest,
    DecisionEpisodeMaterializationService,
)
from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
)
from backend.services.ontology.evaluation import evaluate_goal_progress
from backend.services.ontology.experience_intelligence import (
    ExperienceEpisodeInput,
    ExperiencePatternCandidate,
    evaluate_experience_set,
)
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.observation_attribution import (
    AttributionAssessmentEvidence,
    AttributionEvidenceInput,
    evaluate_attribution_evidence,
    resolve_observation_timing,
)
from backend.services.ontology.outcome import (
    AttributionAssessment,
    ObservedOutcome,
    OutcomeExpectation,
    evaluate_outcome,
)
from backend.services.ontology.types import BusinessObjectRef
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


class EvaluateGoalProgressInput(BaseModel):
    """Input for analysis.evaluate_goal_progress."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    kpis: list[Kpi] = Field(default_factory=list)
    current_state: BusinessStateSnapshot | None = None
    previous_state: BusinessStateSnapshot | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_codes: list[str] = Field(
        default_factory=list,
        description="Caller-declared evidence/information gaps (opaque codes)",
    )


class EvaluateOutcomeInput(BaseModel):
    """Input for analysis.evaluate_outcome."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    baseline_kpis: list[Kpi] = Field(default_factory=list)
    baseline_snapshot: BusinessStateSnapshot | None = None
    success_criteria_codes: list[str] = Field(default_factory=list)
    observed_kpis: list[Kpi] = Field(default_factory=list)
    observed_snapshot: BusinessStateSnapshot | None = None
    observed_at: datetime | None = Field(
        default=None,
        description="Legacy caller assertion; prefer asserted_observed_at",
    )
    source_observed_at: datetime | None = None
    captured_at: datetime | None = None
    asserted_observed_at: datetime | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_codes: list[str] = Field(default_factory=list)
    attribution: AttributionAssessment = AttributionAssessment.NOT_ASSESSED
    attribution_evidence: AttributionEvidenceInput | None = None


class AssessAttributionIntegrityInput(BaseModel):
    """Input for analysis.assess_attribution_integrity."""

    model_config = ConfigDict(extra="forbid")

    source_observed_at: datetime | None = None
    captured_at: datetime | None = None
    asserted_observed_at: datetime | None = None
    evidence: AttributionEvidenceInput


class CompareExperiencesInput(BaseModel):
    """Input for analysis.compare_experiences."""

    model_config = ConfigDict(extra="forbid")

    episodes: list[ExperienceEpisodeInput] = Field(default_factory=list)


class AssessExperienceRecurrenceInput(BaseModel):
    """Input for analysis.assess_experience_recurrence."""

    model_config = ConfigDict(extra="forbid")

    episodes: list[ExperienceEpisodeInput] = Field(default_factory=list)


class QualifyPatternKnowledgeInput(BaseModel):
    """Input for analysis.qualify_pattern_knowledge."""

    model_config = ConfigDict(extra="forbid")
    candidate: ExperiencePatternCandidate


def analysis_materialize_decision_learning_signal(
    invocation: ToolInvocation, context: ActionRuntimeContext
) -> ActionResult:
    """Adapt the queue-authoritative tool path to durable episode authority."""

    if context.session_factory is None:
        raise ValueError("decision episode materialization requires durable repository access")
    payload = DecisionEpisodeMaterializationRequest.model_validate(invocation.input)
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        materialized = DecisionEpisodeMaterializationService(
            session=session,
            evidence=EvidenceRepository(session),
            tasks=ExecutionTaskRepository(session),
        ).materialize(tenant_id=context.tenant_id, request=payload)
    finally:
        session.close()
    if context.mission_id is None or str(context.mission_id) != materialized.episode_reference.mission_id:
        raise ValueError("materialization task mission must match the durable decision episode mission")
    signal = materialized.feedback.learning_signal
    records_inspected = materialized.inspection_trace.resource_references()
    output = signal.model_dump(mode="json")
    summary = f"Materialized authoritative learning signal {signal.signal_id} for decision {signal.decision_id}."
    return ActionResult(
        action="analysis.materialize_decision_learning_signal",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[
            EvidenceItem(
                evidence_type="action_result_evidence",
                evidence_source="decision_episode_materialization",
                action_name="analysis.materialize_decision_learning_signal",
                tool_provider="ajenda_analysis",
                tenant_id=context.tenant_id,
                task_id=str(context.task_id),
                mission_id=str(context.mission_id) if context.mission_id is not None else None,
                summary=summary,
                structured_payload=output,
                records_inspected=records_inspected,
                confidence=signal.effectiveness.confidence,
                provenance={
                    "runtime_path": "TaskDispatcher -> tool.invoke -> DecisionEpisodeMaterializationService",
                    "cluster": "decision_feedback_intelligence",
                    "evidence_role": "decision_learning_signal",
                    "episode_id": materialized.episode_reference.episode_id,
                },
                side_effect_class=SideEffectClass.INTERNAL_READ,
            )
        ],
        records_inspected=records_inspected,
        summary=summary,
        confidence=signal.effectiveness.confidence,
    )


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    confidence: float | None,
    cluster: str,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="analysis_actions",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        confidence=confidence,
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry",
            "cluster": cluster,
        },
        side_effect_class=SideEffectClass.NONE,
    )


def analysis_evaluate_goal_progress(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = EvaluateGoalProgressInput.model_validate(invocation.input)
    result = evaluate_goal_progress(
        goal=payload.goal,
        kpis=list(payload.kpis),
        current_state=payload.current_state,
        previous_state=payload.previous_state,
        events=list(payload.events),
        evidence_ids=list(payload.evidence_ids),
        missing_evidence_codes=list(payload.missing_evidence_codes),
    )
    output = result.model_dump(mode="json")
    summary = (
        f"Goal {result.goal_id} progress={result.status.value} "
        f"confidence={result.confidence} gaps={len(result.progress_gaps)}"
    )
    return ActionResult(
        action="analysis.evaluate_goal_progress",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.evaluate_goal_progress",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=result.confidence,
                cluster="evaluation_intelligence",
            )
        ],
        summary=summary,
        confidence=result.confidence,
    )


def analysis_evaluate_outcome(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = EvaluateOutcomeInput.model_validate(invocation.input)
    expectation = OutcomeExpectation(
        goal=payload.goal,
        subject_refs=list(payload.subject_refs),
        baseline_kpis=list(payload.baseline_kpis),
        baseline_snapshot=payload.baseline_snapshot,
        success_criteria_codes=list(payload.success_criteria_codes),
    )
    observed = ObservedOutcome(
        observed_kpis=list(payload.observed_kpis),
        observed_snapshot=payload.observed_snapshot,
        observed_at=payload.observed_at,
        source_observed_at=payload.source_observed_at,
        captured_at=payload.captured_at,
        asserted_observed_at=payload.asserted_observed_at,
        events=list(payload.events),
        evidence_ids=list(payload.evidence_ids),
        missing_evidence_codes=list(payload.missing_evidence_codes),
    )
    result = evaluate_outcome(
        expectation=expectation,
        observed=observed,
        attribution=payload.attribution,
        attribution_evidence=payload.attribution_evidence,
    )
    output = result.model_dump(mode="json")
    summary = (
        f"Outcome goal={result.goal_id} status={result.status.value} "
        f"confidence={result.confidence} deltas={len(result.kpi_deltas)} "
        f"attribution={result.attribution.value}"
    )
    return ActionResult(
        action="analysis.evaluate_outcome",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.evaluate_outcome",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=result.confidence,
                cluster="outcome_intelligence",
            )
        ],
        summary=summary,
        confidence=result.confidence,
    )


def analysis_assess_attribution_integrity(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = AssessAttributionIntegrityInput.model_validate(invocation.input)
    timing = resolve_observation_timing(
        source_observed_at=payload.source_observed_at,
        captured_at=payload.captured_at,
        asserted_observed_at=payload.asserted_observed_at,
    )
    result: AttributionAssessmentEvidence = evaluate_attribution_evidence(
        evidence=payload.evidence,
        observation_timing=timing,
    )
    output = result.model_dump(mode="json")
    summary = (
        f"Attribution={result.resulting_attribution.value} "
        f"chronology={result.observation_timing.provenance.value} "
        f"ordering={result.ordering.value} causal_claim={result.causal_claim}"
    )
    return ActionResult(
        action="analysis.assess_attribution_integrity",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.assess_attribution_integrity",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=result.confidence,
                cluster="observation_attribution_integrity",
            )
        ],
        summary=summary,
        confidence=result.confidence,
        limitations=["Non-causal structural assessment; source truth is not independently verified."],
    )


def analysis_compare_experiences(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CompareExperiencesInput.model_validate(invocation.input)
    result = evaluate_experience_set(list(payload.episodes))
    output = {
        "signatures": [s.model_dump(mode="json") for s in result.signatures],
        "comparisons": [c.model_dump(mode="json") for c in result.comparisons],
        "unclassified_episode_ids": list(result.unclassified_episode_ids),
        "excluded_episode_ids": list(result.excluded_episode_ids),
        "dependent_episode_groups": [list(g) for g in result.dependent_episode_groups],
        "partition_explanations": result.partition_explanations,
        "algorithm": result.algorithm,
    }
    summary = (
        f"Compared {len(result.signatures)} experience episodes across "
        f"{len(result.partition_explanations)} semantic partitions; "
        f"candidates={len(result.pattern_candidates)}"
    )
    return ActionResult(
        action="analysis.compare_experiences",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.compare_experiences",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=None,
                cluster="experience_intelligence",
            )
        ],
        summary=summary,
    )


def analysis_assess_experience_recurrence(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = AssessExperienceRecurrenceInput.model_validate(invocation.input)
    result = evaluate_experience_set(list(payload.episodes))
    output = result.model_dump(mode="json")
    summary = f"Assessed {len(result.signatures)} experience episodes; candidates={len(result.pattern_candidates)} unclassified={len(result.unclassified_episode_ids)}"
    return ActionResult(
        action="analysis.assess_experience_recurrence",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.assess_experience_recurrence",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=None,
                cluster="experience_intelligence",
            )
        ],
        summary=summary,
        limitations=list(result.epistemic_limits),
    )


def analysis_qualify_pattern_knowledge(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = QualifyPatternKnowledgeInput.model_validate(invocation.input)
    result = qualify_pattern_knowledge(payload.candidate)
    output = result.model_dump(mode="json")
    summary = f"Qualified Experience candidate {result.source_candidate_id}: {result.status.value}"
    return ActionResult(
        action="analysis.qualify_pattern_knowledge",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.qualify_pattern_knowledge",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=None,
                cluster="knowledge_qualification",
            )
        ],
        summary=summary,
        limitations=list(result.epistemic_limits),
    )


def register_analysis_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="analysis.materialize_decision_learning_signal",
            handler=analysis_materialize_decision_learning_signal,
            provider="ajenda_analysis",
            input_model=DecisionEpisodeMaterializationRequest,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.assess_attribution_integrity",
            handler=analysis_assess_attribution_integrity,
            provider="ajenda_analysis",
            input_model=AssessAttributionIntegrityInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.evaluate_goal_progress",
            handler=analysis_evaluate_goal_progress,
            provider="ajenda_analysis",
            input_model=EvaluateGoalProgressInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.evaluate_outcome",
            handler=analysis_evaluate_outcome,
            provider="ajenda_analysis",
            input_model=EvaluateOutcomeInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.compare_experiences",
            handler=analysis_compare_experiences,
            provider="ajenda_analysis",
            input_model=CompareExperiencesInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.assess_experience_recurrence",
            handler=analysis_assess_experience_recurrence,
            provider="ajenda_analysis",
            input_model=AssessExperienceRecurrenceInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.qualify_pattern_knowledge",
            handler=analysis_qualify_pattern_knowledge,
            provider="ajenda_analysis",
            input_model=QualifyPatternKnowledgeInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )

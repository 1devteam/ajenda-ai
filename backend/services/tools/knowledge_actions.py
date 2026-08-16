from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.durable_learning_signal_repository import DurableLearningSignalRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.services.durable_experience_consolidation import DurableExperienceConsolidationService
from backend.services.knowledge.knowledge_applicability import (
    ContextConditionAssertion,
    KnowledgeApplicabilityContext,
    SourceConditionObservation,
    resolve_knowledge_applicability,
    validate_context_for_query,
)
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionCriterion,
    KnowledgeDecisionOption,
    KnowledgeInfluenceDirection,
    evaluate_knowledge_decision_support,
    knowledge_support_evidence_facts,
)
from backend.services.knowledge.knowledge_ledger import record_knowledge_qualification
from backend.services.knowledge.knowledge_lifecycle import resolve_current_knowledge_state
from backend.services.knowledge.knowledge_retrieval import KnowledgeRetrievalQuery, retrieve_current_knowledge
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.knowledge_qualification import KnowledgeQualificationResult
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.decision_actions import decision_recommend_next_action
from backend.services.tools.evidence_bridge import (
    require_canonical_source_observation_evidence,
    require_canonical_tool_action_evidence,
)
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    DecisionRecommendInput,
    EvidenceFact,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


def _normalize_decision_evidence_ids(
    decision_output: dict[str, object],
    *,
    derived_facts: tuple[EvidenceFact, ...],
    influence_ids: tuple[str, ...],
) -> dict[str, object]:
    """Keep synthetic scoring identities out of durable Decision references.

    The canonical scorer is intentionally unchanged and may refer to the
    synthetic identity of a derived fact in dimension diagnostics.  The composed
    action's durable artifact must instead cite only the EvidenceRecord UUIDs
    that establish that fact.  Influence identities remain diagnostic and never
    occupy an evidence field.
    """

    mapping = {
        fact.evidence_id: tuple(fact.durable_source_evidence_ids)
        for fact in derived_facts
        if fact.durable_source_evidence_ids
    }

    def normalize(values: object) -> list[str]:
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("canonical Decision evidence references must be a list of strings")
        normalized: list[str] = []
        for value in values:
            for durable_id in mapping.get(value, (value,)):
                if durable_id not in normalized:
                    normalized.append(durable_id)
        return normalized

    output = dict(decision_output)
    output["supporting_evidence_ids"] = normalize(output.get("supporting_evidence_ids", []))
    raw_scores = output.get("option_scores", [])
    if not isinstance(raw_scores, list) or not all(isinstance(item, dict) for item in raw_scores):
        raise ValueError("canonical Decision option_scores must be a list of objects")
    scores: list[dict[str, object]] = []
    for raw_score in raw_scores:
        score = dict(raw_score)
        score["supporting_evidence_ids"] = normalize(score.get("supporting_evidence_ids", []))
        raw_dimensions = score.get("dimension_scores", [])
        if not isinstance(raw_dimensions, list) or not all(isinstance(item, dict) for item in raw_dimensions):
            raise ValueError("canonical Decision dimension_scores must be a list of objects")
        dimensions: list[dict[str, object]] = []
        for raw_dimension in raw_dimensions:
            dimension = dict(raw_dimension)
            dimension["evidence_ids"] = normalize(dimension.get("evidence_ids", []))
            dimensions.append(dimension)
        score["dimension_scores"] = dimensions
        scores.append(score)
    output["option_scores"] = scores
    output["knowledge_influence_ids"] = list(influence_ids)
    return output


def _materialization_decision_input(scoring_input: dict[str, object], *, derived_fact_count: int) -> dict[str, object]:
    """Build the audit/materialization view with durable evidence identities.

    Caller-owned facts are copied byte-for-byte. Each appended Knowledge-derived
    scoring fact is expanded over its real durable ancestry. Its claim remains
    explicitly INFERRED and Knowledge-owned; this normalization does not assert
    that the source EvidenceRecord authored the derived semantic claim.
    """

    raw_evidence = scoring_input.get("evidence", [])
    if not isinstance(raw_evidence, list) or not all(isinstance(item, dict) for item in raw_evidence):
        raise ValueError("canonical Decision evidence must be a list of objects")
    caller_count = len(raw_evidence) - derived_fact_count
    if caller_count < 0:
        raise ValueError("derived Decision evidence count exceeds canonical input")
    normalized: list[dict[str, object]] = [dict(item) for item in raw_evidence[:caller_count]]
    for raw_fact in raw_evidence[caller_count:]:
        sources = raw_fact.get("durable_source_evidence_ids")
        if not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources):
            raise ValueError("Knowledge-derived Decision evidence lacks durable ancestry")
        for source_id in sources:
            fact = dict(raw_fact)
            fact["evidence_id"] = source_id
            fact["lineage"] = {
                "schema_version": 1,
                "artifact_evidence_id": source_id,
                "origin_type": "derived_fact",
                "root_evidence_ids": [source_id],
                "parent_evidence_ids": [source_id],
                "ancestor_evidence_ids": [source_id],
                "resolution": "known",
            }
            fact["durable_source_evidence_ids"] = [source_id]
            normalized.append(fact)
    materialized = dict(scoring_input)
    materialized["evidence"] = normalized
    return materialized


class RecordKnowledgeQualificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: KnowledgeQualificationResult


class ResolveCurrentKnowledgeStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposition_key: str


class RetrieveCurrentKnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: KnowledgeRetrievalQuery


class EvaluateKnowledgeApplicabilityInput(BaseModel):
    """Production composition input; Retrieval output is never caller-authored."""

    model_config = ConfigDict(extra="forbid")

    query: KnowledgeRetrievalQuery
    context: KnowledgeApplicabilityContext


class KnowledgeInformedDecisionSupportInput(BaseModel):
    """Production input: owner artifacts are recomputed, never caller-authored."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    decision: DecisionRecommendInput
    options: tuple[KnowledgeDecisionOption, ...]
    criteria: tuple[KnowledgeDecisionCriterion, ...]
    query: KnowledgeRetrievalQuery
    applicability_context: KnowledgeApplicabilityContext


class ConsolidateLearningHistoryInput(BaseModel):
    """No-input contract: active runtime tenant is the sole history authority."""

    model_config = ConfigDict(extra="forbid")


def knowledge_consolidate_learning_history(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Compose durable tenant history through Experience, Qualification, and Ledger."""

    ConsolidateLearningHistoryInput.model_validate(invocation.input)
    if context.session_factory is None:
        raise RuntimeError("durable experience consolidation requires a primary session factory")
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        result = DurableExperienceConsolidationService(history=DurableLearningSignalRepository(session)).consolidate(
            session, tenant_id=context.tenant_id
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    output = result.model_dump(mode="json")
    records_inspected = [f"evidence:{item}" for item in result.records_inspected]
    records_changed = [
        reference
        for item in result.qualifications
        for reference in (
            f"knowledge_qualification:{item.ledger_write.qualification_record_id}"
            if item.ledger_write.qualification_created and item.ledger_write.qualification_record_id
            else None,
            f"knowledge_artifact:{item.ledger_write.artifact_record_id}"
            if item.ledger_write.artifact_created and item.ledger_write.artifact_record_id
            else None,
        )
        if reference is not None
    ]
    summary = (
        f"Consolidated {len(result.valid_learning_signal_ids)} durable learning signals into "
        f"{len(result.qualifications)} qualification results."
    )
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="durable_experience_consolidation",
        action_name="knowledge.consolidate_learning_history",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=records_inspected,
        records_changed=records_changed,
        limitations=list(result.limitations),
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> DurableExperienceConsolidationService",
            "evidence_role": "experience_consolidation_result",
        },
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
    )
    return ActionResult(
        action="knowledge.consolidate_learning_history",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        records_inspected=records_inspected,
        records_changed=records_changed,
        summary=summary,
        limitations=list(result.limitations),
    )


def knowledge_record_qualification(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordKnowledgeQualificationInput.model_validate(invocation.input)
    if payload.result.proposition is None:
        write = record_knowledge_qualification(
            cast(Session, _NoMutationSession()), tenant_id=context.tenant_id, result=payload.result
        )
    else:
        if context.session_factory is None:
            raise RuntimeError("knowledge persistence requires a primary session factory")
        session = context.session_factory()
        try:
            activate_tenant_session(session, context.tenant_id)
            write = record_knowledge_qualification(session, tenant_id=context.tenant_id, result=payload.result)
            session.commit()
            write = write.model_copy(update={"persistence_committed": True})
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    output = write.model_dump(mode="json")
    output.update({"qualification_status": payload.result.status.value, "algorithm": payload.result.algorithm})
    changed: list[str] = []
    if write.qualification_created and write.qualification_record_id:
        changed.append(f"knowledge_qualification:{write.qualification_record_id}")
    if write.artifact_created and write.artifact_record_id:
        changed.append(f"knowledge_artifact:{write.artifact_record_id}")
    summary = f"Knowledge qualification persistence: {write.status.value}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_ledger",
        action_name="knowledge.record_qualification",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_changed=changed,
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
    )
    return ActionResult(
        action="knowledge.record_qualification",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        records_changed=changed,
        summary=summary,
    )


def knowledge_resolve_current_state(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = ResolveCurrentKnowledgeStateInput.model_validate(invocation.input)
    if context.session_factory is None:
        raise RuntimeError("knowledge lifecycle resolution requires a primary session factory")
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        state = resolve_current_knowledge_state(
            session, tenant_id=context.tenant_id, proposition_key=payload.proposition_key
        )
    finally:
        session.close()

    output = state.model_dump(mode="json")
    evidence_payload = {
        key: output[key]
        for key in (
            "proposition_key",
            "lifecycle_status",
            "evaluation_frontier",
            "authoritative_qualification_ids",
            "authoritative_knowledge_ids",
            "historical_qualification_count",
            "reason_codes",
            "epistemic_limits",
            "algorithm",
        )
    }
    records_inspected = [
        *(f"knowledge_qualification:{item}" for item in state.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in state.authoritative_knowledge_ids),
    ]
    summary = f"Current knowledge lifecycle state: {state.lifecycle_status.value}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_lifecycle_resolution",
        action_name="knowledge.resolve_current_state",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=evidence_payload,
        records_inspected=records_inspected,
        limitations=list(state.epistemic_limits),
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="knowledge.resolve_current_state",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=records_inspected,
        summary=summary,
        limitations=list(state.epistemic_limits),
    )


def knowledge_retrieve_current(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RetrieveCurrentKnowledgeInput.model_validate(invocation.input)
    if context.session_factory is None:
        raise RuntimeError("knowledge retrieval requires a primary session factory")
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        result = retrieve_current_knowledge(session, tenant_id=context.tenant_id, query=payload.query)
    finally:
        session.close()
    output = result.model_dump(mode="json")
    proposition_keys = [item.proposition.proposition_key for item in result.matches]
    knowledge_ids = [artifact.knowledge_id for item in result.matches for artifact in item.authoritative_artifacts]
    trace = result.inspection_trace
    records_inspected = [
        *(f"knowledge_proposition:{item}" for item in trace.candidate_proposition_keys),
        *(f"knowledge_qualification:{item}" for item in trace.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in trace.artifact_knowledge_ids_loaded),
    ]
    evidence_payload = {
        "retrieval_id": result.retrieval_id,
        "candidate_proposition_count": result.candidate_proposition_count,
        "active_proposition_count": result.active_proposition_count,
        "semantic_match_count": result.semantic_match_count,
        "matched_proposition_keys": proposition_keys,
        "authoritative_knowledge_ids": knowledge_ids,
        "goal_comparison_statuses": [item.goal_comparison.status.value for item in result.matches],
        "algorithm": result.algorithm,
        "epistemic_limits": list(result.epistemic_limits),
        "inspected_candidate_proposition_keys": list(trace.candidate_proposition_keys),
        "inspected_lifecycle_projection_ids": list(trace.lifecycle_projection_ids),
        "inspected_authoritative_qualification_ids": list(trace.authoritative_qualification_ids),
        "inspected_artifact_knowledge_ids": list(trace.artifact_knowledge_ids_loaded),
    }
    summary = f"Current semantic knowledge matches: {result.semantic_match_count}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_retrieval",
        action_name="knowledge.retrieve_current",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=evidence_payload,
        records_inspected=records_inspected,
        limitations=list(result.epistemic_limits),
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="knowledge.retrieve_current",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=records_inspected,
        summary=summary,
        limitations=list(result.epistemic_limits),
    )


def knowledge_evaluate_applicability(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Retrieve tenant-current knowledge and evaluate explicit present context."""

    payload = EvaluateKnowledgeApplicabilityInput.model_validate(invocation.input)
    validate_context_for_query(query=payload.query, context=payload.context)
    if context.session_factory is None:
        raise RuntimeError("knowledge applicability requires a primary session factory")
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        retrieval = retrieve_current_knowledge(session, tenant_id=context.tenant_id, query=payload.query)
        result = resolve_knowledge_applicability(retrieval=retrieval, context=payload.context)
    finally:
        session.close()

    output = result.model_dump(mode="json")
    trace = retrieval.inspection_trace
    records_inspected = [
        *(f"knowledge_proposition:{item}" for item in trace.candidate_proposition_keys),
        *(f"knowledge_qualification:{item}" for item in trace.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in trace.artifact_knowledge_ids_loaded),
    ]
    referenced_evidence = [f"evidence:{item}" for item in result.referenced_evidence_ids]
    summary = f"Current knowledge applicability evaluations: {len(result.evaluations)}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_applicability",
        action_name="knowledge.evaluate_applicability",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "resolution_id": result.resolution_id,
            "retrieval_id": retrieval.retrieval_id,
            "evaluations": [item.model_dump(mode="json") for item in result.evaluations],
            "referenced_evidence_ids": list(result.referenced_evidence_ids),
            "reason_codes": list(result.reason_codes),
            "algorithm": result.algorithm,
        },
        records_inspected=records_inspected,
        limitations=list(result.epistemic_limits),
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> Knowledge Retrieval -> Knowledge Applicability",
            "referenced_evidence_not_inspected": referenced_evidence,
        },
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="knowledge.evaluate_applicability",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=records_inspected,
        summary=summary,
        limitations=list(result.epistemic_limits),
    )


def knowledge_inform_decision(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Compose Retrieval → Applicability → bounded support → canonical Decision."""

    payload = KnowledgeInformedDecisionSupportInput.model_validate(invocation.input)
    validate_context_for_query(query=payload.query, context=payload.applicability_context)
    support_criteria = [
        item.model_dump(exclude={"objective_key", "kpi_semantic_signature"}) for item in payload.criteria
    ]
    decision_criteria = [item.model_dump() for item in payload.decision.criteria]
    if [item.model_dump() for item in payload.options] != [
        item.model_dump() for item in payload.decision.options
    ] or support_criteria != decision_criteria:
        raise ValueError("typed support options/criteria must exactly match the Decision-owned request")
    if context.session_factory is None:
        raise RuntimeError("knowledge-informed decision support requires a primary session factory")
    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        retrieval = retrieve_current_knowledge(session, tenant_id=context.tenant_id, query=payload.query)
        applicability = resolve_knowledge_applicability(retrieval=retrieval, context=payload.applicability_context)
        support = evaluate_knowledge_decision_support(
            decision_id=payload.decision_id,
            options=payload.options,
            criteria=payload.criteria,
            applicability=applicability,
            evaluated_at=payload.applicability_context.evaluated_at,
        )
        scoring_applicability_ids = {
            item.applicability_id
            for item in support.influences
            if item.direction == KnowledgeInfluenceDirection.SUPPORTS and item.criterion_id is not None
        }
        scoring_evaluations = tuple(
            item for item in applicability.evaluations if item.applicability_id in scoring_applicability_ids
        )
        _validate_applicability_evidence(
            session=session,
            tenant_id=context.tenant_id,
            mission_id=context.mission_id,
            evaluated_at=payload.applicability_context.evaluated_at,
            evidence_ids={evidence_id for item in scoring_evaluations for evidence_id in item.evidence_ids},
            assertions=payload.applicability_context.condition_assertions,
            required_condition_keys={
                condition_key
                for item in scoring_evaluations
                for condition_key in (*item.required_scope_conditions, *item.invalidation_conditions)
            },
        )
        episode_evidence_ids = _resolve_historical_episode_evidence(
            session=session,
            tenant_id=context.tenant_id,
            episode_ids=set(support.supporting_episode_ids),
        )
        derived_facts = knowledge_support_evidence_facts(
            support,
            episode_evidence_ids=episode_evidence_ids,
        )
    finally:
        session.close()
    decision_payload = payload.decision.model_dump(mode="json")
    decision_payload["evidence"] = [
        *decision_payload["evidence"],
        *(item.model_dump(mode="json") for item in derived_facts),
    ]
    decision_payload["context"] = {
        **decision_payload["context"],
        "knowledge_decision_support": {
            "support_id": support.support_id,
            "influence_ids": [item.influence_id for item in support.influences],
            "provenance_class": support.provenance_class,
            "is_independent_observation": False,
        },
    }
    decision_result = decision_recommend_next_action(
        ToolInvocation(action="decision.recommend_next_action", input=decision_payload), context
    )
    scoring_influence_ids = tuple(
        sorted(
            item.influence_id
            for item in support.influences
            if item.direction == KnowledgeInfluenceDirection.SUPPORTS
            and item.criterion_id is not None
            and item.supporting_episode_ids
        )
    )
    normalized_decision_result = _normalize_decision_evidence_ids(
        decision_result.output,
        derived_facts=derived_facts,
        influence_ids=scoring_influence_ids,
    )
    materialization_input = _materialization_decision_input(
        decision_payload,
        derived_fact_count=len(derived_facts),
    )
    output = {
        "support": support.model_dump(mode="json"),
        "scoring_decision_input": decision_payload,
        "decision_input": materialization_input,
        "decision_result": normalized_decision_result,
    }
    records_inspected = [
        *(f"knowledge_proposition:{item}" for item in retrieval.inspection_trace.candidate_proposition_keys),
        *(f"knowledge_qualification:{item}" for item in retrieval.inspection_trace.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in retrieval.inspection_trace.artifact_knowledge_ids_loaded),
        *(f"evidence:{item}" for item in sorted(support.applicability_evidence_ids)),
        *(f"evidence:{item}" for item in sorted(episode_evidence_ids.values())),
    ]
    parent_ids = tuple(sorted(episode_evidence_ids.values()))
    lineage = EvidenceLineage(
        artifact_evidence_id=support.support_id,
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=parent_ids,
        resolution=(EvidenceLineageResolution.PARTIAL if parent_ids else EvidenceLineageResolution.UNKNOWN),
    )
    summary = f"Bounded knowledge influences evaluated: {len(support.influences)}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_decision_support",
        action_name="knowledge.inform_decision",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=records_inspected,
        limitations=list(support.epistemic_limits),
        provenance={
            "runtime_path": (
                "TaskDispatcher -> tool.invoke -> Knowledge Retrieval -> Knowledge Applicability "
                "-> Knowledge Decision Support -> decision.recommend_next_action"
            ),
            "provenance_class": "derived_knowledge_influence",
            "is_independent_observation": False,
            "evidence_role": "decision_recommendation_result",
            "composed_action": "decision.recommend_next_action",
            "composition_schema_version": 1,
        },
        lineage=lineage,
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="knowledge.inform_decision",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=records_inspected,
        summary=summary,
        limitations=list(support.epistemic_limits),
    )


def _validate_applicability_evidence(
    *,
    session: Session,
    tenant_id: str,
    mission_id: uuid.UUID | None,
    evaluated_at: datetime,
    evidence_ids: set[str],
    assertions: tuple[ContextConditionAssertion, ...],
    required_condition_keys: set[str],
) -> None:
    """Require owner-produced current-condition proof before Decision scoring."""

    if evidence_ids and mission_id is None:
        raise ValueError("Knowledge applicability evidence requires mission provenance")
    assertions_by_key = {assertion.condition_key: assertion for assertion in assertions}
    required_assertions = tuple(
        assertions_by_key[key] for key in sorted(required_condition_keys) if key in assertions_by_key
    )
    if len(required_assertions) != len(required_condition_keys) or any(
        not assertion.evidence_ids for assertion in required_assertions
    ):
        raise ValueError("Knowledge applicability scoring requires evidence for every resolved condition")
    if any(
        assertion.verification_basis != ObservationVerificationBasis.SOURCE_SUPPLIED_UNDER_CONTRACT
        for assertion in required_assertions
    ):
        raise ValueError(
            "Knowledge applicability scoring requires source-supplied evidence; "
            "independent verification cannot be caller-asserted"
        )
    authoritative_ids = {evidence_id for assertion in required_assertions for evidence_id in assertion.evidence_ids}
    if evidence_ids != authoritative_ids:
        raise ValueError("Knowledge applicability scoring evidence disagrees with resolved conditions")
    repository = EvidenceRepository(session)
    for raw_id in sorted(evidence_ids):
        try:
            evidence_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise ValueError("Knowledge applicability source must be a durable EvidenceRecord UUID") from exc
        record = repository.get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)
        if record is None:
            raise ValueError("Knowledge applicability evidence is inaccessible")
        if record.mission_id != mission_id:
            raise ValueError("Knowledge applicability evidence mission provenance disagrees")
        for field in ("observed_at", "executed_at", "evaluated_at", "decided_at"):
            raw_time = record.structured_payload.get(field)
            if raw_time is None:
                continue
            if not isinstance(raw_time, str):
                raise ValueError("Knowledge applicability chronology must be an ISO-8601 string")
            event_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if event_time.tzinfo is None or event_time.utcoffset() is None:
                raise ValueError("Knowledge applicability chronology must include a timezone")
            if event_time > evaluated_at:
                raise ValueError("future evidence cannot establish earlier Knowledge applicability")
        raw_lineage = record.provenance_metadata.get("evidence_lineage")
        if raw_lineage is None:
            raise ValueError("Knowledge applicability evidence requires explicit source-observation lineage")
        durable_lineage = EvidenceLineage.model_validate(raw_lineage)
        if durable_lineage.artifact_evidence_id != str(record.id):
            raise ValueError("Knowledge applicability evidence lineage identity disagrees")
        if durable_lineage.origin_type != EvidenceOriginType.SOURCE_OBSERVATION:
            raise ValueError("derived evidence cannot establish fresh Knowledge applicability")
        evidence_item = require_canonical_source_observation_evidence(session=session, record=record)
        raw_observations = evidence_item.structured_payload.get("condition_observations")
        if not isinstance(raw_observations, list) or not raw_observations:
            raise ValueError("Knowledge applicability source does not emit condition semantics")
        try:
            observations = tuple(SourceConditionObservation.model_validate(item) for item in raw_observations)
        except ValidationError as exc:
            raise ValueError("Knowledge applicability source condition semantics are malformed") from exc
        if any(item.observed_at > evaluated_at for item in observations):
            raise ValueError("future source semantics cannot establish earlier Knowledge applicability")
        for assertion in required_assertions:
            if raw_id not in assertion.evidence_ids:
                continue
            if not any(
                observation.condition_key == assertion.condition_key
                and observation.state == assertion.state
                and observation.subject_refs == assertion.subject_refs
                and observation.observed_at == assertion.observed_at
                and observation.verification_basis == assertion.verification_basis
                for observation in observations
            ):
                raise ValueError("Knowledge applicability source does not establish the asserted condition semantics")


def _resolve_historical_episode_evidence(
    *,
    session: Session,
    tenant_id: str,
    episode_ids: set[str],
) -> dict[str, str]:
    """Resolve Qualification-owned episode identities to canonical durable signals.

    Historical Knowledge may cross mission boundaries but never tenant boundaries.
    Duplicate persistence of an identical logical episode resolves deterministically
    to the lowest EvidenceRecord UUID and cannot increase support.
    """

    if not episode_ids:
        return {}
    resolved: dict[str, tuple[str, DecisionLearningSignal]] = {}
    for record in DurableLearningSignalRepository(session).list_candidates_for_tenant(tenant_id=tenant_id):
        if record.provenance_metadata.get("evidence_role") != "decision_learning_signal":
            continue
        require_canonical_tool_action_evidence(
            session=session,
            record=record,
            expected_action="analysis.materialize_decision_learning_signal",
            expected_role="decision_learning_signal",
        )
        try:
            signal = DecisionLearningSignal.model_validate(record.structured_payload)
        except Exception as exc:
            raise ValueError("durable Knowledge history contains a malformed learning signal") from exc
        reference = signal.episode_reference
        episode_id = reference.episode_id if reference is not None else f"legacy:{signal.signal_id}"
        if episode_id not in episode_ids:
            continue
        existing = resolved.get(episode_id)
        candidate = (str(record.id), signal)
        if existing is not None and existing[1] != signal:
            raise ValueError("Knowledge support episode has contradictory durable learning signals")
        if existing is None or candidate[0] < existing[0]:
            resolved[episode_id] = candidate
    missing = sorted(episode_ids - resolved.keys())
    if missing:
        raise ValueError("Knowledge support episode lacks durable learning-signal evidence")
    return {episode_id: item[0] for episode_id, item in sorted(resolved.items())}


class _NoMutationSession:
    """Sentinel proving proposition-less results cannot access persistence."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"ineligible qualification attempted session operation {name}")


def register_knowledge_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="knowledge.inform_decision",
            handler=knowledge_inform_decision,
            provider="ajenda_knowledge",
            input_model=KnowledgeInformedDecisionSupportInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="knowledge.evaluate_applicability",
            handler=knowledge_evaluate_applicability,
            provider="ajenda_knowledge",
            input_model=EvaluateKnowledgeApplicabilityInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="knowledge.consolidate_learning_history",
            handler=knowledge_consolidate_learning_history,
            provider="ajenda_knowledge",
            input_model=ConsolidateLearningHistoryInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="knowledge.record_qualification",
            handler=knowledge_record_qualification,
            provider="ajenda_knowledge",
            input_model=RecordKnowledgeQualificationInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="knowledge.retrieve_current",
            handler=knowledge_retrieve_current,
            provider="ajenda_knowledge",
            input_model=RetrieveCurrentKnowledgeInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="knowledge.resolve_current_state",
            handler=knowledge_resolve_current_state,
            provider="ajenda_knowledge",
            input_model=ResolveCurrentKnowledgeStateInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.durable_learning_signal_repository import DurableLearningSignalRepository
from backend.services.durable_experience_consolidation import DurableExperienceConsolidationService
from backend.services.knowledge.knowledge_applicability import (
    KnowledgeApplicabilityContext,
    resolve_knowledge_applicability,
    validate_context_for_query,
)
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionCriterion,
    KnowledgeDecisionOption,
    evaluate_knowledge_decision_support,
)
from backend.services.knowledge.knowledge_ledger import record_knowledge_qualification
from backend.services.knowledge.knowledge_lifecycle import resolve_current_knowledge_state
from backend.services.knowledge.knowledge_retrieval import KnowledgeRetrievalQuery, retrieve_current_knowledge
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.knowledge_qualification import KnowledgeQualificationResult
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.decision_actions import decision_recommend_next_action
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    DecisionRecommendInput,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


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
    finally:
        session.close()
    support = evaluate_knowledge_decision_support(
        decision_id=payload.decision_id,
        options=payload.options,
        criteria=payload.criteria,
        applicability=applicability,
        evaluated_at=payload.applicability_context.evaluated_at,
    )
    decision_payload = payload.decision.model_dump(mode="json")
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
    output = {
        "support": support.model_dump(mode="json"),
        "decision_result": decision_result.output,
    }
    records_inspected = [
        *(f"knowledge_proposition:{item}" for item in retrieval.inspection_trace.candidate_proposition_keys),
        *(f"knowledge_qualification:{item}" for item in retrieval.inspection_trace.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in retrieval.inspection_trace.artifact_knowledge_ids_loaded),
    ]
    parent_ids = tuple(sorted({*support.knowledge_ids_considered, *support.supporting_evidence_ids}))
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

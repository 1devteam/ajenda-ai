from __future__ import annotations

import uuid
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.durable_learning_signal_repository import DurableLearningSignalRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.durable_experience_consolidation import DurableExperienceConsolidationService
from backend.services.knowledge.knowledge_applicability import (
    KnowledgeApplicabilityContext,
    resolve_knowledge_applicability,
    validate_context_for_query,
)
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionCriterion,
    KnowledgeDecisionOption,
    KnowledgeDecisionSupportResult,
    build_knowledge_decision_evidence,
    evaluate_knowledge_decision_support,
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


def _durable_knowledge_ancestry(
    session: Session,
    *,
    tenant_id: str,
    mission_id: uuid.UUID | None,
    support: KnowledgeDecisionSupportResult,
) -> dict[str, tuple[str, ...]]:
    """Resolve Knowledge's supporting episodes back to tenant-owned world evidence.

    Candidate IDs are provenance references, never evidence roots. Ancestry that
    cannot be resolved to durable UUID EvidenceRecords in the recommendation
    mission is omitted so the corresponding influence cannot become scoring input.
    """

    qualification_repository = KnowledgeRepository(session)
    evidence_repository = EvidenceRepository(session)
    learning_records = DurableLearningSignalRepository(session).list_candidates_for_tenant(tenant_id=tenant_id)
    signals_by_episode: dict[str, DecisionLearningSignal] = {}
    for learning_record in learning_records:
        try:
            parsed_signal = DecisionLearningSignal.model_validate(learning_record.structured_payload)
        except Exception:
            continue
        if parsed_signal.episode_reference is not None:
            signals_by_episode[parsed_signal.episode_reference.episode_id] = parsed_signal

    roots_by_proposition: dict[str, set[str]] = {}
    for match in support.applicability.retrieval.matches:
        proposition_roots = roots_by_proposition.setdefault(match.proposition.proposition_key, set())
        for qualification_id in match.current_state.authoritative_qualification_ids:
            qualification_record = qualification_repository.get_qualification_for_tenant(
                tenant_id=tenant_id, qualification_id=qualification_id
            )
            if qualification_record is None:
                continue
            try:
                qualification = KnowledgeQualificationResult.model_validate(qualification_record.qualification_payload)
            except Exception:
                continue
            for episode_id in qualification.evidence_summary.supporting_episode_ids:
                episode_signal = signals_by_episode.get(episode_id)
                if episode_signal is None:
                    continue
                candidates = {
                    identity
                    for lineage in episode_signal.evidence_lineages
                    for identity in (
                        *lineage.root_evidence_ids,
                        *lineage.parent_evidence_ids,
                        *lineage.ancestor_evidence_ids,
                    )
                }
                candidates.update(episode_signal.supporting_evidence_ids)
                for identity in candidates:
                    try:
                        evidence_id = uuid.UUID(identity)
                    except (AttributeError, TypeError, ValueError):
                        continue
                    evidence = evidence_repository.get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)
                    if evidence is not None and (mission_id is None or evidence.mission_id == mission_id):
                        proposition_roots.add(str(evidence.id))
    return {
        influence.influence_id: tuple(sorted(roots_by_proposition.get(influence.proposition_key, set())))
        for influence in support.influences
    }


def _normalize_decision_evidence_ids(
    decision_output: dict[str, object],
    *,
    ancestry_by_derived_id: dict[str, tuple[str, ...]],
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Replace synthetic scoring identities with their durable ancestry everywhere."""

    applied: set[str] = set()

    def normalize(values: object) -> list[str]:
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("Decision evidence identity fields must be lists of strings")
        normalized: list[str] = []
        for identity in values:
            roots = ancestry_by_derived_id.get(identity)
            if roots is None:
                normalized.append(identity)
            else:
                applied.add(identity)
                normalized.extend(roots)
        return list(dict.fromkeys(normalized))

    output = dict(decision_output)
    output["supporting_evidence_ids"] = normalize(output.get("supporting_evidence_ids", []))
    raw_scores = output.get("option_scores", [])
    if not isinstance(raw_scores, list) or not all(isinstance(item, dict) for item in raw_scores):
        raise ValueError("Decision option_scores must be a list of objects")
    scores: list[dict[str, object]] = []
    for raw_score in raw_scores:
        score = dict(raw_score)
        contributor_ids = [item for item in score.get("supporting_evidence_ids", []) if item in ancestry_by_derived_id]
        score["supporting_evidence_ids"] = normalize(score.get("supporting_evidence_ids", []))
        raw_dimensions = score.get("dimension_scores", [])
        if not isinstance(raw_dimensions, list) or not all(isinstance(item, dict) for item in raw_dimensions):
            raise ValueError("Decision dimension_scores must be a list of objects")
        dimensions: list[dict[str, object]] = []
        for raw_dimension in raw_dimensions:
            dimension = dict(raw_dimension)
            contributor_ids.extend(item for item in dimension.get("evidence_ids", []) if item in ancestry_by_derived_id)
            dimension["evidence_ids"] = normalize(dimension.get("evidence_ids", []))
            dimensions.append(dimension)
        score["dimension_scores"] = dimensions
        score["knowledge_influence_ids"] = list(dict.fromkeys(contributor_ids))
        scores.append(score)
    output["option_scores"] = scores
    return output, tuple(sorted(applied))


def _materialization_decision_input(
    decision_payload: dict[str, object],
    *,
    ancestry_by_derived_id: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    """Expose durable support identities for #427 without synthetic ID leakage."""

    normalized = dict(decision_payload)
    raw_facts = normalized.get("evidence", [])
    if not isinstance(raw_facts, list) or not all(isinstance(item, dict) for item in raw_facts):
        raise ValueError("Decision evidence must be a list of objects")
    facts: list[dict[str, object]] = []
    for raw_fact in raw_facts:
        fact = dict(raw_fact)
        roots = ancestry_by_derived_id.get(str(fact.get("evidence_id")))
        if roots is None:
            facts.append(fact)
            continue
        for root in roots:
            durable_fact = dict(fact)
            durable_fact["evidence_id"] = root
            durable_fact["lineage"] = None
            facts.append(durable_fact)
    normalized["evidence"] = facts
    return normalized


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
        ancestry_by_influence = _durable_knowledge_ancestry(
            session,
            tenant_id=context.tenant_id,
            mission_id=context.mission_id,
            support=support,
        )
    finally:
        session.close()
    knowledge_evidence = build_knowledge_decision_evidence(
        support=support, durable_ancestry_by_influence=ancestry_by_influence
    )
    decision_payload = payload.decision.model_dump(mode="json")
    decision_payload["evidence"] = [
        *(item.model_dump(mode="json") for item in payload.decision.evidence),
        *(item.model_dump(mode="json") for item in knowledge_evidence),
    ]
    decision_payload["context"] = {
        **decision_payload["context"],
        "knowledge_decision_support": {
            "support_id": support.support_id,
            "influence_ids": [item.influence_id for item in support.influences],
            "applied_influence_ids": [item.evidence_id for item in knowledge_evidence],
            "provenance_class": support.provenance_class,
            "is_independent_observation": False,
        },
    }
    decision_result = decision_recommend_next_action(
        ToolInvocation(action="decision.recommend_next_action", input=decision_payload), context
    )
    normalized_decision_output, applied_influence_ids = _normalize_decision_evidence_ids(
        decision_result.output, ancestry_by_derived_id=ancestry_by_influence
    )
    normalized_decision_output["knowledge_decision_support"] = {
        "support_id": support.support_id,
        "influence_ids": [item.influence_id for item in support.influences],
        "applied_influence_ids": list(applied_influence_ids),
        "provenance_class": support.provenance_class,
        "is_independent_observation": False,
    }
    output = {
        "support": support.model_dump(mode="json"),
        "decision_input": _materialization_decision_input(
            decision_payload, ancestry_by_derived_id=ancestry_by_influence
        ),
        "decision_result": normalized_decision_output,
    }
    records_inspected = [
        *(f"knowledge_proposition:{item}" for item in retrieval.inspection_trace.candidate_proposition_keys),
        *(f"knowledge_qualification:{item}" for item in retrieval.inspection_trace.authoritative_qualification_ids),
        *(f"knowledge_artifact:{item}" for item in retrieval.inspection_trace.artifact_knowledge_ids_loaded),
    ]
    applied_fact_ids = {item.evidence_id for item in knowledge_evidence}
    durable_roots = tuple(
        sorted(
            {
                root
                for influence_id, roots in ancestry_by_influence.items()
                if influence_id in applied_fact_ids
                for root in roots
            }
        )
    )
    parent_ids = tuple(sorted(support.knowledge_ids_considered)) if durable_roots else ()
    lineage = EvidenceLineage(
        artifact_evidence_id=support.support_id,
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=parent_ids,
        root_evidence_ids=durable_roots,
        ancestor_evidence_ids=durable_roots,
        resolution=(EvidenceLineageResolution.KNOWN if durable_roots else EvidenceLineageResolution.UNKNOWN),
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
            "delegated_decision_action": "decision.recommend_next_action",
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

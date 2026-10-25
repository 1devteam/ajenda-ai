"""Analysis, synthesis, retrieval, and knowledge action input builders."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.services.knowledge.knowledge_applicability import KnowledgeApplicabilityContext
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionCriterion,
    KnowledgeDecisionOption,
)
from backend.services.knowledge.knowledge_retrieval import KnowledgeRetrievalQuery
from backend.services.mission_composition.action_input_common import (
    _compact_research_query,
    _prospect_count,
    _target_bits,
)
from backend.services.mission_composition.contracts import MissionIntent
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.types import BusinessObjectRef, business_object_semantic_signature
from backend.services.tools.knowledge_actions import KnowledgeInformedDecisionSupportInput
from backend.services.tools.schemas import DecisionRecommendInput


def _assessment_decision_input(
    *,
    intent: MissionIntent,
    assessment_context: dict[str, Any],
) -> dict[str, Any]:
    """Translate a reviewed assessment into the existing Decision input.

    The assessment owner already evaluated candidate response evidence. This
    adapter does not discover causes, retrieve knowledge, or reinterpret a
    business observation as verified runtime evidence. It supplies bounded,
    explicitly *inferred* decision facts and preserves their non-canonical
    provenance in context. Consequently, a later learning episode still
    requires the existing canonical recommendation/outcome/execution evidence
    checks rather than treating an assessment identifier as source evidence.
    """

    assessment_id = assessment_context.get("assessment_id")
    condition = assessment_context.get("condition_summary")
    candidates = assessment_context.get("candidate_responses")
    if not isinstance(assessment_id, str) or not assessment_id.strip():
        raise ValueError("business need assessment context requires an assessment_id")
    if not isinstance(condition, str) or not condition.strip():
        raise ValueError("business need assessment context requires a condition_summary")
    if not isinstance(candidates, list):
        raise ValueError("business need assessment context requires candidate_responses")

    options: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    constraints = [
        "Assessment-derived facts are analytical claims, not independently verified causal evidence.",
        "Capability availability does not determine whether a response is justified.",
        "Do not execute work from this recommendation.",
    ]
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        response_key = raw.get("response_key")
        summary = raw.get("summary")
        if not isinstance(response_key, str) or not response_key.strip():
            continue
        if not isinstance(summary, str) or not summary.strip():
            continue
        response_key = response_key.strip()
        options.append(
            {
                "option_id": response_key,
                "label": response_key.replace("_", " "),
                "description": summary.strip(),
                "intervention_key": response_key,
            }
        )
        status = raw.get("evidence_status")
        knowledge_status = raw.get("knowledge_support_status")
        # A response with contradictory or unresolved observation/knowledge
        # influence cannot be promoted by this adapter. It remains an option,
        # but has no supporting decision fact.
        if status != "supported" or knowledge_status in {"opposes", "unresolved"}:
            continue
        evidence.append(
            {
                "evidence_id": f"assessment:{assessment_id}:{response_key}",
                "claim": f"The reviewed need assessment marks response '{response_key}' as observation-supported.",
                "status": "inferred",
                "source": f"business_need_assessment:{assessment_id}",
                "confidence": 0.6,
                "supports_option_ids": [response_key],
                "supports_criterion_ids": ["assessment_support"],
            }
        )
        for field in ("dependencies", "assumptions", "tradeoffs"):
            values = raw.get(field)
            if isinstance(values, list):
                constraints.extend(str(item) for item in values if isinstance(item, str) and item.strip())

    subject_refs = assessment_context.get("subject_references")
    if not isinstance(subject_refs, list):
        subject_refs = []
    return {
        "goal": condition.strip(),
        "options": options,
        "criteria": [
            {
                "criterion_id": "assessment_support",
                "label": "Observation-supported assessment",
                "weight": 1.0,
                "required": True,
            }
        ],
        "evidence": evidence,
        "constraints": list(dict.fromkeys(constraints)),
        "subject_refs": subject_refs,
        "context": {
            "review_kind": "business_need_assessment",
            "assessment_reference": {
                "assessment_id": assessment_id,
                "need_id": assessment_context.get("need_id"),
                "need_revision": assessment_context.get("need_revision"),
            },
            "assessment_evidence_class": "derived_noncanonical",
            "information_gaps": assessment_context.get("information_gaps", []),
            "causes": assessment_context.get("causes", []),
            "supporting_observation_ids": assessment_context.get("supporting_observation_ids", []),
            "contradictory_observation_ids": assessment_context.get("contradictory_observation_ids", []),
            "knowledge_epistemic_limits": assessment_context.get("knowledge_epistemic_limits", []),
            "requested_objective": intent.objective[:1000],
        },
    }


def _assessment_knowledge_decision_input(
    *,
    intent: MissionIntent,
    assessment_context: dict[str, Any],
) -> dict[str, Any]:
    """Bind reviewed assessment semantics to the existing Knowledge action.

    This is deliberately a contract adapter, not a retrieval or qualification
    implementation.  The Knowledge owner receives exact source-owned subjects,
    objective semantics, and the assessment's immutable evaluation time.  It
    may retrieve only qualified tenant knowledge and will determine
    applicability itself.  Assessment observations remain analytical facts and
    never become canonical evidence identifiers here.
    """

    decision_payload = _assessment_decision_input(intent=intent, assessment_context=assessment_context)
    assessment_id = assessment_context.get("assessment_id")
    objective_reference = assessment_context.get("objective_reference")
    evaluated_at = assessment_context.get("evaluated_at")
    raw_subjects = assessment_context.get("subject_references")
    if not isinstance(assessment_id, str) or not assessment_id.strip():
        raise ValueError("business need assessment context requires an assessment_id")
    if not isinstance(objective_reference, dict):
        raise ValueError("business need assessment context requires an objective reference")
    objective_key = objective_reference.get("objective_key")
    if not isinstance(objective_key, str) or not objective_key.strip():
        raise ValueError("business need assessment context requires an objective_key for knowledge reuse")
    if not isinstance(raw_subjects, list) or not raw_subjects:
        raise ValueError("business need assessment context requires subject references for knowledge reuse")
    if evaluated_at is None:
        raise ValueError("business need assessment context requires an evaluation timestamp for knowledge reuse")

    subject_refs = tuple(BusinessObjectRef.model_validate(item) for item in raw_subjects)
    subject_semantics = tuple(
        sorted(
            {business_object_semantic_signature(item) for item in subject_refs},
            key=lambda item: item.object_type.value,
        )
    )
    goal_semantics = GoalSemanticSignature(objective_key=objective_key.strip())
    # Validate through the exact action-owned models before compilation.  This
    # keeps composition and runtime on one contract and prevents a local
    # approximation of retrieval/applicability semantics.
    query = KnowledgeRetrievalQuery(
        subject_semantic_signatures=subject_semantics,
        goal_semantic_signature=goal_semantics,
        intervention_keys=tuple(
            str(item["intervention_key"])
            for item in decision_payload["options"]
            if isinstance(item, dict) and isinstance(item.get("intervention_key"), str)
        ),
    )
    applicability_context = KnowledgeApplicabilityContext(
        subject_refs=subject_refs,
        subject_semantic_signatures=subject_semantics,
        goal_semantic_signature=goal_semantics,
        evaluated_at=evaluated_at,
    )
    decision = DecisionRecommendInput.model_validate(decision_payload)
    options = tuple(KnowledgeDecisionOption.model_validate(item.model_dump()) for item in decision.options)
    criteria = tuple(
        KnowledgeDecisionCriterion.model_validate(
            {
                **item.model_dump(),
                "objective_key": objective_key.strip(),
            }
        )
        for item in decision.criteria
    )
    result = KnowledgeInformedDecisionSupportInput(
        decision_id=f"assessment:{assessment_id}",
        decision=decision,
        options=options,
        criteria=criteria,
        query=query,
        applicability_context=applicability_context,
    )
    return result.model_dump(mode="json")


def assessment_context_supports_qualified_knowledge(assessment_context: dict[str, Any] | None) -> bool:
    """Whether the reviewed context can satisfy the established Knowledge input.

    The boolean is used only to select an existing read-only job.  The full
    owner-contract validation above still runs when the task input is compiled.
    """

    if not isinstance(assessment_context, dict):
        return False
    try:
        # The instruction is only carried into the embedded Decision context;
        # an empty intent cannot change the typed Knowledge semantics.
        _assessment_knowledge_decision_input(
            intent=MissionIntent(objective="Reviewed business need decision"),
            assessment_context=assessment_context,
        )
    except (TypeError, ValueError):
        return False
    return True


def build_analysis_action_input(
    *,
    action_name: str,
    intent: MissionIntent,
    business_need_assessment_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    _, _, query = _target_bits(intent)
    limit = _prospect_count(intent)
    if action_name == "research.synthesize_report":
        return {
            "objective": intent.objective[:1000],
            "prospects": [],
            # A synthesis node is only selected when the graph includes the
            # upstream research job. Never report synthetic success if that
            # dependency artifact is absent at runtime.
            "binding_required": True,
        }
    if action_name == "knowledge.retrieve_current":
        return {
            "query": {
                "schema_version": 1,
                "subject_semantic_signatures": [{"schema_version": 1, "object_type": "organization"}],
                "goal_semantic_signature": {
                    "schema_version": 1,
                    "objective_key": "observe_contacts",
                    "kpis": [],
                },
            }
        }
    if action_name == "analysis.evaluate_goal_progress":
        goal_name = intent.objective[:240].strip()
        objective_key = hashlib.sha256(intent.objective.strip().encode("utf-8")).hexdigest()[:16]
        return {
            "goal": {
                "goal_id": f"mission-goal-{objective_key}",
                "objective_key": f"mission_goal_{objective_key}",
                "name": goal_name or "Mission goal",
                "description": intent.objective[:2000],
                "subject_refs": [],
                "status": "active",
            },
            "kpis": [],
            "events": [],
            "evidence_ids": [],
            "missing_evidence_codes": [
                "durable_goal_context_unavailable",
                "kpis_not_declared",
                "current_state_not_declared",
            ],
        }
    if action_name == "decision.recommend_next_action":
        if business_need_assessment_context is not None:
            return _assessment_decision_input(
                intent=intent,
                assessment_context=business_need_assessment_context,
            )
        if "review_business_income" in intent.requested_outcomes:
            return {
                "goal": intent.objective[:1000],
                "options": [],
                "criteria": [],
                "evidence": [],
                "constraints": [
                    "Use only approved business profile facts.",
                    "Do not invent revenue, costs, demand, or customer results.",
                    "Do not execute external actions.",
                ],
                "context": {
                    "review_kind": "business_income",
                    "binding_required": True,
                    "binding_source": "upstream_business_profile_facts",
                },
            }
        return {
            "goal": (intent.objective or "Recommend next research or outreach step")[:1000],
            "options": [
                {
                    "option_id": "await_observed_contacts",
                    "label": "Wait for observed contacts",
                    "description": "Do not invent emails or phones.",
                }
            ],
            "criteria": [
                {
                    "criterion_id": "has_real_contact",
                    "label": "Real observed contact",
                    "weight": 1.0,
                    "required": True,
                }
            ],
            "evidence": [],
            "constraints": ["Do not invent contact emails or phone numbers"],
            "context": {
                "binding_source": "upstream_observed_contacts",
                "binding_required": False,
            },
        }
    if action_name == "knowledge.inform_decision" and business_need_assessment_context is not None:
        return _assessment_knowledge_decision_input(
            intent=intent,
            assessment_context=business_need_assessment_context,
        )
    if action_name == "retrieval.hybrid_search" and (
        "read_business_profile" in intent.requested_outcomes or "review_business_income" in intent.requested_outcomes
    ):
        return {
            "query": "Ajenda products services target customers differentiators approved business profile",
            "limit": min(max(limit, 5), 20),
        }
    if action_name == "record.search":
        return {
            "record_type": ("contact" if "create_internal_followup_tasks" in intent.requested_outcomes else "account"),
            # Internal CRM missions request a bounded record set. Matching the
            # full natural-language instruction against stored record text can
            # hide every valid account before qualification starts.
            "query": ""
            if "internal_crm_source" in intent.context_requirements
            else _compact_research_query(intent)[:240],
            "limit": limit,
        }
    if action_name in {"document.search", "retrieval.hybrid_search"}:
        return {"query": query, "limit": limit}
    return None

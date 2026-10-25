"""Unit tests for Evidence Intelligence decision abilities (Slice 1)."""

from __future__ import annotations

import uuid

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def test_decision_recommend_is_registered() -> None:
    registry = get_default_action_registry(rebuild=True)
    definition = registry.get("decision.recommend_next_action")
    assert definition.name == "decision.recommend_next_action"
    assert definition.provider == "ajenda_decision"


def test_decision_recommend_selects_highest_supported_option() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = _context()
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                "goal": "Choose next outreach step for enterprise lead",
                "options": [
                    {"option_id": "draft_followup", "label": "Draft follow-up", "description": "Write email"},
                    {"option_id": "research_more", "label": "Research more", "description": "Gather signals"},
                ],
                "criteria": [
                    {"criterion_id": "fit", "label": "ICP fit", "weight": 2.0, "required": True},
                    {"criterion_id": "urgency", "label": "Urgency", "weight": 1.0, "required": False},
                ],
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "claim": "Lead matches ICP on company size and industry",
                        "status": "known",
                        "source": "crm",
                        "confidence": 0.95,
                        "supports_option_ids": ["draft_followup"],
                        "supports_criterion_ids": ["fit"],
                    },
                    {
                        "evidence_id": "e2",
                        "claim": "Buying window indicated in last call notes",
                        "status": "inferred",
                        "source": "notes",
                        "confidence": 0.8,
                        "supports_option_ids": ["draft_followup"],
                        "supports_criterion_ids": ["urgency"],
                    },
                    {
                        "evidence_id": "e3",
                        "claim": "Missing recent firmographic refresh",
                        "status": "missing",
                        "source": "research",
                        "confidence": 0.0,
                        "supports_option_ids": ["research_more"],
                        "supports_criterion_ids": ["fit"],
                    },
                ],
            },
        ),
        context,
    )

    assert result.action == "decision.recommend_next_action"
    assert result.provider == "ajenda_decision"
    assert result.side_effect_class.value == "none"
    assert result.output["recommendation"] == "draft_followup"
    assert result.output["confidence"] > 0.5
    assert "e1" in result.output["supporting_evidence_ids"]
    assert result.evidence[0].action_name == "decision.recommend_next_action"
    assert result.evidence[0].tenant_id == context.tenant_id
    assert result.output["algorithm"]["name"] == "weighted_criterion_evidence_v1"


def test_decision_recommend_without_options_gathers_evidence() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={"goal": "Decide whether to expand into a new region"},
        ),
        _context(),
    )
    assert result.output["recommendation"] == "gather_more_evidence"
    assert "options_absent" in result.output["uncertainty"]


def test_business_income_review_returns_bounded_opportunities_from_profile() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                "goal": "Review my business and suggest possible ways to increase income.",
                "context": {
                    "review_kind": "business_income",
                    "business_profile_facts": {
                        "profile_id": "profile-1",
                        "approved_facts": {"products_services": ["managed services"]},
                    },
                },
            },
        ),
        _context(),
    )
    report = result.output["business_review_report"]
    assert len(report["income_opportunities"]) == 3
    assert report["status"] == "evidence_limited"
    assert report["evidence"]["profile_id"] == "profile-1"
    assert result.side_effect_class.value == "none"


def test_assessment_derived_decision_does_not_promote_conflicted_response() -> None:
    intent = interpret_instruction("Use the approved business profile and recommend the next action.").model_copy(
        update={"context_requirements": ["business_need_assessment_context"]}
    )
    payload = build_action_input(
        action_name="decision.recommend_next_action",
        intent=intent,
        business_need_assessment_context={
            "assessment_id": "assessment-1",
            "need_id": "need-1",
            "need_revision": 1,
            "condition_summary": "Customer acquisition is below target.",
            "candidate_responses": [
                {
                    "response_key": "investigate_funnel",
                    "summary": "Inspect funnel-stage loss before selecting a campaign.",
                    "evidence_status": "supported",
                    "knowledge_support_status": "not_provided",
                },
                {
                    "response_key": "increase_advertising",
                    "summary": "Increase advertising spend.",
                    "evidence_status": "conflicted",
                    "knowledge_support_status": "supports",
                },
            ],
            "causes": [],
            "information_gaps": [],
            "supporting_observation_ids": [],
            "contradictory_observation_ids": [],
            "knowledge_epistemic_limits": [],
            "subject_references": [],
            "objective_reference": {},
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(action="decision.recommend_next_action", input=payload),
        _context(),
    )

    assert result.output["recommendation"] == "investigate_funnel"
    assert result.output["supporting_evidence_ids"] == ["assessment:assessment-1:investigate_funnel"]
    conflicting = next(item for item in result.output["option_scores"] if item["option_id"] == "increase_advertising")
    assert conflicting["total_score"] == 0.0


def test_decision_recommend_respects_forbid_constraint() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                "goal": "Pick channel",
                "options": [
                    {"option_id": "cold_call", "label": "Cold call"},
                    {"option_id": "email", "label": "Email"},
                ],
                "criteria": [{"criterion_id": "reach", "label": "Reach", "weight": 1.0}],
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "claim": "Phone numbers available",
                        "status": "known",
                        "confidence": 1.0,
                        "supports_option_ids": ["cold_call"],
                        "supports_criterion_ids": ["reach"],
                    },
                    {
                        "evidence_id": "e2",
                        "claim": "Email addresses available",
                        "status": "known",
                        "confidence": 0.9,
                        "supports_option_ids": ["email"],
                        "supports_criterion_ids": ["reach"],
                    },
                ],
                "constraints": ["forbid:cold_call"],
            },
        ),
        _context(),
    )
    assert result.output["recommendation"] == "email"
    cold = next(row for row in result.output["option_scores"] if row["option_id"] == "cold_call")
    assert cold["feasible"] is False


def test_decision_recommend_required_gap_lowers_or_gathers() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                "goal": "Select vendor",
                "options": [{"option_id": "vendor_a", "label": "Vendor A"}],
                "criteria": [{"criterion_id": "security", "label": "Security review", "weight": 1.0, "required": True}],
                "evidence": [],
            },
        ),
        _context(),
    )
    # Unsupported required criterion => score 0 => gather_more_evidence
    assert result.output["recommendation"] == "gather_more_evidence"
    assert result.output["what_would_change_recommendation"]


def test_sales_recommend_unchanged_by_decision_ability() -> None:
    """Slice 1 must not broaden or replace sales.recommend_next_action."""
    registry = get_default_action_registry(rebuild=True)
    lead = {"company": "Acme", "role": "VP", "intent": "expansion", "email": "avery@example.com"}
    result = registry.invoke(
        ToolInvocation(action="sales.recommend_next_action", input={"lead": lead}),
        _context(),
    )
    assert result.action == "sales.recommend_next_action"
    assert result.output["recommendation"] == "draft_followup"

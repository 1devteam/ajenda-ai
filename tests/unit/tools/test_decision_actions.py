"""Unit tests for Evidence Intelligence decision abilities (Slice 1)."""

from __future__ import annotations

import uuid

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
                "criteria": [
                    {"criterion_id": "security", "label": "Security review", "weight": 1.0, "required": True}
                ],
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

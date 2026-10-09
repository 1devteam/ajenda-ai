"""Analysis, synthesis, retrieval, and knowledge action input builders."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.services.mission_composition.action_input_common import (
    _compact_research_query,
    _prospect_count,
    _target_bits,
)
from backend.services.mission_composition.contracts import MissionIntent


def build_analysis_action_input(*, action_name: str, intent: MissionIntent) -> dict[str, Any] | None:
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
    if action_name == "retrieval.hybrid_search" and (
        "read_business_profile" in intent.requested_outcomes or "review_business_income" in intent.requested_outcomes
    ):
        return {
            "query": "Ajenda products services target customers differentiators approved business profile",
            "limit": min(max(limit, 5), 20),
        }
    if action_name == "record.search":
        return {
            "record_type": "account",
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

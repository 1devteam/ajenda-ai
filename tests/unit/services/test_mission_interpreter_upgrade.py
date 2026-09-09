"""Coherent interpreter upgrade invariants (history, calendar, draft recipient, deps)."""

import pytest

from backend.services.mission_composition.capability_resolver import route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.proposal_store import load_recent_failure_context


@pytest.mark.parametrize(
    ("phrase", "outcome"),
    [
        ("merge records", "update_crm"),
        ("advance the deal", "update_crm"),
        ("segment accounts", "qualify_prospects"),
        ("prepare sequence", "prepare_outreach"),
        ("vertical research", "research_prospects"),
    ],
)
def test_revops_vocabulary_normalizes_to_canonical_outcome(phrase: str, outcome: str) -> None:
    assert outcome in interpret_instruction(f"Please {phrase} for this mission").requested_outcomes


def test_calendar_day_query_not_quantity() -> None:
    intent = interpret_instruction("what do i have scheduled for july 28 2026 in my google calender")
    assert intent.requested_outcomes == ["read_calendar"]
    assert intent.requested_quantity is None
    assert intent.interpretation_ready is True
    assert route_jobs_for_intent(intent)[0].job_key == "ops.calendar_briefing"


def test_draft_to_email_does_not_expand_prospect_discovery() -> None:
    intent = interpret_instruction("Draft an introduction email to bob@acme.com about roofing. Do not send.")
    assert intent.requested_outcomes == ["prepare_outreach"]
    assert intent.has_recipient_context() is True
    keys = [j.job_key for j in route_jobs_for_intent(intent)]
    assert keys == ["email.prepare_outreach"]
    assert "research.discover_prospects" not in keys


def test_tenant_chronology_escalation_disabled() -> None:
    assert load_recent_failure_context(tenant_id="t1", db=None) is None


def test_no_send_removes_send_outcome() -> None:
    intent = interpret_instruction(
        "Find three roofing companies in Austin Texas and send emails. Do not send anything."
    )
    assert "send_outreach" not in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"


def test_raw_and_normalized_preserved() -> None:
    raw = "  Find three roofing companies in Austin  "
    intent = interpret_instruction(raw)
    assert intent.raw_instruction == raw
    assert intent.normalized_instruction.strip()
    assert intent.normalized_instruction != ""  # normalized form stored separately


def test_typed_dependencies_compile_to_graph_edges() -> None:
    from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
    from backend.services.mission_composition.plan_compiler import compile_planned_steps, compile_task_graph_preview
    from backend.services.operating_charter import default_operating_charter

    intent = interpret_instruction(
        "Research three roofing companies in Austin, identify strong prospects, "
        "draft personalized introductions. Do not send."
    )
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"hubspot"},
    )
    steps = compile_planned_steps(selections, intent=intent)
    graph = compile_task_graph_preview(steps)
    assert any(step.depends_on for step in steps)
    assert graph.get("edges")


def test_explicit_email_recipient_bound_in_draft_input() -> None:
    from backend.services.mission_composition.action_inputs import build_action_input

    intent = interpret_instruction("Draft an introduction email to bob@acme.com about roofing. Do not send.")
    payload = build_action_input(action_name="gtm.email_draft", intent=intent)
    assert payload["recipient"] == "bob@acme.com"
    assert payload["context"]["binding_required"] is False


def test_schedule_meeting_does_not_map_to_calendar_read() -> None:
    intent = interpret_instruction("Schedule a meeting with Bob tomorrow")
    assert "read_calendar" not in intent.requested_outcomes
    assert any(c.field == "calendar_write" for c in intent.ambiguity)


def test_crm_negation_suppresses_update_crm() -> None:
    intent = interpret_instruction("Find three roofing companies in Austin, but don't add them to contacts")
    assert "research_prospects" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes
    assert "gtm.crm_upsert" in intent.forbidden_outcomes


def test_add_to_contacts_expands_research_dependency() -> None:
    from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
    from backend.services.mission_composition.plan_compiler import compile_planned_steps
    from backend.services.operating_charter import default_operating_charter

    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    assert "update_crm" in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert "research.discover_prospects" in {j.job_key for j in jobs}
    assert "crm.pipeline_maintenance" in {j.job_key for j in jobs}
    selections, _ = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"hubspot"},
    )
    steps = compile_planned_steps(selections, intent=intent)
    crm_steps = [s for s in steps if s.job_key == "crm.pipeline_maintenance"]
    assert crm_steps
    assert crm_steps[0].depends_on

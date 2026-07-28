"""Coherent interpreter upgrade invariants (history, calendar, draft recipient, deps)."""

from backend.services.mission_composition.capability_resolver import route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.proposal_store import load_recent_failure_context


def test_calendar_day_query_not_quantity() -> None:
    intent = interpret_instruction(
        "what do i have scheduled for july 28 2026 in my google calender"
    )
    assert intent.requested_outcomes == ["read_calendar"]
    assert intent.requested_quantity is None
    assert intent.interpretation_ready is True
    assert route_jobs_for_intent(intent)[0].job_key == "ops.calendar_briefing"


def test_draft_to_email_does_not_expand_prospect_discovery() -> None:
    intent = interpret_instruction(
        "Draft an introduction email to bob@acme.com about roofing. Do not send."
    )
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

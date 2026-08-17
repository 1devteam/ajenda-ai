"""Contact-info asks compile to observe, not simulated enrich."""

from __future__ import annotations

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.plan_compiler import compile_planned_steps
from backend.services.operating_charter import default_operating_charter
from backend.services.tools.schemas import SideEffectClass


def test_fixture_contact_info_compiles_to_observe_not_enrich() -> None:
    intent = interpret_instruction(
        "research businesses in nw arkansas area that specialize in cleaning "
        "hazardous waste return the contact info for at least five"
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "observe_contacts" in intent.requested_outcomes
    assert "enrich_contacts" not in intent.requested_outcomes
    assert "qualify_prospects" not in intent.requested_outcomes
    assert intent.requested_quantity == 5

    jobs = route_jobs_for_intent(intent)
    keys = {job.job_key for job in jobs}
    assert "research.discover_prospects" in keys
    assert "research.observe_sources" in keys
    assert "intelligence.retrieve_knowledge" in keys
    assert "intelligence.advise_next" in keys
    assert "gtm.enrich_contacts" not in keys
    assert "sales.qualify_prospects" not in keys

    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    actions = [step.action_name for step in steps]
    assert "web.research" in actions
    assert "research.observe_contacts" in actions
    assert "knowledge.retrieve_current" in actions
    assert "decision.recommend_next_action" in actions
    assert "gtm.lead_enrich" not in actions
    assert "sales.qualify" not in actions
    assert "gtm.email_send" not in actions
    assert not any(
        SideEffectClass(selection.side_effect_class).value in {"external_send", "external_write", "external_publish"}
        for selection in selections
        if selection.selection_status == "selected"
    )


def test_qualify_and_draft_is_sdr_path() -> None:
    intent = interpret_instruction(
        "Qualify these observed contacts and draft personalized introductions. Do not send."
    )
    jobs = route_jobs_for_intent(intent)
    keys = {job.job_key for job in jobs}
    assert "sales.qualify_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" not in keys


def test_explicit_enrich_still_selects_enrich() -> None:
    intent = interpret_instruction("enrich these leads")
    assert "enrich_contacts" in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert "gtm.enrich_contacts" in {job.job_key for job in jobs}


def test_advise_input_does_not_invent_contacts() -> None:
    intent = interpret_instruction("collect contact info for five companies")
    payload = build_action_input(action_name="decision.recommend_next_action", intent=intent)
    assert "Do not invent contact emails or phone numbers" in payload["constraints"]
    assert all("contact@" not in str(option) for option in payload["options"])


def test_observe_action_input_requires_binding() -> None:
    intent = interpret_instruction("collect contact info for five companies")
    payload = build_action_input(action_name="research.observe_contacts", intent=intent)
    assert payload["binding_required"] is True
    assert payload["requested_quantity"] == 5
    assert payload["prospects"] == []

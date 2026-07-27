"""Interpreter maps natural contacts language to enrich + CRM outcomes."""

from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_add_to_contacts_and_collect_info_are_recognized() -> None:
    intent = interpret_instruction(
        "find three roofing companies in the fayetteville Arkansas area "
        "collect contact info for each and add them to contacts"
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "enrich_contacts" in intent.requested_outcomes
    assert "update_crm" in intent.requested_outcomes
    assert intent.requested_quantity == 3
    assert intent.unmatched_material_clauses == []
    assert intent.coverage_score >= 0.99
    assert intent.ambiguity == []
    assert intent.target_entities
    assert intent.target_entities[0].industry == "roofing"


def test_save_to_crm_contacts_phrase() -> None:
    intent = interpret_instruction(
        "Find three roofing companies in Fayetteville Arkansas, "
        "collect contact details for each, and save them to CRM contacts. Do not send emails."
    )
    assert "update_crm" in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"

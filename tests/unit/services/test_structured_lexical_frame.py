from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.interpretation.lexical import classify_lexical_frame


def test_internal_crm_read_is_classified_without_authority() -> None:
    frame = classify_lexical_frame("Read records from Ajenda's internal CRM")

    assert frame.verb == "read"
    assert frame.source == "internal_crm"
    assert frame.entity == "records"
    assert frame.operation == "read"
    assert frame.internal_crm_read is True


def test_structured_frame_is_observable_but_does_not_select_actions() -> None:
    intent = interpret_instruction("Read records from Ajenda's internal CRM", spelling_enabled=False)

    assert "structured_lexical_frame" in intent.components_active
    assert "read_crm" in intent.requested_outcomes
    assert not any("action" in outcome for outcome in intent.requested_outcomes)

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_google_calendar_day_query_is_read_calendar_not_quantity() -> None:
    intent = interpret_instruction("what do i have scheduled for july 28 2026 in my google calender")
    assert intent.requested_outcomes == ["read_calendar"]
    assert intent.requested_quantity is None
    assert intent.unmatched_material_clauses == []
    assert intent.ambiguity == []
    payload = build_action_input(action_name="google_calendar.events_read", intent=intent)
    assert payload["start"] == "2026-07-28T00:00:00Z"
    assert payload["end"] == "2026-07-29T00:00:00Z"

from __future__ import annotations

from backend.services.mission_composition import intent_interpreter


FAILING_SAAS_MISSION = (
    "Find 10 SaaS companies in Austin, Texas that could be good prospects for Ajenda AI. "
    "Research and qualify each company based on what it sells, whether it uses AI or automated software, "
    "and whether Ajenda AI could help the company manage those systems safely and consistently. "
    "For each prospect, provide the company name, website, a short description of what it sells, "
    "the evidence used to qualify it, why Ajenda AI may be relevant, and a qualification score from 1 to 5."
)


def test_descriptive_conjunctions_do_not_become_standalone_clauses() -> None:
    clauses = intent_interpreter._segment_clauses(
        "Qualify prospects based on governance, oversight, auditability, and compliance, "
        "and whether systems are managed safely and consistently."
    )

    assert "consistently" not in clauses
    assert "oversight" not in clauses
    assert "auditability" not in clauses
    assert any("safely and consistently" in clause for clause in clauses)
    assert any("governance, oversight, auditability, and compliance" in clause for clause in clauses)


def test_imperative_chaining_still_creates_independent_clauses() -> None:
    clauses = intent_interpreter._segment_clauses(
        "Research prospects, qualify them, and send the approved email."
    )

    assert clauses == ["Research prospects", "qualify them", "send the approved email"]


def test_unsupported_external_effect_after_conjunction_stays_fail_closed() -> None:
    instruction = "Research three roofing companies in Austin and fax each of them a signed purchase order."
    clauses = intent_interpreter._segment_clauses(instruction)

    assert clauses == [
        "Research three roofing companies in Austin",
        "fax each of them a signed purchase order",
    ]

    intent = intent_interpreter.interpret_instruction(
        instruction,
        spelling_enabled=False,
        fuzzy_enabled=False,
    )
    assert intent.unmatched_material_clauses
    assert any("fax" in clause.text.lower() for clause in intent.unmatched_material_clauses)
    assert any(item.field == "clause_coverage" for item in intent.ambiguity)


def test_live_saas_mission_no_longer_fails_clause_coverage() -> None:
    intent = intent_interpreter.interpret_instruction(
        FAILING_SAAS_MISSION,
        spelling_enabled=False,
        fuzzy_enabled=False,
    )

    assert "research_prospects" in intent.requested_outcomes
    assert "qualify_prospects" in intent.requested_outcomes
    assert intent.requested_quantity == 10
    assert not intent.unmatched_material_clauses
    assert not any(item.field == "clause_coverage" for item in intent.ambiguity)


def test_external_send_remains_material_and_recognized() -> None:
    intent = intent_interpreter.interpret_instruction(
        "Find 3 SaaS companies in Austin, qualify them, and send the approved email.",
        spelling_enabled=False,
        fuzzy_enabled=False,
    )

    assert "send_outreach" in intent.requested_outcomes
    send_clauses = [
        clause for clause in intent.interpreted_clauses if "send" in clause.text.lower()
    ]
    assert send_clauses
    assert all(clause.material and clause.status == "recognized" for clause in send_clauses)

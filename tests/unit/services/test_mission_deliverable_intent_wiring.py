import pytest
from pydantic import ValidationError

from backend.services.mission_composition.contracts import MissionIntent
from backend.services.mission_composition.deliverable_contract import (
    DeliverableFieldRequirement,
    DeliverableRequest,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction


SAAS_DELIVERABLE_PROMPT = """Find 10 SaaS companies in Austin, Texas that could be good prospects for Ajenda AI. Research and qualify each company based on what it sells, whether it uses AI or automated software, and whether Ajenda AI could help the company manage those systems safely and consistently.

For each prospect, provide the company name, website, a short description of what it sells, the evidence used to qualify it, why Ajenda AI may be relevant, and a qualification score from 1 to 5."""


def test_interpreter_exposes_typed_deliverable_request_for_supported_prompt() -> None:
    intent = interpret_instruction(
        SAAS_DELIVERABLE_PROMPT,
        spelling_enabled=False,
        fuzzy_enabled=False,
    )

    request = intent.deliverable_request
    assert request is not None
    assert request.scope == "per_prospect"
    assert [field.field_key for field in request.fields] == [
        "company_name",
        "website",
        "product_description",
        "qualification_evidence",
        "ajenda_relevance",
        "qualification_score",
    ]
    assert request.score_min == 1
    assert request.score_max == 5
    assert request.fully_understood is True
    assert request.grants_execution_authority is False
    assert intent.interpretation_ready is True
    assert not any(item.field == "clause_coverage" for item in intent.ambiguity)


def test_mission_intent_rejects_forged_deliverable_request() -> None:
    forged = DeliverableRequest(
        scope="mission",
        fields=(
            DeliverableFieldRequirement(
                field_key="company_name",
                source_text="company name",
            ),
        ),
    )

    with pytest.raises(ValidationError, match="deliverable_request must be derived from raw_instruction"):
        MissionIntent(
            raw_instruction="Research three roofing companies in Austin.",
            objective="Research three roofing companies in Austin.",
            deliverable_request=forged,
        )


def test_unknown_deliverable_field_stays_unresolved_and_fail_closed() -> None:
    intent = interpret_instruction(
        "Research three roofing companies in Austin. Return the company name, website, and lunar risk index.",
        spelling_enabled=False,
        fuzzy_enabled=False,
    )

    request = intent.deliverable_request
    assert request is not None
    assert request.unresolved_items == ("lunar risk index",)
    assert request.fully_understood is False
    assert intent.interpretation_ready is False
    assert any(item.field == "clause_coverage" for item in intent.ambiguity)

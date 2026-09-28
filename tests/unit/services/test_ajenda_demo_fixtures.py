from __future__ import annotations

from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID
from backend.services.ajenda_demo_fixtures import (
    AJENDA_DEMO_PROFILE_FACTS,
    build_in_memory_demo_records,
    supplemental_demo_records,
)


def test_demo_profile_facts_center_ajenda_ai() -> None:
    assert AJENDA_DEMO_PROFILE_FACTS["business_name"] == {"value": "Ajenda AI"}
    assert "ajenda.ai" in str(AJENDA_DEMO_PROFILE_FACTS["website"])


def test_in_memory_demo_records_include_profile_account_and_prospect_pipeline() -> None:
    records = build_in_memory_demo_records()
    assert PROFILE_ACCOUNT_RECORD_ID in records["account"]
    assert records["account"][PROFILE_ACCOUNT_RECORD_ID]["name"] == "Ajenda AI"
    assert "acct-prospect-1" in records["account"]
    assert "opp-demo-1" in supplemental_demo_records()["opportunity"]


def test_supplemental_records_include_professional_services_fixture_scope() -> None:
    accounts = supplemental_demo_records()["account"]
    matches = [item for item in accounts.values() if item.get("industry") == "professional services"]
    assert len(matches) == 3
    assert {item.get("location") for item in matches} == {"Austin"}

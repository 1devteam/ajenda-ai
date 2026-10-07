from __future__ import annotations

from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID
from backend.services.business_profile.categories import missing_profile_categories, profile_category_for_field
from backend.services.business_profile.record_sync import (
    build_profile_account_record,
    build_profile_contact_record,
)


def test_build_profile_account_record_maps_identity_fields() -> None:
    record = build_profile_account_record(
        approved_facts={
            "business_name": {"value": "Austin Roofing Co."},
            "website": {"value": "https://www.acmeroofing.com"},
            "service_area": {"value": "Austin metro"},
            "target_customers": {"items": ["Homeowners"]},
            "products_services": {"items": ["Roof inspection"]},
        }
    )
    assert record is not None
    assert record["id"] == PROFILE_ACCOUNT_RECORD_ID
    assert record["name"] == "Austin Roofing Co."
    assert record["website"] == "https://www.acmeroofing.com"
    assert record["service_area"] == "Austin metro"
    assert record["target_customers"] == ["Homeowners"]
    assert record["products_services"] == ["Roof inspection"]
    assert record["profile_sync"] is True


def test_build_profile_contact_record_maps_contact_fields() -> None:
    record = build_profile_contact_record(
        approved_facts={
            "primary_contact_name": {"value": "Jordan Lee"},
            "contact_email": {"value": "hello@acmeroofing.com"},
            "contact_phone": {"value": "+1 512 555 0100"},
        }
    )
    assert record is not None
    assert record["id"] == PROFILE_CONTACT_RECORD_ID
    assert record["account_id"] == PROFILE_ACCOUNT_RECORD_ID
    assert record["name"] == "Jordan Lee"
    assert record["email"] == "hello@acmeroofing.com"
    assert record["phone"] == "+1 512 555 0100"


def test_build_profile_records_return_none_without_identity_facts() -> None:
    assert build_profile_account_record(approved_facts={}) is None
    assert build_profile_contact_record(approved_facts={}) is None


def test_profile_brief_exposes_business_first_categories() -> None:
    from backend.services.business_profile.record_sync import build_profile_brief

    brief = build_profile_brief(
        approved_facts={
            "business_name": {"value": "Acme"},
            "target_customers": {"items": ["Operators"]},
            "products_services": {"items": ["Audits"]},
        }
    )
    assert brief["categories"] == {
        "company": ["business_name"],
        "market": ["target_customers"],
        "offer": ["products_services"],
    }
    assert profile_category_for_field("customer_polls") == "customer_insight"


def test_missing_profile_categories_is_fail_closed_for_empty_facts() -> None:
    assert missing_profile_categories({}, ("company", "growth")) == ["company", "growth"]
    assert (
        missing_profile_categories(
            {"business_name": {"value": "Acme"}, "growth_goals": {"value": "Grow"}},
            ("company", "growth"),
        )
        == []
    )

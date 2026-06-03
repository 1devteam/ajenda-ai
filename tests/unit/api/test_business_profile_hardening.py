from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.api.routes.business_profile import (
    BusinessProfileFactUpsert,
    BusinessProfileSuggestionCreate,
    _history_to_read,
    _normalize_category,
)
from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion


def test_business_profile_fact_payload_rejects_oversized_json() -> None:
    with pytest.raises(ValidationError):
        BusinessProfileFactUpsert(approved_fact={"value": "x" * 17_000})


def test_business_profile_fact_payload_rejects_excessive_depth() -> None:
    with pytest.raises(ValidationError):
        BusinessProfileFactUpsert(
            approved_fact={"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "too deep"}}}}}}}}}
        )


def test_suggestion_category_is_canonicalized_for_case_and_space_collisions() -> None:
    suggestion = BusinessProfileSuggestionCreate(
        suggested_category=" Service Area ",
        suggested_fact={"value": "Dallas"},
        rationale="User confirmed this reusable fact.",
    )

    assert suggestion.suggested_category == "service_area"
    assert _normalize_category(" Service Area ") == "service_area"


def test_suggestion_mission_id_must_match_source_context_mission_id() -> None:
    with pytest.raises(ValidationError):
        BusinessProfileSuggestionCreate(
            mission_id=uuid.uuid4(),
            suggested_category="service_area",
            suggested_fact={"value": "Dallas"},
            rationale="User confirmed this reusable fact.",
            source_context={"mission_id": str(uuid.uuid4())},
        )


def test_history_read_model_includes_profile_provenance_and_suggestion_decision() -> None:
    tenant_id = str(uuid.uuid4())
    profile_id = uuid.uuid4()
    suggestion_id = uuid.uuid4()
    now = datetime(2026, 6, 3, tzinfo=UTC)
    profile = BusinessProfile(
        tenant_id=tenant_id,
        approved_facts={"business_name": {"value": "Ajenda"}},
        provenance={
            "business_name": {
                "actor_id": "user-1",
                "updated_at": now.isoformat(),
                "decision": "direct_update",
            }
        },
    )
    profile.id = profile_id
    profile.created_at = now
    profile.updated_at = now
    suggestion = BusinessProfileSuggestion(
        tenant_id=tenant_id,
        suggested_category="service_area",
        suggested_fact={"value": "Dallas"},
        rationale="User stated this service area should be reused.",
        status="declined",
        resolution={"actor_id": "user-2", "decision": "declined"},
    )
    suggestion.id = suggestion_id
    suggestion.created_at = now
    suggestion.resolved_at = now

    result = _history_to_read(tenant_id=tenant_id, profile=profile, suggestions=[suggestion])

    assert result.profile.profile_id == profile_id
    assert {event.event_type for event in result.events} == {"approved_fact", "suggestion"}
    assert result.events[0].category == "business_name"
    assert result.events[1].suggestion_id == suggestion_id

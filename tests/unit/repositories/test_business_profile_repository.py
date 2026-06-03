from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion
from backend.repositories.business_profile_repository import BusinessProfileRepository


def _profile(*, tenant_id: str = "tenant-a") -> BusinessProfile:
    return BusinessProfile(
        tenant_id=tenant_id,
        approved_facts={},
        provenance={},
    )


def _suggestion(*, tenant_id: str = "tenant-a", category: str = "service_area") -> BusinessProfileSuggestion:
    return BusinessProfileSuggestion(
        tenant_id=tenant_id,
        suggested_category=category,
        suggested_fact={"value": "Dallas"},
        rationale="User stated this service area should be reused.",
        source_context={"mission_id": str(uuid.uuid4())},
    )


RESOLVED_SUGGESTION_STATUSES = ("approved", "edited", "declined", "dismissed")


def test_add_profile_flushes_and_refreshes() -> None:
    profile = _profile()
    session = MagicMock()

    result = BusinessProfileRepository(session).add_profile(profile)

    assert result is profile
    session.add.assert_called_once_with(profile)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(profile)


def test_get_profile_for_tenant_uses_tenant_scope() -> None:
    tenant_id = str(uuid.uuid4())
    profile_id = uuid.uuid4()
    profile = _profile(tenant_id=tenant_id)
    session = MagicMock()
    session.scalar.return_value = profile

    result = BusinessProfileRepository(session).get_profile_for_tenant(profile_id=profile_id, tenant_id=tenant_id)

    assert result is profile
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "business_profiles.id" in compiled
    assert "business_profiles.tenant_id" in compiled
    assert tenant_id in compiled


def test_get_active_profile_for_tenant_filters_active_status() -> None:
    tenant_id = str(uuid.uuid4())
    profile = _profile(tenant_id=tenant_id)
    session = MagicMock()
    session.scalar.return_value = profile

    result = BusinessProfileRepository(session).get_active_profile_for_tenant(tenant_id=tenant_id)

    assert result is profile
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "business_profiles.tenant_id" in compiled
    assert "business_profiles.status" in compiled
    assert "active" in compiled
    assert tenant_id in compiled


def test_add_suggestion_flushes_and_refreshes() -> None:
    suggestion = _suggestion()
    session = MagicMock()

    result = BusinessProfileRepository(session).add_suggestion(suggestion)

    assert result is suggestion
    session.add.assert_called_once_with(suggestion)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(suggestion)


def test_get_suggestion_for_tenant_uses_tenant_scope() -> None:
    tenant_id = str(uuid.uuid4())
    suggestion_id = uuid.uuid4()
    suggestion = _suggestion(tenant_id=tenant_id)
    session = MagicMock()
    session.scalar.return_value = suggestion

    result = BusinessProfileRepository(session).get_suggestion_for_tenant(
        suggestion_id=suggestion_id,
        tenant_id=tenant_id,
    )

    assert result is suggestion
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "business_profile_suggestions.id" in compiled
    assert "business_profile_suggestions.tenant_id" in compiled
    assert tenant_id in compiled


def test_list_suggestions_for_tenant_filters_tenant_and_optional_status() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = BusinessProfileRepository(session).list_suggestions_for_tenant(
        tenant_id=tenant_id,
        status="pending",
    )

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "business_profile_suggestions.tenant_id" in compiled
    assert "business_profile_suggestions.status" in compiled
    assert "pending" in compiled
    assert tenant_id in compiled


def test_pending_suggestion_does_not_mutate_profile_truth_when_added() -> None:
    profile = _profile()
    suggestion = _suggestion()
    session = MagicMock()
    repo = BusinessProfileRepository(session)

    repo.add_suggestion(suggestion)

    assert profile.approved_facts == {}
    assert profile.provenance == {}


def test_approve_suggestion_as_is_writes_approved_fact_and_resolution() -> None:
    profile = _profile()
    suggestion = _suggestion(category="service_area")
    suggestion.id = uuid.uuid4()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    updated_profile, updated_suggestion = BusinessProfileRepository(session).approve_suggestion_as_is(
        profile=profile,
        suggestion=suggestion,
        resolved_at=resolved_at,
        actor_id="user-1",
    )

    assert updated_profile.approved_facts["service_area"] == {"value": "Dallas"}
    assert updated_profile.provenance["service_area"]["actor_id"] == "user-1"
    assert updated_profile.provenance["service_area"]["decision"] == "approved"
    assert updated_suggestion.status == "approved"
    assert updated_suggestion.resolution["approved_fact"] == {"value": "Dallas"}
    session.flush.assert_called_once()


def test_approve_suggestion_preserves_superseded_profile_fact_and_provenance() -> None:
    previous_provenance = {
        "actor_id": "user-old",
        "suggestion_id": str(uuid.uuid4()),
        "resolved_at": "2026-06-02T00:00:00+00:00",
        "decision": "approved",
    }
    profile = _profile()
    profile.approved_facts = {"service_area": {"value": "Dallas"}}
    profile.provenance = {"service_area": previous_provenance}
    suggestion = _suggestion(category="service_area")
    suggestion.id = uuid.uuid4()
    suggestion.suggested_fact = {"value": "Fort Worth"}
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    updated_profile, updated_suggestion = BusinessProfileRepository(session).approve_suggestion_as_is(
        profile=profile,
        suggestion=suggestion,
        resolved_at=resolved_at,
        actor_id="user-1",
    )

    assert updated_profile.approved_facts["service_area"] == {"value": "Fort Worth"}
    assert updated_suggestion.resolution["superseded_fact"] == {"value": "Dallas"}
    assert updated_suggestion.resolution["superseded_provenance"] == previous_provenance


def test_approve_suggestion_with_edit_writes_edited_fact_not_original() -> None:
    profile = _profile()
    suggestion = _suggestion(category="service_area")
    suggestion.id = uuid.uuid4()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    updated_profile, updated_suggestion = BusinessProfileRepository(session).approve_suggestion_with_edit(
        profile=profile,
        suggestion=suggestion,
        approved_fact={"value": "Fort Worth"},
        resolved_at=resolved_at,
        actor_id="user-1",
    )

    assert updated_profile.approved_facts["service_area"] == {"value": "Fort Worth"}
    assert updated_profile.approved_facts["service_area"] != suggestion.suggested_fact
    assert updated_profile.provenance["service_area"]["decision"] == "edited"
    assert updated_suggestion.status == "edited"
    assert updated_suggestion.resolution["approved_fact"] == {"value": "Fort Worth"}


def test_decline_suggestion_does_not_write_approved_profile_fact() -> None:
    profile = _profile()
    suggestion = _suggestion()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    result = BusinessProfileRepository(session).decline_suggestion(
        suggestion=suggestion,
        resolved_at=resolved_at,
        actor_id="user-1",
    )

    assert result.status == "declined"
    assert result.resolution["decision"] == "declined"
    assert profile.approved_facts == {}


def test_dismiss_suggestion_does_not_write_approved_profile_fact() -> None:
    profile = _profile()
    suggestion = _suggestion()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    result = BusinessProfileRepository(session).dismiss_suggestion(
        suggestion=suggestion,
        resolved_at=resolved_at,
        actor_id="user-1",
    )

    assert result.status == "dismissed"
    assert result.resolution["decision"] == "dismissed"
    assert profile.approved_facts == {}


def test_resolved_suggestions_cannot_be_approved_again() -> None:
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)

    for status in RESOLVED_SUGGESTION_STATUSES:
        profile = _profile()
        suggestion = _suggestion(category="service_area")
        suggestion.status = status
        session = MagicMock()

        try:
            BusinessProfileRepository(session).approve_suggestion_as_is(
                profile=profile,
                suggestion=suggestion,
                resolved_at=resolved_at,
                actor_id="user-1",
            )
        except ValueError as exc:
            assert str(exc) == "only pending business profile suggestions can be resolved"
        else:
            raise AssertionError(f"expected {status} suggestion approval to fail")

        assert profile.approved_facts == {}
        session.add.assert_not_called()
        session.flush.assert_not_called()


def test_resolved_suggestions_cannot_be_declined_or_dismissed_again() -> None:
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)

    for status in RESOLVED_SUGGESTION_STATUSES:
        for resolver_name in ("decline_suggestion", "dismiss_suggestion"):
            suggestion = _suggestion(category="service_area")
            suggestion.status = status
            session = MagicMock()
            resolver = getattr(BusinessProfileRepository(session), resolver_name)

            try:
                resolver(
                    suggestion=suggestion,
                    resolved_at=resolved_at,
                    actor_id="user-1",
                )
            except ValueError as exc:
                assert str(exc) == "only pending business profile suggestions can be resolved"
            else:
                raise AssertionError(f"expected {status} suggestion {resolver_name} to fail")

            session.add.assert_not_called()
            session.flush.assert_not_called()


def test_approve_suggestion_rejects_cross_tenant_profile_mutation() -> None:
    profile = _profile(tenant_id="tenant-a")
    suggestion = _suggestion(tenant_id="tenant-b")
    suggestion.id = uuid.uuid4()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    try:
        BusinessProfileRepository(session).approve_suggestion_as_is(
            profile=profile,
            suggestion=suggestion,
            resolved_at=resolved_at,
            actor_id="user-1",
        )
    except ValueError as exc:
        assert str(exc) == "business profile suggestion tenant does not match profile tenant"
    else:
        raise AssertionError("expected cross-tenant approval to fail")

    assert profile.approved_facts == {}
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_approve_suggestion_rejects_wrong_profile_id() -> None:
    profile = _profile(tenant_id="tenant-a")
    profile.id = uuid.uuid4()
    suggestion = _suggestion(tenant_id="tenant-a")
    suggestion.id = uuid.uuid4()
    suggestion.profile_id = uuid.uuid4()
    resolved_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    try:
        BusinessProfileRepository(session).approve_suggestion_as_is(
            profile=profile,
            suggestion=suggestion,
            resolved_at=resolved_at,
            actor_id="user-1",
        )
    except ValueError as exc:
        assert str(exc) == "business profile suggestion does not belong to profile"
    else:
        raise AssertionError("expected wrong-profile approval to fail")

    assert profile.approved_facts == {}
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_upsert_approved_fact_writes_explicit_fact_and_provenance_metadata() -> None:
    profile = _profile()
    updated_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    result = BusinessProfileRepository(session).upsert_approved_fact(
        profile=profile,
        category="business_name",
        approved_fact={"value": "Ajenda AI"},
        actor_id="user-1",
        updated_at=updated_at,
        provenance_metadata={"source": "onboarding"},
    )

    assert result.approved_facts["business_name"] == {"value": "Ajenda AI"}
    assert result.provenance["business_name"]["actor_id"] == "user-1"
    assert result.provenance["business_name"]["decision"] == "direct_update"
    assert result.provenance["business_name"]["metadata"] == {"source": "onboarding"}
    session.flush.assert_called_once()


def test_upsert_approved_fact_preserves_superseded_fact_and_provenance() -> None:
    previous_provenance = {"actor_id": "user-old", "decision": "direct_update"}
    profile = _profile()
    profile.approved_facts = {"business_name": {"value": "Old Name"}}
    profile.provenance = {"business_name": previous_provenance}
    updated_at = datetime(2026, 6, 3, tzinfo=UTC)
    session = MagicMock()

    result = BusinessProfileRepository(session).upsert_approved_fact(
        profile=profile,
        category="business_name",
        approved_fact={"value": "New Name"},
        actor_id="user-1",
        updated_at=updated_at,
    )

    assert result.approved_facts["business_name"] == {"value": "New Name"}
    assert result.provenance["business_name"]["superseded_fact"] == {"value": "Old Name"}
    assert result.provenance["business_name"]["superseded_provenance"] == previous_provenance


def test_upsert_approved_fact_rejects_non_active_profile() -> None:
    profile = _profile()
    profile.status = "archived"
    session = MagicMock()

    try:
        BusinessProfileRepository(session).upsert_approved_fact(
            profile=profile,
            category="business_name",
            approved_fact={"value": "Ajenda"},
            actor_id="user-1",
            updated_at=datetime(2026, 6, 3, tzinfo=UTC),
        )
    except ValueError as exc:
        assert str(exc) == "only active business profiles can be updated"
    else:
        raise AssertionError("expected archived profile update to fail")

    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_get_or_create_active_profile_returns_existing_profile_after_unique_race() -> None:
    from sqlalchemy.exc import IntegrityError

    existing = _profile()
    existing.tenant_id = "tenant-race"
    session = MagicMock()
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate active profile"))
    session.scalar.side_effect = [None, existing]

    result = BusinessProfileRepository(session).get_or_create_active_profile(tenant_id="tenant-race", schema_version=1)

    assert result is existing
    session.rollback.assert_not_called()
    session.begin_nested.assert_called_once()
    assert session.scalar.call_count == 2

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services.onboarding_service import OnboardingService


def _service(facts: dict[str, object], *, permissions: tuple[str, ...] = ("credentials:manage",)):
    session = MagicMock()
    state = SimpleNamespace(
        setup_version=1,
        completed=False,
        completed_at=None,
        completed_by_member_id=None,
        updated_at=None,
    )
    repo = MagicMock()
    repo.get_or_create_state.return_value = state
    repo.member_for_subject.return_value = SimpleNamespace(id=uuid.uuid4())
    repo.get_preference.return_value = None
    service = OnboardingService(session)
    service._repo = repo
    principal = SimpleNamespace(subject_id=f"user:{uuid.uuid4()}", permissions=permissions)
    profile = SimpleNamespace(approved_facts=facts)
    return service, session, repo, principal, profile, state


def test_read_is_incomplete_for_empty_nested_profile_values() -> None:
    service, _session, repo, principal, profile, _state = _service(
        {"business_name": {"value": ""}, "contact_email": {"value": ""}}
    )
    with (
        patch("backend.services.onboarding_service.BusinessProfileRepository") as profile_repo,
        patch.object(
            service,
            "_connections",
            return_value={"gmail": False, "google_calendar": False, "google_contacts": False, "google_docs": False},
        ),
    ):
        profile_repo.return_value.get_active_profile_for_tenant.return_value = profile
        snapshot = service.read(tenant_id=uuid.uuid4(), principal=principal)
    assert snapshot.completed is False
    assert snapshot.company_profile_ready is False
    assert repo.get_or_create_state.call_args.kwargs["legacy_completed"] is False


def test_complete_requires_operating_preferences() -> None:
    service, _session, _repo, principal, profile, _state = _service(
        {"business_name": {"value": "Ajenda"}, "contact_email": {"value": "owner@example.com"}}
    )
    with patch("backend.services.onboarding_service.BusinessProfileRepository") as profile_repo:
        profile_repo.return_value.get_active_profile_for_tenant.return_value = profile
        with pytest.raises(ValueError, match="operating preferences"):
            service.complete(tenant_id=uuid.uuid4(), principal=principal)

"""Real PostgreSQL proof for operating-charter revision ownership."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.tenant import Tenant
from backend.repositories.business_profile_repository import (
    BusinessProfileCharterRevisionConflict,
    BusinessProfileRepository,
)
from backend.services.operating_charter import OperatingCharter, inspect_operating_charter

pytestmark = pytest.mark.integration


def _charter(*, revision: int = 0, may_prepare: tuple[str, ...] = ("web.research",)) -> OperatingCharter:
    return OperatingCharter(
        schema_version=1,
        revision=revision,
        may_prepare=may_prepare,
        may_perform=(),
        never_do=("gtm.email_send", "gtm.social_publish", "webhook.dispatch"),
        approval_mode="none",
        escalation_email=None,
        escalation_phone=None,
        source="profile",
    )


def _session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_operating_charter_revision_conflict_is_checked_under_real_row_lock(pg_engine) -> None:
    """Two stale independent sessions cannot lose an active-charter update."""
    tenant_id = uuid.uuid4()
    setup = _session_factory(pg_engine)()
    try:
        setup.add(
            Tenant(
                id=tenant_id,
                name="Charter concurrency tenant",
                slug=f"charter-concurrency-{tenant_id.hex[:12]}",
                plan="free",
            )
        )
        setup.commit()
    finally:
        setup.close()

    first = _session_factory(pg_engine)()
    second = _session_factory(pg_engine)()
    try:
        for session in (first, second):
            activate_tenant_session(session, str(tenant_id))

        first_repo = BusinessProfileRepository(first)
        first_profile = first_repo.get_or_create_active_profile(tenant_id=str(tenant_id))
        first.commit()
        # PostgreSQL SET LOCAL expires at the preceding commit, just as it
        # does between real HTTP requests.
        activate_tenant_session(first, str(tenant_id))

        # Both independent sessions observe the same revision before either
        # update. The second must re-read a locked row, not trust this stale
        # identity-map snapshot, when it attempts its write.
        first_profile = first_repo.get_active_profile_for_tenant(tenant_id=str(tenant_id))
        second_profile = BusinessProfileRepository(second).get_active_profile_for_tenant(tenant_id=str(tenant_id))
        assert first_profile is not None
        assert second_profile is not None
        assert inspect_operating_charter(approved_facts=first_profile.approved_facts).revision == 0
        assert inspect_operating_charter(approved_facts=second_profile.approved_facts).revision == 0

        first_repo.upsert_operating_charter(
            profile=first_profile,
            charter=_charter(),
            expected_revision=0,
            actor_id="first-api-session",
            updated_at=datetime.now(UTC),
        )
        first.commit()

        with pytest.raises(BusinessProfileCharterRevisionConflict) as conflict:
            BusinessProfileRepository(second).upsert_operating_charter(
                profile=second_profile,
                charter=_charter(may_prepare=("web.search",)),
                expected_revision=0,
                actor_id="second-api-session",
                updated_at=datetime.now(UTC),
            )
        assert conflict.value.expected_revision == 0
        assert conflict.value.current_revision == 1
        second.rollback()

        verify = _session_factory(pg_engine)()
        try:
            activate_tenant_session(verify, str(tenant_id))
            current = BusinessProfileRepository(verify).get_active_profile_for_tenant(tenant_id=str(tenant_id))
            assert current is not None
            state = inspect_operating_charter(approved_facts=current.approved_facts)
            assert state.status == "active"
            assert state.revision == 1
            assert state.charter is not None
            assert state.charter.may_prepare == ("web.research",)
        finally:
            verify.close()
    finally:
        first.close()
        second.close()

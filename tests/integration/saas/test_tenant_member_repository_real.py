"""Integration tests: tenant_members schema and repository."""

from __future__ import annotations

import uuid

import pytest

from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.repositories.tenant_repository import TenantRepository

pytestmark = pytest.mark.integration


def _slug() -> str:
    return f"member-repo-{uuid.uuid4().hex[:8]}"


class TestTenantMemberRepositoryReal:
    def test_create_and_lookup_owner_by_canonical_email(self, pg_session) -> None:
        tenant_repo = TenantRepository(pg_session)
        tenant = tenant_repo.create(name="Member Test Co.", slug=_slug(), plan="free")
        pg_session.flush()

        member_repo = TenantMemberRepository(pg_session)
        member = member_repo.create(
            tenant_id=tenant.id,
            email_raw="Owner@Example.COM",
            email_canonical="owner@example.com",
            status="pending_verification",
        )
        pg_session.flush()

        found = member_repo.get_owner_by_email_canonical("owner@example.com")
        assert found is not None
        assert found.id == member.id
        assert found.tenant_id == tenant.id

    def test_partial_unique_owner_email_blocks_duplicate_pending(self, pg_session) -> None:
        tenant_repo = TenantRepository(pg_session)
        tenant_a = tenant_repo.create(name="Tenant A", slug=_slug(), plan="free")
        tenant_b = tenant_repo.create(name="Tenant B", slug=_slug(), plan="free")
        pg_session.flush()

        member_repo = TenantMemberRepository(pg_session)
        member_repo.create(
            tenant_id=tenant_a.id,
            email_raw="user@example.com",
            email_canonical="user@example.com",
            status="pending_verification",
        )
        pg_session.flush()

        member_repo.create(
            tenant_id=tenant_b.id,
            email_raw="user@example.com",
            email_canonical="user@example.com",
            status="pending_verification",
        )
        with pytest.raises(Exception):
            pg_session.flush()
        pg_session.rollback()

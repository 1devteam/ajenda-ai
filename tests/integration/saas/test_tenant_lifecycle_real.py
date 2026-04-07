"""Integration tests: tenant lifecycle against a real PostgreSQL database.

These tests replace the mock-backed unit tests for TenantLifecycleService and
TenantRepository. Running against a real Postgres instance catches issues that
SQLite or MagicMock cannot surface:

  - UUID primary key handling with psycopg v3
  - JSONB column serialisation for governance event payloads
  - Unique constraint enforcement on tenant slugs
  - Atomic increment behaviour of UPDATE ... SET field = field + :amount
  - Correct billing-period isolation in TenantUsage rows
  - GovernanceEvent rows written to the governance_events table

All tests use the pg_session fixture from tests/integration/conftest.py, which
provides a real Postgres connection rolled back after each test.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.domain.governance_event import GovernanceEvent
from backend.domain.tenant import Tenant
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantRepository,
    TenantSuspendedError,
)
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tenant_lifecycle import TenantLifecycleService

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug() -> str:
    """Generate a unique slug for each test to avoid unique-constraint conflicts."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


def _provision(session, *, slug: str | None = None, plan: str = "free") -> tuple[TenantLifecycleService, uuid.UUID]:
    """Provision a tenant and return (service, tenant_id)."""
    svc = TenantLifecycleService(session)
    result = svc.provision(name="Integration Test Co.", slug=slug or _slug(), plan=plan, actor="test-runner")
    session.flush()
    return svc, result.tenant_id


# ---------------------------------------------------------------------------
# TenantRepository — CRUD against real Postgres
# ---------------------------------------------------------------------------


class TestTenantRepositoryReal:
    def test_create_and_retrieve_tenant(self, pg_session) -> None:
        """Creating a tenant must persist a retrievable row with correct fields."""
        repo = TenantRepository(pg_session)
        slug = _slug()
        tenant = repo.create(name="Acme Corp", slug=slug, plan="starter")
        pg_session.flush()

        retrieved = repo.get(tenant.id)
        assert retrieved is not None
        assert retrieved.id == tenant.id
        assert retrieved.name == "Acme Corp"
        assert retrieved.slug == slug
        assert retrieved.plan == "starter"
        assert retrieved.status == "active"
        assert retrieved.deleted_at is None

    def test_get_by_slug(self, pg_session) -> None:
        """get_by_slug must return the correct tenant."""
        repo = TenantRepository(pg_session)
        slug = _slug()
        tenant = repo.create(name="Slug Corp", slug=slug)
        pg_session.flush()

        found = repo.get_by_slug(slug)
        assert found is not None
        assert found.id == tenant.id

    def test_get_by_slug_returns_none_for_missing(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        assert repo.get_by_slug("slug-that-does-not-exist-xyz") is None

    def test_get_returns_none_for_missing_id(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        assert repo.get(uuid.uuid4()) is None

    def test_get_active_raises_for_suspended(self, pg_session) -> None:
        """get_active must raise TenantSuspendedError for a suspended tenant."""
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Suspended Co.", slug=_slug())
        pg_session.flush()
        repo.suspend(tenant.id, reason="non-payment")
        pg_session.flush()

        with pytest.raises(TenantSuspendedError):
            repo.get_active(tenant.id)

    def test_get_active_raises_for_deleted(self, pg_session) -> None:
        """get_active must raise TenantDeletedError for a soft-deleted tenant."""
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Deleted Co.", slug=_slug())
        pg_session.flush()
        repo.soft_delete(tenant.id)
        pg_session.flush()

        with pytest.raises(TenantDeletedError):
            repo.get_active(tenant.id)

    def test_get_active_raises_for_missing(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        with pytest.raises(TenantNotFoundError):
            repo.get_active(uuid.uuid4())

    def test_suspend_sets_status(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Suspend Test", slug=_slug())
        pg_session.flush()

        repo.suspend(tenant.id, reason="test-reason")
        pg_session.flush()
        pg_session.refresh(tenant)

        assert tenant.status == "suspended"

    def test_reactivate_restores_active_status(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Reactivate Test", slug=_slug())
        pg_session.flush()
        repo.suspend(tenant.id, reason="test")
        pg_session.flush()
        repo.reactivate(tenant.id)
        pg_session.flush()
        pg_session.refresh(tenant)

        assert tenant.status == "active"

    def test_soft_delete_sets_deleted_at(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Delete Test", slug=_slug())
        pg_session.flush()

        repo.soft_delete(tenant.id)
        pg_session.flush()
        pg_session.refresh(tenant)

        assert tenant.status == "deleted"
        assert tenant.deleted_at is not None

    def test_update_plan(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Plan Test", slug=_slug(), plan="free")
        pg_session.flush()

        repo.update_plan(tenant.id, new_plan="pro")
        pg_session.flush()
        pg_session.refresh(tenant)

        assert tenant.plan == "pro"

    def test_suspend_deleted_tenant_raises(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Already Deleted", slug=_slug())
        pg_session.flush()
        repo.soft_delete(tenant.id)
        pg_session.flush()

        with pytest.raises(TenantDeletedError):
            repo.suspend(tenant.id, reason="too late")

    def test_reactivate_deleted_tenant_raises(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Deleted No Reactivate", slug=_slug())
        pg_session.flush()
        repo.soft_delete(tenant.id)
        pg_session.flush()

        with pytest.raises(TenantDeletedError):
            repo.reactivate(tenant.id)


# ---------------------------------------------------------------------------
# TenantLifecycleService — full lifecycle with governance events
# ---------------------------------------------------------------------------


class TestTenantLifecycleServiceReal:
    def test_provision_creates_tenant_and_governance_event(self, pg_session) -> None:
        """provision() must persist a Tenant row AND a governance event."""
        svc = TenantLifecycleService(pg_session)
        slug = _slug()
        result = svc.provision(name="Lifecycle Corp", slug=slug, plan="starter", actor="operator-1")
        pg_session.flush()

        # Tenant row must exist
        tenant = pg_session.get(Tenant, result.tenant_id)
        assert tenant is not None
        assert tenant.slug == slug
        assert tenant.plan == "starter"
        assert tenant.status == "active"

        # Governance event must be written
        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(result.tenant_id), event_type="tenant_provisioned")
            .all()
        )
        assert len(events) == 1
        assert events[0].actor == "operator-1"
        assert events[0].payload_json["slug"] == slug

    def test_provision_duplicate_slug_raises(self, pg_session) -> None:
        """Provisioning two tenants with the same slug must raise ValueError."""
        svc = TenantLifecycleService(pg_session)
        slug = _slug()
        svc.provision(name="First Corp", slug=slug)
        pg_session.flush()

        with pytest.raises(ValueError, match="already exists"):
            svc.provision(name="Second Corp", slug=slug)

    def test_suspend_emits_governance_event(self, pg_session) -> None:
        svc, tenant_id = _provision(pg_session)
        svc.suspend(tenant_id, reason="non-payment", actor="billing-bot")
        pg_session.flush()

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant_id), event_type="tenant_suspended")
            .all()
        )
        assert len(events) == 1
        assert events[0].actor == "billing-bot"
        assert "non-payment" in events[0].payload_json["reason"]

    def test_reactivate_emits_governance_event(self, pg_session) -> None:
        svc, tenant_id = _provision(pg_session)
        svc.suspend(tenant_id, reason="test", actor="system")
        pg_session.flush()
        svc.reactivate(tenant_id, actor="operator-2")
        pg_session.flush()

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant_id), event_type="tenant_reactivated")
            .all()
        )
        assert len(events) == 1
        assert events[0].actor == "operator-2"

    def test_delete_emits_governance_event(self, pg_session) -> None:
        svc, tenant_id = _provision(pg_session)
        svc.delete(tenant_id, actor="operator-3", reason="gdpr-erasure")
        pg_session.flush()

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant_id), event_type="tenant_deleted")
            .all()
        )
        assert len(events) == 1
        assert "gdpr-erasure" in events[0].payload_json["reason"]

    def test_upgrade_plan_emits_governance_event(self, pg_session) -> None:
        svc, tenant_id = _provision(pg_session, plan="free")
        svc.upgrade_plan(tenant_id, new_plan="pro", actor="sales-team")
        pg_session.flush()

        events = (
            pg_session.query(GovernanceEvent)
            .filter_by(tenant_id=str(tenant_id), event_type="tenant_plan_changed")
            .all()
        )
        assert len(events) == 1
        assert events[0].payload_json["old_plan"] == "free"
        assert events[0].payload_json["new_plan"] == "pro"

    def test_full_lifecycle_sequence(self, pg_session) -> None:
        """Provision → suspend → reactivate → delete — all transitions must succeed."""
        svc = TenantLifecycleService(pg_session)
        slug = _slug()

        result = svc.provision(name="Full Lifecycle Co.", slug=slug, plan="free", actor="system")
        pg_session.flush()
        tenant_id = result.tenant_id

        svc.suspend(tenant_id, reason="trial-expired", actor="billing")
        pg_session.flush()

        tenant = pg_session.get(Tenant, tenant_id)
        assert tenant is not None
        assert tenant.status == "suspended"

        svc.reactivate(tenant_id, actor="support")
        pg_session.flush()
        pg_session.refresh(tenant)
        assert tenant.status == "active"

        svc.delete(tenant_id, actor="operator", reason="customer-request")
        pg_session.flush()
        pg_session.refresh(tenant)
        assert tenant.status == "deleted"
        assert tenant.deleted_at is not None


# ---------------------------------------------------------------------------
# TenantUsage — metering and quota enforcement against real Postgres
# ---------------------------------------------------------------------------


class TestTenantUsageReal:
    def _seed_plan(self, pg_session, slug: str, plan_slug: str = "free") -> uuid.UUID:
        """Create a tenant and ensure the plan row exists (seeded by migration 0006)."""
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Usage Test Co.", slug=slug, plan=plan_slug)
        pg_session.flush()
        return tenant.id

    def test_get_or_create_usage_creates_row(self, pg_session) -> None:
        """First call to get_or_create_usage must insert a TenantUsage row."""
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())

        usage = repo.get_or_create_usage(tenant_id)
        pg_session.flush()

        assert usage is not None
        assert usage.tenant_id == str(tenant_id)
        assert usage.missions_created == 0
        assert usage.tasks_created == 0

    def test_get_or_create_usage_is_idempotent(self, pg_session) -> None:
        """Calling get_or_create_usage twice must return the same row."""
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())

        usage1 = repo.get_or_create_usage(tenant_id)
        pg_session.flush()
        usage2 = repo.get_or_create_usage(tenant_id)
        pg_session.flush()

        assert usage1.id == usage2.id

    def test_increment_usage_tasks_created(self, pg_session) -> None:
        """increment_usage must atomically increase the counter."""
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())

        repo.get_or_create_usage(tenant_id)
        pg_session.flush()

        repo.increment_usage(tenant_id, field="tasks_created", amount=5)
        pg_session.flush()

        usage = repo.get_or_create_usage(tenant_id)
        assert usage.tasks_created == 5

    def test_increment_usage_missions_created(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())

        repo.get_or_create_usage(tenant_id)
        pg_session.flush()
        repo.increment_usage(tenant_id, field="missions_created", amount=3)
        pg_session.flush()

        usage = repo.get_or_create_usage(tenant_id)
        assert usage.missions_created == 3

    def test_increment_unknown_field_raises(self, pg_session) -> None:
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())
        repo.get_or_create_usage(tenant_id)
        pg_session.flush()

        with pytest.raises(ValueError, match="Unknown usage field"):
            repo.increment_usage(tenant_id, field="nonexistent_field")

    def test_billing_period_isolation(self, pg_session) -> None:
        """Usage rows for different billing periods must be independent."""
        repo = TenantRepository(pg_session)
        tenant_id = self._seed_plan(pg_session, _slug())

        period_a = date(2026, 1, 1)
        period_b = date(2026, 2, 1)

        repo.get_or_create_usage(tenant_id, billing_period=period_a)
        pg_session.flush()
        repo.increment_usage(tenant_id, field="tasks_created", amount=10, billing_period=period_a)
        pg_session.flush()

        repo.get_or_create_usage(tenant_id, billing_period=period_b)
        pg_session.flush()

        usage_a = repo.get_or_create_usage(tenant_id, billing_period=period_a)
        usage_b = repo.get_or_create_usage(tenant_id, billing_period=period_b)

        assert usage_a.tasks_created == 10
        assert usage_b.tasks_created == 0


# ---------------------------------------------------------------------------
# QuotaEnforcementService — against real Postgres + seeded plan data
# ---------------------------------------------------------------------------


class TestQuotaEnforcementReal:
    """These tests rely on the plan rows seeded by migration 0006:
      free:       max_tasks_per_month=100, max_missions_per_month=10
      starter:    max_tasks_per_month=500, max_missions_per_month=50
      pro:        max_tasks_per_month=2000, max_missions_per_month=200
      enterprise: max_tasks_per_month=-1 (unlimited)
    """

    def _make_tenant(self, pg_session, plan: str = "free") -> uuid.UUID:
        repo = TenantRepository(pg_session)
        tenant = repo.create(name="Quota Test Co.", slug=_slug(), plan=plan)
        pg_session.flush()
        return tenant.id

    def test_task_creation_within_limit_succeeds(self, pg_session) -> None:
        tenant_id = self._make_tenant(pg_session, plan="free")
        svc = QuotaEnforcementService(pg_session)
        # free plan: 100 tasks/month — creating 1 must succeed
        svc.check_and_record_task_creation(tenant_id, count=1)
        pg_session.flush()

        repo = TenantRepository(pg_session)
        usage = repo.get_or_create_usage(tenant_id)
        assert usage.tasks_created == 1

    def test_task_creation_batch_count_increments_correctly(self, pg_session) -> None:
        """count=N must increment tasks_created by N, not 1."""
        tenant_id = self._make_tenant(pg_session, plan="free")
        svc = QuotaEnforcementService(pg_session)
        svc.check_and_record_task_creation(tenant_id, count=7)
        pg_session.flush()

        repo = TenantRepository(pg_session)
        usage = repo.get_or_create_usage(tenant_id)
        assert usage.tasks_created == 7

    def test_task_creation_exceeds_limit_raises(self, pg_session) -> None:
        """Exceeding the plan limit must raise QuotaExceededError."""
        tenant_id = self._make_tenant(pg_session, plan="free")
        repo = TenantRepository(pg_session)
        # Seed usage to 99 — one below the free plan limit of 100
        repo.get_or_create_usage(tenant_id)
        pg_session.flush()
        repo.increment_usage(tenant_id, field="tasks_created", amount=99)
        pg_session.flush()

        svc = QuotaEnforcementService(pg_session)
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_and_record_task_creation(tenant_id, count=2)  # 99 + 2 > 100

        err = exc_info.value
        assert err.field == "tasks_per_month"
        assert err.limit == 100
        assert err.current == 99

    def test_enterprise_plan_is_unlimited(self, pg_session) -> None:
        """Enterprise plan (limit=-1) must never raise QuotaExceededError."""
        tenant_id = self._make_tenant(pg_session, plan="enterprise")
        repo = TenantRepository(pg_session)
        # Seed a very high usage count
        repo.get_or_create_usage(tenant_id)
        pg_session.flush()
        repo.increment_usage(tenant_id, field="tasks_created", amount=999_999)
        pg_session.flush()

        svc = QuotaEnforcementService(pg_session)
        # Must not raise
        svc.check_and_record_task_creation(tenant_id, count=1000)

    def test_suspended_tenant_raises_on_quota_check(self, pg_session) -> None:
        """Quota check on a suspended tenant must raise (via get_active)."""
        repo = TenantRepository(pg_session)
        tenant_id = self._make_tenant(pg_session, plan="free")
        repo.suspend(tenant_id, reason="test")
        pg_session.flush()

        svc = QuotaEnforcementService(pg_session)
        with pytest.raises(TenantSuspendedError):
            svc.check_and_record_task_creation(tenant_id)

    def test_feature_gate_webhooks_blocked_on_free_plan(self, pg_session) -> None:
        """Free plan must not have the 'webhooks' feature."""
        tenant_id = self._make_tenant(pg_session, plan="free")
        svc = QuotaEnforcementService(pg_session)

        with pytest.raises(FeatureNotAvailableError) as exc_info:
            svc.require_feature(tenant_id, "webhooks")

        assert exc_info.value.feature == "webhooks"
        assert exc_info.value.plan == "free"

    def test_feature_gate_webhooks_allowed_on_starter_plan(self, pg_session) -> None:
        """Starter plan must include the 'webhooks' feature (seeded by migration 0006)."""
        tenant_id = self._make_tenant(pg_session, plan="starter")
        svc = QuotaEnforcementService(pg_session)
        # Must not raise — starter plan includes webhooks
        svc.require_feature(tenant_id, "webhooks")

    def test_quota_status_returns_correct_counts(self, pg_session) -> None:
        """get_quota_status must reflect the actual usage counters."""
        tenant_id = self._make_tenant(pg_session, plan="free")
        repo = TenantRepository(pg_session)
        repo.get_or_create_usage(tenant_id)
        pg_session.flush()
        repo.increment_usage(tenant_id, field="tasks_created", amount=12)
        repo.increment_usage(tenant_id, field="missions_created", amount=3)
        pg_session.flush()

        svc = QuotaEnforcementService(pg_session)
        status = svc.get_quota_status(tenant_id)

        assert status.tasks_created == 12
        assert status.missions_created == 3
        assert status.tasks_limit == 100  # free plan
        assert status.missions_limit == 10  # free plan
        assert status.plan == "free"

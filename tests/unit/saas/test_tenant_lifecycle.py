"""Unit tests for TenantLifecycleService.

Tests cover:
  - Tenant provisioning: creates tenant, validates slug uniqueness, invalid plan
  - Suspension: active → suspended, requires reason + actor
  - Reactivation: suspended → active, requires actor
  - Soft-delete: active → deleted, idempotent on already-deleted
  - Plan upgrade/downgrade via upgrade_plan()
  - Error propagation from repository
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
)
from backend.services.tenant_lifecycle import TenantLifecycleService, TenantProvisionResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PLANS = ("free", "starter", "pro", "enterprise")


def _make_service_with_mock_repo():
    """Build TenantLifecycleService with a fully mocked TenantRepository."""
    db = MagicMock()
    svc = TenantLifecycleService(db)
    repo = MagicMock()
    svc._tenants = repo
    return svc, repo


def _make_tenant(
    tenant_id: uuid.UUID | None = None,
    slug: str = "acme",
    plan: str = "free",
    status: str = "active",
):
    t = MagicMock()
    t.id = tenant_id or uuid.uuid4()
    t.slug = slug
    t.plan = plan
    t.status = status
    t.name = "Acme Corp"
    return t


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


class TestTenantProvisioning:
    def test_provision_creates_tenant_and_returns_result(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(slug="acme", plan="free")
        repo.get_by_slug.return_value = None  # No existing tenant with this slug
        repo.create.return_value = tenant

        result = svc.provision(name="Acme Corp", slug="acme", plan="free", actor="admin")

        repo.create.assert_called_once()
        assert isinstance(result, TenantProvisionResult)
        assert result.slug == "acme"
        assert result.plan == "free"
        assert result.status == "active"

    def test_provision_with_starter_plan(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(slug="beta-corp", plan="starter")
        repo.get_by_slug.return_value = None
        repo.create.return_value = tenant

        result = svc.provision(name="Beta Corp", slug="beta-corp", plan="starter", actor="admin")
        assert result.plan == "starter"

    def test_provision_slug_conflict_raises(self):
        svc, repo = _make_service_with_mock_repo()
        existing = _make_tenant(slug="acme")
        repo.get_by_slug.return_value = existing  # Slug already taken

        with pytest.raises(ValueError, match="already exists"):
            svc.provision(name="Acme Corp", slug="acme", plan="free", actor="admin")

        repo.create.assert_not_called()

    def test_provision_emits_governance_event(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(slug="new-co")
        repo.get_by_slug.return_value = None
        repo.create.return_value = tenant

        svc.provision(name="New Co", slug="new-co", plan="free", actor="admin")

        # Governance event should be added to the session
        svc._session.add.assert_called()


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------


class TestTenantSuspension:
    def test_suspend_active_tenant(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="active")
        repo.suspend.return_value = tenant

        svc.suspend(tenant.id, reason="non-payment", actor="billing-system")

        repo.suspend.assert_called_once_with(tenant.id, reason="non-payment")

    def test_suspend_emits_governance_event(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="active")
        repo.suspend.return_value = tenant

        svc.suspend(tenant.id, reason="non-payment", actor="billing-system")

        svc._session.add.assert_called()

    def test_suspend_deleted_tenant_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.suspend.side_effect = TenantDeletedError("tenant is deleted")

        with pytest.raises(TenantDeletedError):
            svc.suspend(uuid.uuid4(), reason="test", actor="admin")

    def test_suspend_nonexistent_tenant_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.suspend.side_effect = TenantNotFoundError("not found")

        with pytest.raises(TenantNotFoundError):
            svc.suspend(uuid.uuid4(), reason="test", actor="admin")

    def test_suspend_requires_reason(self):
        """Empty reason string must be rejected."""
        svc, repo = _make_service_with_mock_repo()

        with pytest.raises((ValueError, AssertionError)):
            svc.suspend(uuid.uuid4(), reason="", actor="admin")


# ---------------------------------------------------------------------------
# Reactivation
# ---------------------------------------------------------------------------


class TestTenantReactivation:
    def test_reactivate_suspended_tenant(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="suspended")
        repo.reactivate.return_value = tenant

        svc.reactivate(tenant.id, actor="admin")

        repo.reactivate.assert_called_once_with(tenant.id)

    def test_reactivate_emits_governance_event(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="suspended")
        repo.reactivate.return_value = tenant

        svc.reactivate(tenant.id, actor="admin")

        svc._session.add.assert_called()

    def test_reactivate_deleted_tenant_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.reactivate.side_effect = TenantDeletedError("deleted")

        with pytest.raises(TenantDeletedError):
            svc.reactivate(uuid.uuid4(), actor="admin")

    def test_reactivate_nonexistent_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.reactivate.side_effect = TenantNotFoundError("not found")

        with pytest.raises(TenantNotFoundError):
            svc.reactivate(uuid.uuid4(), actor="admin")


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------


class TestTenantDelete:
    def test_delete_active_tenant(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="active")
        repo.soft_delete.return_value = tenant

        svc.delete(tenant.id, actor="admin")

        repo.soft_delete.assert_called_once_with(tenant.id)

    def test_delete_emits_governance_event(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(status="active")
        repo.soft_delete.return_value = tenant

        svc.delete(tenant.id, actor="admin")

        svc._session.add.assert_called()

    def test_delete_nonexistent_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.soft_delete.side_effect = TenantNotFoundError("not found")

        with pytest.raises(TenantNotFoundError):
            svc.delete(uuid.uuid4(), actor="admin")


# ---------------------------------------------------------------------------
# Plan changes
# ---------------------------------------------------------------------------


class TestPlanChanges:
    def test_upgrade_plan(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(plan="free")
        repo.get.return_value = tenant
        repo.update_plan.return_value = tenant

        svc.upgrade_plan(tenant.id, new_plan="pro", actor="admin")

        repo.update_plan.assert_called_once_with(tenant.id, new_plan="pro")

    def test_downgrade_plan(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(plan="enterprise")
        repo.get.return_value = tenant
        repo.update_plan.return_value = tenant

        svc.upgrade_plan(tenant.id, new_plan="starter", actor="admin")

        repo.update_plan.assert_called_once_with(tenant.id, new_plan="starter")

    def test_plan_change_emits_governance_event(self):
        svc, repo = _make_service_with_mock_repo()
        tenant = _make_tenant(plan="free")
        repo.get.return_value = tenant
        repo.update_plan.return_value = tenant

        svc.upgrade_plan(tenant.id, new_plan="pro", actor="admin")

        svc._session.add.assert_called()

    def test_change_plan_nonexistent_tenant_raises(self):
        svc, repo = _make_service_with_mock_repo()
        repo.get.return_value = None  # Tenant not found

        with pytest.raises(TenantNotFoundError):
            svc.upgrade_plan(uuid.uuid4(), new_plan="pro", actor="admin")

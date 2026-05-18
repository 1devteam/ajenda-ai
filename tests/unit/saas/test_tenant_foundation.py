from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.domain import Tenant, TenantPlan, TenantUsage
from backend.domain.tenant_plan import UNLIMITED
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantRepository,
    TenantSuspendedError,
)


def test_tenant_lifecycle_helpers() -> None:
    tenant = Tenant(name="Tenant A", slug="tenant-a", status="active", plan="free")

    assert tenant.is_active() is True
    assert tenant.is_suspended() is False
    assert tenant.is_deleted() is False

    tenant.status = "suspended"
    assert tenant.is_active() is False
    assert tenant.is_suspended() is True

    tenant.deleted_at = datetime.now(UTC)
    assert tenant.is_deleted() is True


def test_tenant_plan_feature_and_limit_helpers() -> None:
    plan = TenantPlan(
        slug="pro",
        display_name="Pro",
        max_api_keys=20,
        max_tasks_per_month=UNLIMITED,
        features_enabled=["webhooks"],
    )

    assert plan.allows_feature("webhooks") is True
    assert plan.allows_feature("missing") is False
    assert plan.check_limit("max_api_keys", 19) is True
    assert plan.check_limit("max_api_keys", 20) is False
    assert plan.check_limit("max_tasks_per_month", 999_999) is True


def test_tenant_usage_shape() -> None:
    tenant_id = uuid.uuid4()
    usage = TenantUsage(
        tenant_id=tenant_id,
        billing_period_start=datetime.now(UTC).date().replace(day=1),
        missions_created=0,
        tasks_created=0,
        api_calls_count=0,
        agents_provisioned=0,
        active_workers=0,
    )

    assert usage.tenant_id == tenant_id
    assert usage.tasks_created == 0


def test_repository_create_adds_active_tenant() -> None:
    session = MagicMock()
    repo = TenantRepository(session)

    tenant = repo.create(name="Tenant A", slug="tenant-a", plan="starter")

    session.add.assert_called_once_with(tenant)
    assert tenant.status == "active"
    assert tenant.plan == "starter"


def test_repository_get_active_rejects_missing_tenant() -> None:
    session = MagicMock()
    session.get.return_value = None
    repo = TenantRepository(session)

    with pytest.raises(TenantNotFoundError):
        repo.get_active(uuid.uuid4())


def test_repository_get_active_rejects_suspended_tenant() -> None:
    tenant = Tenant(name="Tenant A", slug="tenant-a", status="suspended", plan="free")
    session = MagicMock()
    session.get.return_value = tenant
    repo = TenantRepository(session)

    with pytest.raises(TenantSuspendedError):
        repo.get_active(uuid.uuid4())


def test_repository_get_active_rejects_deleted_tenant() -> None:
    tenant = Tenant(
        name="Tenant A",
        slug="tenant-a",
        status="deleted",
        plan="free",
        deleted_at=datetime.now(UTC),
    )
    session = MagicMock()
    session.get.return_value = tenant
    repo = TenantRepository(session)

    with pytest.raises(TenantDeletedError):
        repo.get_active(uuid.uuid4())


def test_repository_increment_usage_rejects_unknown_field() -> None:
    repo = TenantRepository(MagicMock())

    with pytest.raises(ValueError, match="Unknown usage field"):
        repo.increment_usage(uuid.uuid4(), field="not_real")

"""Unit tests for AccountService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.auth.principal import MachinePrincipal, PrincipalType
from backend.domain.tenant_member import TenantMember
from backend.repositories.tenant_repository import TenantSuspendedError
from backend.services.account_service import AccountService


def _tenant(*, tenant_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=tenant_id or uuid.uuid4(),
        name="Acme Corp",
        slug="acme",
        status="active",
        plan="free",
        stripe_customer_id=None,
        created_at=datetime(2026, 1, 15, tzinfo=UTC),
        is_deleted=lambda: False,
        is_suspended=lambda: False,
    )


def _owner(*, tenant_id: uuid.UUID) -> TenantMember:
    return TenantMember(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email_raw="owner@example.com",
        email_canonical="owner@example.com",
        role="tenant_owner",
        status="active",
    )


def test_get_me_returns_tenant_principal_and_membership() -> None:
    tenant = _tenant()
    owner = _owner(tenant_id=tenant.id)
    principal = MachinePrincipal(
        subject_id="machine:key-1",
        tenant_id=str(tenant.id),
        principal_type=PrincipalType.MACHINE,
        roles=("tenant_operator",),
        permissions=frozenset(),
        key_id="key-1",
    )
    session = MagicMock()

    with (
        patch("backend.services.account_service.TenantRepository") as tenant_repo_cls,
        patch("backend.services.account_service.TenantMemberRepository") as member_repo_cls,
    ):
        tenant_repo = tenant_repo_cls.return_value
        tenant_repo.get_active.return_value = tenant
        member_repo_cls.return_value.get_active_owner_for_tenant.return_value = owner

        summary = AccountService(session).get_me(tenant.id, principal=principal)

    assert summary.tenant.slug == "acme"
    assert summary.principal.subject_id == "machine:key-1"
    assert summary.principal.email == "owner@example.com"
    assert summary.membership is not None
    assert summary.membership.email == "owner@example.com"


def test_get_plan_returns_plan_limits_and_features() -> None:
    tenant = _tenant()
    plan = SimpleNamespace(
        slug="pro",
        display_name="Pro",
        max_missions_per_month=100,
        max_tasks_per_month=1000,
        max_agents_per_fleet=10,
        max_concurrent_workers=4,
        max_api_keys=10,
        max_monthly_api_calls=100_000,
        features_enabled=["ability_runtime"],
    )
    session = MagicMock()

    with patch("backend.services.account_service.TenantRepository") as tenant_repo_cls:
        tenant_repo = tenant_repo_cls.return_value
        tenant_repo.get_active.return_value = tenant
        tenant_repo.get_plan.return_value = plan

        summary = AccountService(session).get_plan(tenant.id)

    assert summary.slug == "pro"
    assert summary.limits["max_tasks_per_month"] == 1000
    assert summary.features_enabled == ["ability_runtime"]


def test_get_usage_delegates_to_quota_service() -> None:
    tenant_id = uuid.uuid4()
    session = MagicMock()
    quota_status = SimpleNamespace(
        tenant_id=str(tenant_id),
        plan="free",
        billing_period="2026-06-01",
        missions_created=2,
        missions_limit=10,
        tasks_created=5,
        tasks_limit=100,
        agents_provisioned=1,
        api_calls_count=20,
        api_calls_limit=10_000,
    )
    tenant = _tenant(tenant_id=tenant_id)
    plan = SimpleNamespace(
        max_agents_per_fleet=2,
        max_api_keys=2,
    )

    with (
        patch("backend.services.account_service.QuotaEnforcementService") as quota_cls,
        patch("backend.services.account_service.TenantRepository") as tenant_repo_cls,
    ):
        quota_cls.return_value.get_quota_status.return_value = quota_status
        tenant_repo = tenant_repo_cls.return_value
        tenant_repo.get_active.return_value = tenant
        tenant_repo.get_plan.return_value = plan

        summary = AccountService(session).get_usage(tenant_id)

    assert summary.usage["missions_created"] == 2
    assert summary.limits["api_keys"] == 2


def test_get_billing_marks_missing_stripe_customer() -> None:
    tenant = _tenant()
    session = MagicMock()

    with patch("backend.services.account_service.TenantRepository") as tenant_repo_cls:
        tenant_repo_cls.return_value.get.return_value = tenant

        summary = AccountService(session).get_billing(tenant.id)

    assert summary.has_billing_account is False
    assert summary.stripe_customer_id is None


def test_get_billing_raises_for_suspended_tenant() -> None:
    tenant = _tenant()
    tenant.status = "suspended"
    tenant.is_suspended = lambda: True
    session = MagicMock()

    with patch("backend.services.account_service.TenantRepository") as tenant_repo_cls:
        tenant_repo_cls.return_value.get.return_value = tenant

        with pytest.raises(TenantSuspendedError):
            AccountService(session).get_billing(tenant.id)

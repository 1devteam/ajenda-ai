"""Unit tests for /v1/account/* routes."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes.account import (
    get_account_billing,
    get_account_me,
    get_account_plan,
    get_account_usage,
)
from backend.auth.permissions import Permission
from backend.auth.principal import MachinePrincipal, PrincipalType
from backend.services.account_service import (
    AccountBillingSummary,
    AccountMembershipSummary,
    AccountMeSummary,
    AccountPlanSummary,
    AccountPrincipalSummary,
    AccountTenantSummary,
    AccountUsageSummary,
)


def _authorized_request(*, roles: tuple[str, ...] = ("tenant_operator",)) -> MagicMock:
    tenant_id = uuid.uuid4()
    request = MagicMock()
    request.state.principal = MachinePrincipal(
        subject_id="machine:key-1",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.MACHINE,
        roles=roles,
        permissions=frozenset(),
        key_id="key-1",
    )
    request.state.tenant_id = str(tenant_id)
    return request, tenant_id


def test_account_me_requires_account_read_permission() -> None:
    request, tenant_id = _authorized_request(roles=("machine_executor",))
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        get_account_me(request=request, tenant_id=tenant_id, db=db)

    assert exc_info.value.status_code == 403


def test_account_me_returns_summary_for_tenant_operator() -> None:
    request, tenant_id = _authorized_request()
    db = MagicMock()
    summary = AccountMeSummary(
        tenant=AccountTenantSummary(
            tenant_id=str(tenant_id),
            name="Acme",
            slug="acme",
            status="active",
            plan="free",
            created_at="2026-01-15T00:00:00+00:00",
        ),
        principal=AccountPrincipalSummary(
            subject_id="machine:key-1",
            principal_type="machine",
            roles=("tenant_operator",),
            email="owner@example.com",
        ),
        membership=AccountMembershipSummary(
            email="owner@example.com",
            role="tenant_owner",
            status="active",
        ),
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_me.return_value = summary
        response = get_account_me(request=request, tenant_id=tenant_id, db=db)

    assert response.tenant.slug == "acme"
    assert response.membership is not None
    assert response.membership.email == "owner@example.com"


def test_account_plan_returns_plan_payload() -> None:
    request, tenant_id = _authorized_request()
    db = MagicMock()
    summary = AccountPlanSummary(
        slug="free",
        display_name="Free",
        limits={"max_missions_per_month": 10},
        features_enabled=[],
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_plan.return_value = summary
        response = get_account_plan(request=request, tenant_id=tenant_id, db=db)

    assert response.slug == "free"
    assert response.limits["max_missions_per_month"] == 10


def test_account_usage_returns_usage_payload() -> None:
    request, tenant_id = _authorized_request()
    db = MagicMock()
    summary = AccountUsageSummary(
        tenant_id=str(tenant_id),
        plan="free",
        billing_period="2026-06-01",
        usage={"missions_created": 1},
        limits={"missions_per_month": 10},
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_usage.return_value = summary
        response = get_account_usage(request=request, tenant_id=tenant_id, db=db)

    assert response.usage["missions_created"] == 1


def test_account_billing_requires_billing_read_permission() -> None:
    request, tenant_id = _authorized_request(roles=("signup_bootstrap",))
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        get_account_billing(request=request, tenant_id=tenant_id, db=db)

    assert exc_info.value.status_code == 403


def test_account_billing_returns_billing_payload() -> None:
    request, tenant_id = _authorized_request()
    db = MagicMock()
    summary = AccountBillingSummary(
        tenant_id=str(tenant_id),
        plan="pro",
        tenant_status="active",
        has_billing_account=True,
        stripe_customer_id="cus_test",
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_billing.return_value = summary
        response = get_account_billing(request=request, tenant_id=tenant_id, db=db)

    assert response.has_billing_account is True
    assert response.stripe_customer_id == "cus_test"


def test_tenant_operator_role_resolves_account_and_billing_permissions() -> None:
    from backend.auth.rbac import RbacAuthorizer

    principal = MachinePrincipal(
        subject_id="machine:key-1",
        tenant_id="tenant-a",
        principal_type=PrincipalType.MACHINE,
        roles=("tenant_operator",),
        permissions=frozenset(),
        key_id="key-1",
    )
    authorizer = RbacAuthorizer()

    assert authorizer.authorize(
        principal=principal,
        permission=Permission.ACCOUNT_READ,
        tenant_id="tenant-a",
    ).allowed
    assert authorizer.authorize(
        principal=principal,
        permission=Permission.BILLING_READ,
        tenant_id="tenant-a",
    ).allowed
    assert authorizer.authorize(
        principal=principal,
        permission=Permission.BILLING_MANAGE,
        tenant_id="tenant-a",
    ).allowed

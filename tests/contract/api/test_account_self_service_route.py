"""Contract tests for tenant self-service account routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.api.routes.account import get_account_me, router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
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
from backend.services.onboarding_service import OnboardingSnapshot


def _build_client(*, roles: tuple[str, ...] = ("tenant_operator",)) -> tuple[TestClient, uuid.UUID]:
    tenant_id = uuid.uuid4()
    app = FastAPI()

    principal = MachinePrincipal(
        subject_id="machine:key-1",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.MACHINE,
        roles=roles,
        permissions=frozenset(),
        key_id="key-1",
    )

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = principal
        return await call_next(request)

    app.include_router(router, prefix="/v1")

    def override_tenant_id() -> uuid.UUID:
        return tenant_id

    def override_db():
        session = MagicMock()
        yield session

    app.dependency_overrides[get_request_tenant_id] = override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = override_db
    return TestClient(app, raise_server_exceptions=False), tenant_id


def test_account_me_requires_auth() -> None:
    request = MagicMock()
    request.state.principal = None
    tenant_id = uuid.uuid4()

    with (
        patch("backend.api.routes.account.require_route_permission"),
        patch("backend.api.routes.account.AccountService"),
        pytest.raises(HTTPException) as exc_info,
    ):
        get_account_me(request=request, tenant_id=tenant_id, db=MagicMock())

    assert exc_info.value.status_code == 401


def test_account_me_returns_tenant_summary() -> None:
    client, tenant_id = _build_client()
    summary = AccountMeSummary(
        tenant=AccountTenantSummary(
            tenant_id=str(tenant_id),
            name="Acme",
            slug="acme",
            status="active",
            plan="free",
            created_at=datetime.now(UTC).isoformat(),
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
        response = client.get("/v1/account/me")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant"]["slug"] == "acme"
    assert body["membership"]["email"] == "owner@example.com"


def test_account_plan_returns_limits() -> None:
    client, tenant_id = _build_client()
    summary = AccountPlanSummary(
        slug="pro",
        display_name="Pro",
        limits={"max_missions_per_month": 100, "max_tasks_per_month": 1000},
        features_enabled=["ability_runtime"],
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_plan.return_value = summary
        response = client.get("/v1/account/plan")

    assert response.status_code == 200
    assert response.json()["features_enabled"] == ["ability_runtime"]


def test_account_usage_returns_quota_summary() -> None:
    client, tenant_id = _build_client()
    summary = AccountUsageSummary(
        tenant_id=str(tenant_id),
        plan="free",
        billing_period="2026-06-01",
        usage={"missions_created": 2, "tasks_created": 5, "agents_provisioned": 0, "api_calls_count": 10},
        limits={
            "missions_per_month": 10,
            "tasks_per_month": 100,
            "agents_per_fleet": 2,
            "api_keys": 2,
            "api_calls_per_month": 10000,
        },
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_usage.return_value = summary
        response = client.get("/v1/account/usage")

    assert response.status_code == 200
    assert response.json()["usage"]["missions_created"] == 2


def test_account_billing_denied_for_bootstrap_role() -> None:
    client, _tenant_id = _build_client(roles=("signup_bootstrap",))

    response = client.get("/v1/account/billing")

    assert response.status_code == 403


def test_account_billing_returns_status() -> None:
    client, tenant_id = _build_client()
    summary = AccountBillingSummary(
        tenant_id=str(tenant_id),
        plan="pro",
        tenant_status="active",
        has_billing_account=True,
        stripe_customer_id="cus_test",
    )

    with patch("backend.api.routes.account.AccountService") as service_cls:
        service_cls.return_value.get_billing.return_value = summary
        response = client.get("/v1/account/billing")

    assert response.status_code == 200
    body = response.json()
    assert body["has_billing_account"] is True
    assert body["stripe_customer_id"] == "cus_test"


def test_account_onboarding_is_status_only_and_does_not_admit_runtime() -> None:
    client, _tenant_id = _build_client()
    snapshot = OnboardingSnapshot(
        setup_version=1,
        completed=True,
        completed_at="2026-09-28T00:00:00+00:00",
        completed_by_member_id="member-1",
        suppress_prompt=False,
        prompt_suppressed_at=None,
        company_profile_ready=True,
        operating_preferences_ready=True,
        can_manage_connections=False,
        human_member=True,
        connections={"gmail": False, "google_calendar": False, "google_contacts": False, "google_docs": False},
    )

    with patch("backend.api.routes.account.OnboardingService") as service_cls:
        service_cls.return_value.read.return_value = snapshot
        response = client.get("/v1/account/onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["completed"] is True
    # Account onboarding is a declarative status surface. It must not expose
    # or imply mission/task/queue/lease execution state.
    assert not any(key in body for key in ("mission_id", "task_ids", "queue", "lease_id", "runtime_queued"))
    service_cls.return_value.read.assert_called_once()

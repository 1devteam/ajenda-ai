"""AccountService — tenant self-service account, plan, usage, and billing reads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.auth.principal import Principal
from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantRepository,
    TenantSuspendedError,
)
from backend.services.quota_enforcement import QuotaEnforcementService


@dataclass(frozen=True, slots=True)
class AccountTenantSummary:
    tenant_id: str
    name: str
    slug: str
    status: str
    plan: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AccountPrincipalSummary:
    subject_id: str
    principal_type: str
    roles: tuple[str, ...]
    email: str | None


@dataclass(frozen=True, slots=True)
class AccountMembershipSummary:
    email: str
    role: str
    status: str


@dataclass(frozen=True, slots=True)
class AccountMeSummary:
    tenant: AccountTenantSummary
    principal: AccountPrincipalSummary
    membership: AccountMembershipSummary | None


@dataclass(frozen=True, slots=True)
class AccountPlanSummary:
    slug: str
    display_name: str
    limits: dict[str, int]
    features_enabled: list[str]


@dataclass(frozen=True, slots=True)
class AccountUsageSummary:
    tenant_id: str
    plan: str
    billing_period: str
    usage: dict[str, int]
    limits: dict[str, int]


@dataclass(frozen=True, slots=True)
class AccountBillingSummary:
    tenant_id: str
    plan: str
    tenant_status: str
    has_billing_account: bool
    stripe_customer_id: str | None


class AccountService:
    """Read-only tenant account surface for customer self-service APIs."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._members = TenantMemberRepository(session)
        self._quota = QuotaEnforcementService(session)

    def get_me(self, tenant_id: uuid.UUID, *, principal: Principal) -> AccountMeSummary:
        tenant = self._tenants.get_active(tenant_id)
        owner = self._members.get_active_owner_for_tenant(tenant_id)
        email = getattr(principal, "email", None)
        if email is None and owner is not None:
            email = owner.email_raw

        membership = None
        if owner is not None:
            membership = AccountMembershipSummary(
                email=owner.email_raw,
                role=owner.role,
                status=owner.status,
            )

        return AccountMeSummary(
            tenant=AccountTenantSummary(
                tenant_id=str(tenant.id),
                name=tenant.name,
                slug=tenant.slug,
                status=tenant.status,
                plan=tenant.plan,
                created_at=tenant.created_at.isoformat(),
            ),
            principal=AccountPrincipalSummary(
                subject_id=principal.subject_id,
                principal_type=principal.principal_type.value,
                roles=principal.roles,
                email=email,
            ),
            membership=membership,
        )

    def get_plan(self, tenant_id: uuid.UUID) -> AccountPlanSummary:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return AccountPlanSummary(
                slug=tenant.plan,
                display_name=tenant.plan,
                limits={
                    "max_missions_per_month": -1,
                    "max_tasks_per_month": -1,
                    "max_agents_per_fleet": -1,
                    "max_concurrent_workers": -1,
                    "max_api_keys": -1,
                    "max_monthly_api_calls": -1,
                },
                features_enabled=[],
            )
        return AccountPlanSummary(
            slug=plan.slug,
            display_name=plan.display_name,
            limits={
                "max_missions_per_month": plan.max_missions_per_month,
                "max_tasks_per_month": plan.max_tasks_per_month,
                "max_agents_per_fleet": plan.max_agents_per_fleet,
                "max_concurrent_workers": plan.max_concurrent_workers,
                "max_api_keys": plan.max_api_keys,
                "max_monthly_api_calls": plan.max_monthly_api_calls,
            },
            features_enabled=list(plan.features_enabled or []),
        )

    def get_usage(self, tenant_id: uuid.UUID) -> AccountUsageSummary:
        status = self._quota.get_quota_status(tenant_id)
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        agents_limit = plan.max_agents_per_fleet if plan else -1
        api_keys_limit = plan.max_api_keys if plan else -1
        return AccountUsageSummary(
            tenant_id=status.tenant_id,
            plan=status.plan,
            billing_period=status.billing_period,
            usage={
                "missions_created": status.missions_created,
                "tasks_created": status.tasks_created,
                "agents_provisioned": status.agents_provisioned,
                "api_calls_count": status.api_calls_count,
            },
            limits={
                "missions_per_month": status.missions_limit,
                "tasks_per_month": status.tasks_limit,
                "agents_per_fleet": agents_limit,
                "api_keys": api_keys_limit,
                "api_calls_per_month": status.api_calls_limit,
            },
        )

    def get_billing(self, tenant_id: uuid.UUID) -> AccountBillingSummary:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Tenant {tenant_id} has been deleted")
        if tenant.is_suspended():
            raise TenantSuspendedError(f"Tenant {tenant_id} is suspended")
        return AccountBillingSummary(
            tenant_id=str(tenant_id),
            plan=tenant.plan,
            tenant_status=tenant.status,
            has_billing_account=tenant.stripe_customer_id is not None,
            stripe_customer_id=tenant.stripe_customer_id,
        )


__all__ = [
    "AccountBillingSummary",
    "AccountMeSummary",
    "AccountMembershipSummary",
    "AccountPlanSummary",
    "AccountPrincipalSummary",
    "AccountService",
    "AccountTenantSummary",
    "AccountUsageSummary",
    "TenantDeletedError",
    "TenantNotFoundError",
    "TenantSuspendedError",
]

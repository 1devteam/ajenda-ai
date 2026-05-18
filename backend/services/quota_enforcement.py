from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from backend.repositories.tenant_repository import TenantRepository


class QuotaExceededError(ValueError):
    """Raised when a tenant exceeds a plan limit."""

    def __init__(self, field: str, limit: int, current: int, plan: str) -> None:
        self.field = field
        self.limit = limit
        self.current = current
        self.plan = plan
        super().__init__(
            f"Quota exceeded for {field!r}: current={current}, limit={limit} (plan={plan!r})."
        )


class FeatureNotAvailableError(ValueError):
    """Raised when a tenant plan does not include a required feature."""

    def __init__(self, feature: str, plan: str) -> None:
        self.feature = feature
        self.plan = plan
        super().__init__(f"Feature {feature!r} is not available on plan {plan!r}.")


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    tenant_id: str
    plan: str
    billing_period: str
    missions_created: int
    missions_limit: int
    tasks_created: int
    tasks_limit: int
    agents_provisioned: int
    api_calls_count: int
    api_calls_limit: int


class QuotaEnforcementService:
    """Central enforcement point for SaaS plan limits and feature gates."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)

    def check_tenant_active(self, tenant_id: uuid.UUID) -> None:
        self._tenants.get_active(tenant_id)

    def check_and_record_mission_creation(self, tenant_id: uuid.UUID) -> None:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        usage = self._tenants.get_or_create_usage(tenant_id)
        limit = plan.max_missions_per_month
        if limit != -1 and usage.missions_created >= limit:
            raise QuotaExceededError(
                field="missions_per_month",
                limit=limit,
                current=usage.missions_created,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(tenant_id, field="missions_created")

    def check_and_record_task_creation(
        self,
        tenant_id: uuid.UUID,
        *,
        count: int = 1,
    ) -> None:
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count}")

        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        usage = self._tenants.get_or_create_usage(tenant_id)
        limit = plan.max_tasks_per_month
        if limit != -1 and usage.tasks_created + count > limit:
            raise QuotaExceededError(
                field="tasks_per_month",
                limit=limit,
                current=usage.tasks_created,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(
            tenant_id,
            field="tasks_created",
            amount=count,
        )

    def check_and_record_agent_provisioning(
        self,
        tenant_id: uuid.UUID,
        *,
        agents_requested: int,
    ) -> None:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        limit = plan.max_agents_per_fleet
        if limit != -1 and agents_requested > limit:
            raise QuotaExceededError(
                field="agents_per_fleet",
                limit=limit,
                current=agents_requested,
                plan=tenant.plan,
            )

        self._tenants.increment_usage(
            tenant_id,
            field="agents_provisioned",
            amount=agents_requested,
        )

    def check_api_key_limit(self, tenant_id: uuid.UUID, *, current_key_count: int) -> None:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        limit = plan.max_api_keys
        if limit != -1 and current_key_count >= limit:
            raise QuotaExceededError(
                field="api_keys",
                limit=limit,
                current=current_key_count,
                plan=tenant.plan,
            )

    def require_feature(self, tenant_id: uuid.UUID, feature: str) -> None:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return

        if not plan.allows_feature(feature):
            raise FeatureNotAvailableError(feature=feature, plan=tenant.plan)

    def get_quota_status(self, tenant_id: uuid.UUID) -> QuotaStatus:
        tenant = self._tenants.get_active(tenant_id)
        plan = self._tenants.get_plan(tenant.plan)
        usage = self._tenants.get_or_create_usage(tenant_id)
        billing_period = date.today().replace(day=1)

        return QuotaStatus(
            tenant_id=str(tenant_id),
            plan=tenant.plan,
            billing_period=str(billing_period),
            missions_created=usage.missions_created,
            missions_limit=plan.max_missions_per_month if plan else -1,
            tasks_created=usage.tasks_created,
            tasks_limit=plan.max_tasks_per_month if plan else -1,
            agents_provisioned=usage.agents_provisioned,
            api_calls_count=usage.api_calls_count,
            api_calls_limit=plan.max_monthly_api_calls if plan else -1,
        )

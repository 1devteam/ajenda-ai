from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.domain.tenant import Tenant
from backend.domain.tenant_plan import TenantPlan
from backend.domain.tenant_usage import TenantUsage


class TenantNotFoundError(ValueError):
    """Raised when a tenant does not exist."""


class TenantSuspendedError(ValueError):
    """Raised when a tenant is suspended."""


class TenantDeletedError(ValueError):
    """Raised when a tenant is deleted."""


class TenantRepository:
    """Data access layer for Tenant, TenantPlan, and TenantUsage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self._session.get(Tenant, tenant_id)

    def get_active(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Tenant {tenant_id} has been deleted")
        if tenant.is_suspended():
            raise TenantSuspendedError(f"Tenant {tenant_id} is suspended")
        return tenant

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self._session.query(Tenant).filter_by(slug=slug).first()

    def create(self, *, name: str, slug: str, plan: str = "free") -> Tenant:
        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            status="active",
            plan=plan,
        )
        self._session.add(tenant)
        return tenant

    def suspend(self, tenant_id: uuid.UUID, *, reason: str) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Cannot suspend deleted tenant {tenant_id}")
        tenant.status = "suspended"
        return tenant

    def reactivate(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Cannot reactivate deleted tenant {tenant_id}")
        tenant.status = "active"
        return tenant

    def soft_delete(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        tenant.status = "deleted"
        tenant.deleted_at = datetime.now(UTC)
        return tenant

    def update_plan(self, tenant_id: uuid.UUID, *, new_plan: str) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        tenant.plan = new_plan
        return tenant

    def get_plan(self, plan_slug: str) -> TenantPlan | None:
        return self._session.query(TenantPlan).filter_by(slug=plan_slug).first()

    def get_plan_for_tenant(self, tenant_id: uuid.UUID) -> TenantPlan | None:
        tenant = self.get(tenant_id)
        if tenant is None:
            return None
        return self.get_plan(tenant.plan)

    def get_or_create_usage(
        self,
        tenant_id: uuid.UUID,
        *,
        billing_period: date | None = None,
    ) -> TenantUsage:
        period = billing_period or date.today().replace(day=1)
        usage = (
            self._session.query(TenantUsage)
            .filter_by(tenant_id=tenant_id, billing_period_start=period)
            .first()
        )
        if usage is not None:
            return usage

        usage = TenantUsage(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            billing_period_start=period,
        )
        self._session.add(usage)
        self._session.flush()
        return usage

    def increment_usage(
        self,
        tenant_id: uuid.UUID,
        *,
        field: str,
        amount: int = 1,
        billing_period: date | None = None,
    ) -> None:
        allowed_fields = {
            "missions_created",
            "tasks_created",
            "api_calls_count",
            "agents_provisioned",
        }
        if field not in allowed_fields:
            raise ValueError(f"Unknown usage field {field!r}. Allowed: {sorted(allowed_fields)}")

        period = billing_period or date.today().replace(day=1)
        self.get_or_create_usage(tenant_id, billing_period=period)
        self._session.execute(
            text(
                f"UPDATE tenant_usage "
                f"SET {field} = {field} + :amount, updated_at = now() "
                f"WHERE tenant_id = :tenant_id AND billing_period_start = :period"
            ),
            {"amount": amount, "tenant_id": tenant_id, "period": period},
        )

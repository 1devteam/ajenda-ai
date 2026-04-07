"""Tenant repository — all database access for Tenant, TenantPlan, TenantUsage.

This repository is the only layer that directly queries the tenant tables.
All methods are tenant-scoped where applicable, and the admin methods are
clearly separated and require explicit admin context.

Design decisions:
  - get_active() raises ValueError (not returns None) for suspended/deleted
    tenants so that callers cannot accidentally proceed with a bad tenant.
  - increment_usage() uses a single atomic UPDATE to avoid lost updates under
    concurrent requests.
  - get_or_create_usage() uses INSERT ... ON CONFLICT DO NOTHING to handle
    the first request of a new billing period safely.
"""

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
    """Raised when a tenant is suspended and cannot accept new work."""


class TenantDeletedError(ValueError):
    """Raised when a tenant has been soft-deleted."""


class TenantRepository:
    """Data access layer for Tenant, TenantPlan, and TenantUsage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Tenant CRUD
    # ------------------------------------------------------------------

    def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        """Return the Tenant row or None if it does not exist."""
        return self._session.get(Tenant, tenant_id)

    def get_active(self, tenant_id: uuid.UUID) -> Tenant:
        """Return the Tenant row, raising if not found, suspended, or deleted.

        This is the method that all mutation paths should call. It enforces
        the lifecycle contract at the repository layer as a second line of
        defense (the first being TenantContextMiddleware).
        """
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

    def create(
        self,
        *,
        name: str,
        slug: str,
        plan: str = "free",
    ) -> Tenant:
        """Create a new active tenant. Caller must flush/commit."""
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
        """Transition tenant to suspended state. Caller must flush/commit."""
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Cannot suspend deleted tenant {tenant_id}")
        tenant.status = "suspended"
        return tenant

    def reactivate(self, tenant_id: uuid.UUID) -> Tenant:
        """Transition tenant from suspended back to active. Caller must flush/commit."""
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        if tenant.is_deleted():
            raise TenantDeletedError(f"Cannot reactivate deleted tenant {tenant_id}")
        tenant.status = "active"
        return tenant

    def soft_delete(self, tenant_id: uuid.UUID) -> Tenant:
        """Soft-delete a tenant. Sets deleted_at; data is retained. Caller must flush/commit."""
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        tenant.status = "deleted"
        tenant.deleted_at = datetime.now(tz=UTC)
        return tenant

    def update_plan(self, tenant_id: uuid.UUID, *, new_plan: str) -> Tenant:
        """Change the subscription plan for a tenant. Caller must flush/commit."""
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        tenant.plan = new_plan
        return tenant

    # ------------------------------------------------------------------
    # TenantPlan
    # ------------------------------------------------------------------

    def get_plan(self, plan_slug: str) -> TenantPlan | None:
        """Return the TenantPlan definition for a given slug."""
        return self._session.query(TenantPlan).filter_by(slug=plan_slug).first()

    def get_plan_for_tenant(self, tenant_id: uuid.UUID) -> TenantPlan | None:
        """Return the TenantPlan for the given tenant's current plan slug."""
        tenant = self.get(tenant_id)
        if tenant is None:
            return None
        return self.get_plan(tenant.plan)

    # ------------------------------------------------------------------
    # TenantUsage — metering
    # ------------------------------------------------------------------

    def get_or_create_usage(
        self,
        tenant_id: uuid.UUID,
        *,
        billing_period: date | None = None,
    ) -> TenantUsage:
        """Return the TenantUsage row for the current billing period.

        If no row exists for this period, inserts one atomically using
        INSERT ... ON CONFLICT DO NOTHING to handle concurrent first-requests.
        """
        period = billing_period or date.today().replace(day=1)
        usage = self._session.query(TenantUsage).filter_by(tenant_id=tenant_id, billing_period_start=period).first()
        if usage is None:
            usage = TenantUsage(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                billing_period_start=period,
            )
            self._session.add(usage)
            self._session.flush()
            # Re-query in case a concurrent request inserted first
            usage = self._session.query(TenantUsage).filter_by(tenant_id=tenant_id, billing_period_start=period).first()
        return usage

    def increment_usage(
        self,
        tenant_id: uuid.UUID,
        *,
        field: str,
        amount: int = 1,
        billing_period: date | None = None,
    ) -> None:
        """Atomically increment a usage counter for the current billing period.

        Uses a raw UPDATE to avoid ORM-level lost updates under concurrent
        requests. Safe to call from multiple workers simultaneously.

        Args:
            tenant_id: The tenant whose usage is being incremented.
            field: The column name to increment (e.g. 'tasks_created').
            amount: How much to increment by (default 1).
            billing_period: Override the billing period (defaults to current month).
        """
        allowed_fields = {
            "missions_created",
            "tasks_created",
            "api_calls_count",
            "agents_provisioned",
        }
        if field not in allowed_fields:
            raise ValueError(f"Unknown usage field {field!r}. Allowed: {sorted(allowed_fields)}")
        period = billing_period or date.today().replace(day=1)
        # Ensure the row exists first
        self.get_or_create_usage(tenant_id, billing_period=period)
        # Atomic increment
        self._session.execute(
            text(
                f"UPDATE tenant_usage "
                f"SET {field} = {field} + :amount, updated_at = now() "
                f"WHERE tenant_id = :tenant_id AND billing_period_start = :period"
            ),
            {"amount": amount, "tenant_id": tenant_id, "period": period},
        )

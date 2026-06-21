"""TenantLifecycleService — tenant provisioning, suspension, reactivation, and teardown.

This service owns the full lifecycle of a Tenant record. It is the only
code path that should create, suspend, reactivate, or delete tenants.

Lifecycle state machine:
  (new) --> active --> suspended --> active  (reactivation)
                   --> deleted               (soft-delete, irreversible)
  active --> deleted                         (direct soft-delete)

Design decisions:
  - All transitions emit a GovernanceEvent for the immutable audit trail.
  - Suspension is reversible; deletion is not (within the retention window).
  - Provisioning seeds the default TenantPlan row lookup (does not create a
    new plan — plans are pre-seeded by migration 0006).
  - The service does not commit — callers own the transaction boundary.
  - Tenant INSERT authority is centralized here via provision(source=...).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.domain.governance_event import GovernanceEvent
from backend.domain.provision_source import ProvisionSource
from backend.repositories.tenant_repository import (
    TenantNotFoundError,
    TenantRepository,
)

_SELF_SERVE_ALLOWED_PLANS = frozenset({"free"})


@dataclass(frozen=True)
class TenantProvisionResult:
    tenant_id: uuid.UUID
    slug: str
    plan: str
    status: str
    source: ProvisionSource


class TenantLifecycleService:
    """Cross-tenant tenant lifecycle authority.

    Callable from admin control-plane routes and the self-serve onboarding
    orchestrator only. Must never be invoked from tenant-scoped API routes.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._tenants = TenantRepository(session)

    def provision(
        self,
        *,
        name: str,
        slug: str,
        plan: str = "free",
        actor: str = "system",
        source: ProvisionSource = ProvisionSource.ADMIN,
    ) -> TenantProvisionResult:
        """Create a new active tenant and emit a provisioning governance event.

        Raises ValueError if a tenant with the given slug already exists or if
        the plan is not allowed for the given source. IntegrityError may
        propagate from flush on concurrent slug collision — callers should
        rollback and map to HTTP 409.

        Caller must commit.
        """
        normalized_plan = plan.strip().lower()
        self._validate_plan_for_source(normalized_plan, source=source)

        existing = self._tenants.get_by_slug(slug)
        if existing is not None:
            raise ValueError(f"Tenant with slug {slug!r} already exists (id={existing.id})")

        tenant = self._tenants.create(name=name, slug=slug, plan=normalized_plan)
        self._session.flush()

        event_type, decision = self._provision_event_metadata(
            source=source,
            slug=slug,
            plan=normalized_plan,
        )
        self._emit_event(
            tenant_id=tenant.id,
            event_type=event_type,
            actor=actor,
            decision=decision,
            payload={
                "name": name,
                "slug": slug,
                "plan": normalized_plan,
                "source": source.value,
            },
        )

        return TenantProvisionResult(
            tenant_id=tenant.id,
            slug=tenant.slug,
            plan=tenant.plan,
            status=tenant.status,
            source=source,
        )

    def suspend(
        self,
        tenant_id: uuid.UUID,
        *,
        reason: str,
        actor: str,
    ) -> None:
        """Suspend a tenant, blocking all mutation operations.

        Raises TenantNotFoundError or TenantDeletedError if the tenant
        cannot be suspended. Caller must commit.
        """
        if not reason or not reason.strip():
            raise ValueError("Suspension reason must be a non-empty string.")
        self._tenants.suspend(tenant_id, reason=reason)

        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_suspended",
            actor=actor,
            decision=f"Tenant suspended: {reason}",
            payload={"reason": reason},
        )

    def reactivate(
        self,
        tenant_id: uuid.UUID,
        *,
        actor: str,
    ) -> None:
        """Reactivate a suspended tenant.

        Raises TenantNotFoundError or TenantDeletedError if the tenant
        cannot be reactivated. Caller must commit.
        """
        self._tenants.reactivate(tenant_id)

        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_reactivated",
            actor=actor,
            decision="Tenant reactivated",
            payload={},
        )

    def delete(
        self,
        tenant_id: uuid.UUID,
        *,
        actor: str,
        reason: str = "admin_initiated",
    ) -> None:
        """Soft-delete a tenant. Irreversible within the retention window.

        Sets deleted_at and status='deleted'. Data is retained for the
        compliance retention period. Caller must commit.
        """
        self._tenants.soft_delete(tenant_id)

        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_deleted",
            actor=actor,
            decision=f"Tenant soft-deleted: {reason}",
            payload={"reason": reason},
        )

    def upgrade_plan(
        self,
        tenant_id: uuid.UUID,
        *,
        new_plan: str,
        actor: str,
    ) -> None:
        """Change the subscription plan for a tenant.

        Raises TenantNotFoundError if the tenant does not exist.
        Caller must commit.
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")

        old_plan = tenant.plan
        self._tenants.update_plan(tenant_id, new_plan=new_plan)

        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_plan_changed",
            actor=actor,
            decision=f"Plan changed from {old_plan!r} to {new_plan!r}",
            payload={"old_plan": old_plan, "new_plan": new_plan},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_plan_for_source(plan: str, *, source: ProvisionSource) -> None:
        if source == ProvisionSource.SELF_SERVE and plan not in _SELF_SERVE_ALLOWED_PLANS:
            raise ValueError(f"Self-serve provisioning may only create free-plan tenants; got {plan!r}.")

    @staticmethod
    def _provision_event_metadata(*, source: ProvisionSource, slug: str, plan: str) -> tuple[str, str]:
        if source == ProvisionSource.SELF_SERVE:
            return (
                "tenant_self_serve_provisioned",
                f"Tenant {slug!r} self-serve provisioned on plan {plan!r}",
            )
        return (
            "tenant_provisioned",
            f"Tenant {slug!r} provisioned on plan {plan!r}",
        )

    def _emit_event(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        actor: str,
        decision: str,
        payload: dict[str, object],
    ) -> None:
        """Append a GovernanceEvent to the immutable audit trail."""
        activate_tenant_session(self._session, str(tenant_id))
        event = GovernanceEvent(
            id=uuid.uuid4(),
            tenant_id=str(tenant_id),
            event_type=event_type,
            actor=actor,
            decision=decision,
            payload_json=payload,
            created_at=datetime.now(tz=UTC),
        )
        self._session.add(event)

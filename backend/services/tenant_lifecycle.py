from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.governance_event import GovernanceEvent
from backend.repositories.tenant_repository import (
    TenantNotFoundError,
    TenantRepository,
)


@dataclass(frozen=True, slots=True)
class TenantProvisionResult:
    tenant_id: uuid.UUID
    slug: str
    plan: str
    status: str


class TenantLifecycleService:
    """Manages tenant provisioning, lifecycle transitions, and plan changes."""

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
    ) -> TenantProvisionResult:
        existing = self._tenants.get_by_slug(slug)
        if existing is not None:
            raise ValueError(f"Tenant with slug {slug!r} already exists")

        tenant = self._tenants.create(name=name, slug=slug, plan=plan)
        self._session.flush()

        self._emit_event(
            tenant_id=tenant.id,
            event_type="tenant_provisioned",
            actor=actor,
            decision=f"Tenant {slug!r} provisioned on plan {plan!r}",
            payload={"name": name, "slug": slug, "plan": plan},
        )

        return TenantProvisionResult(
            tenant_id=tenant.id,
            slug=tenant.slug,
            plan=tenant.plan,
            status=tenant.status,
        )

    def suspend(self, tenant_id: uuid.UUID, *, reason: str, actor: str) -> None:
        if not reason.strip():
            raise ValueError("Suspension reason must be a non-empty string.")

        self._tenants.suspend(tenant_id, reason=reason)
        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_suspended",
            actor=actor,
            decision=f"Tenant suspended: {reason}",
            payload={"reason": reason},
        )

    def reactivate(self, tenant_id: uuid.UUID, *, actor: str) -> None:
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
        self._tenants.soft_delete(tenant_id)
        self._emit_event(
            tenant_id=tenant_id,
            event_type="tenant_deleted",
            actor=actor,
            decision=f"Tenant soft-deleted: {reason}",
            payload={"reason": reason},
        )

    def upgrade_plan(self, tenant_id: uuid.UUID, *, new_plan: str, actor: str) -> None:
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

    def _emit_event(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        actor: str,
        decision: str,
        payload: dict[str, Any],
    ) -> None:
        self._session.add(
            GovernanceEvent(
                id=uuid.uuid4(),
                tenant_id=str(tenant_id),
                mission_id=None,
                event_type=event_type,
                actor=actor,
                decision=decision,
                payload_json=payload,
                created_at=datetime.now(UTC),
            )
        )

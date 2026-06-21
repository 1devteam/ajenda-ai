"""Helpers for activating PostgreSQL tenant session context (RLS)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def activate_tenant_session(session: Session, tenant_id: str) -> None:
    """Set ``app.current_tenant_id`` for the current transaction.

    Required before writing tenant-scoped rows protected by RLS (e.g.
    ``governance_events``) from system/cross-tenant code paths such as
    Stripe webhooks or admin lifecycle services.
    """
    session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )

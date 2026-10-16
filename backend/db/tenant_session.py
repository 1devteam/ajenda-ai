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
    # SQLite-backed unit tests and lightweight fakes do not implement
    # PostgreSQL's transaction-local setting.  They have no RLS policy to
    # activate; real application sessions are bound to PostgreSQL and always
    # take the fail-closed path below.
    execute = getattr(session, "execute", None)
    if not callable(execute):
        return
    dialect_name = getattr(getattr(getattr(session, "bind", None), "dialect", None), "name", None)
    if isinstance(dialect_name, str) and dialect_name != "postgresql":
        return
    execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )

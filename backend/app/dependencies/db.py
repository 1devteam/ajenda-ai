from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.db.session import DatabaseRuntime


def get_database_runtime(request: Request) -> DatabaseRuntime:
    runtime: DatabaseRuntime = request.app.state.database_runtime
    return runtime


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a transactional DB session without tenant RLS context.

    Use for admin routes, health checks, and any cross-tenant operations.
    For per-tenant API routes, prefer ``get_tenant_db_session`` which activates
    PostgreSQL Row-Level Security for the request's tenant.
    """
    runtime = get_database_runtime(request)
    yield from runtime.session_scope()


def get_tenant_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a transactional DB session with Row-Level Security activated.

    Reads ``request.state.tenant_id`` (set by TenantContextMiddleware) and
    executes ``SET LOCAL app.current_tenant_id`` so that PostgreSQL RLS policies
    enforce tenant isolation at the database level.

    Raises HTTP 400 if tenant_id is not present on the request state — this
    should not happen in practice because TenantContextMiddleware rejects
    requests without a valid X-Tenant-Id header before they reach route handlers.
    """
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context on request state.")
    runtime = get_database_runtime(request)
    yield from runtime.tenant_session_scope(tenant_id)

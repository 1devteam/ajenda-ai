from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.db.session import DatabaseRuntime


def get_database_runtime(request: Request) -> DatabaseRuntime:
    return request.app.state.database_runtime


def get_db_session(request: Request) -> Generator[Session, None, None]:
    runtime = get_database_runtime(request)
    yield from runtime.session_scope()


def get_request_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing tenant context on request state.",
        )
    return str(tenant_id)


def get_tenant_db_session(request: Request) -> Generator[Session, None, None]:
    runtime = get_database_runtime(request)
    tenant_id = get_request_tenant_id(request)
    yield from runtime.tenant_session_scope(tenant_id)

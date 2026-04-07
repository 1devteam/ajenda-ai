from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health(db: Session = Depends(get_db_session)) -> dict[str, str]:
    """Infrastructure health check. Public — no tenant context required.

    Uses get_db_session intentionally. See:
    docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.2
    """
    return SystemStatusService(db).health()


@router.get("/system/readiness")
def system_readiness(db: Session = Depends(get_db_session)) -> dict[str, str]:
    """Infrastructure readiness check. Public — no tenant context required.

    Uses get_db_session intentionally. See:
    docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.2
    """
    return SystemStatusService(db).readiness()


@router.get("/system/status")
def system_status(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, dict[str, int]]:
    """Return operational status for the authenticated tenant.

    Tenant-facing — uses get_tenant_db_session to activate RLS. See:
    docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.1
    """
    return SystemStatusService(db).status(tenant_id=str(tenant_id))

from __future__ import annotations

import uuid as _uuid

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.authorization_service import AuthorizationService


def require_route_permission(
    *,
    request: Request,
    db: Session,
    permission: Permission,
    tenant_id: _uuid.UUID | str,
) -> None:
    """Enforce route-level RBAC for authenticated tenant-scoped/control-plane calls."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing authentication")
    try:
        AuthorizationService.from_settings(
            get_settings(),
            audit_repository=AuditEventRepository(db),
        ).require(
            principal=principal,
            permission=permission,
            tenant_id=str(tenant_id),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

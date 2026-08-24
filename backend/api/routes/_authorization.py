from __future__ import annotations

import uuid as _uuid

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.errors import authentication_required_http
from backend.app.config import get_settings
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.authorization_service import AuthorizationService


def _authorization_service(db: Session) -> AuthorizationService:
    return AuthorizationService.from_settings(
        get_settings(),
        audit_repository=AuditEventRepository(db),
    )


def require_route_permission(
    *,
    request: Request,
    db: Session,
    permission: Permission,
    tenant_id: _uuid.UUID | str,
) -> None:
    """Enforce route-level RBAC for authenticated tenant-scoped calls."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise authentication_required_http()
    try:
        _authorization_service(db).require(
            principal=principal,
            permission=permission,
            tenant_id=str(tenant_id),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def require_platform_permission(
    *,
    request: Request,
    db: Session,
    permission: Permission,
) -> None:
    """Enforce platform/global authority without binding it to a request tenant."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise authentication_required_http()
    try:
        _authorization_service(db).require_platform(
            principal=principal,
            permission=permission,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

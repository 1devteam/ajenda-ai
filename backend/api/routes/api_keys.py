from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.api_key_service import ApiKeyService
from backend.services.authorization_service import AuthorizationService
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

_REQUEST_TENANT_ID = Depends(get_request_tenant_id)
_TENANT_DB_SESSION = Depends(get_tenant_db_session)


class CreateApiKeyRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)


def _tenant_uuid_or_400(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a UUID") from exc


def _quota_detail(exc: QuotaExceededError) -> dict[str, Any]:
    return {
        "code": "QUOTA_EXCEEDED",
        "field": exc.field,
        "limit": exc.limit,
        "current": exc.current,
        "plan": exc.plan,
    }


@router.post("")
def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    tenant_id: str = _REQUEST_TENANT_ID,
    db: Session = _TENANT_DB_SESSION,
) -> dict[str, object]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing authentication")

    AuthorizationService(AuditEventRepository(db)).require(
        principal=principal,
        permission=Permission.API_KEYS_CREATE,
        tenant_id=tenant_id,
    )

    service = ApiKeyService(db)
    try:
        QuotaEnforcementService(db).check_api_key_limit(
            _tenant_uuid_or_400(tenant_id),
            current_key_count=service.count_active_keys(tenant_id=tenant_id),
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=_quota_detail(exc)) from exc

    plaintext, record = service.create_key(tenant_id=tenant_id, scopes=tuple(body.scopes))
    return {
        "key_id": record.key_id,
        "tenant_id": record.tenant_id,
        "scopes": list(record.scopes_json),
        "plaintext_key": f"{record.key_id}.{plaintext}",
    }


@router.post("/{key_id}/revoke")
def revoke_api_key(
    key_id: str,
    request: Request,
    tenant_id: str = _REQUEST_TENANT_ID,
    db: Session = _TENANT_DB_SESSION,
) -> dict[str, str]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing authentication")

    AuthorizationService(AuditEventRepository(db)).require(
        principal=principal,
        permission=Permission.API_KEYS_REVOKE,
        tenant_id=tenant_id,
    )

    try:
        ApiKeyService(db).revoke_key(key_id=key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"key_id": key_id, "status": "revoked"}

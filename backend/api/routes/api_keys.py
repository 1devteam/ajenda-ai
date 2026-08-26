from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.errors import authentication_required_http, quota_exceeded_http
from backend.app.config import get_settings
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.api_key_service import ApiKeyService
from backend.services.authorization_service import AuthorizationService
from backend.services.quota_enforcement import (
    QuotaConfigurationError,
    QuotaEnforcementService,
    QuotaExceededError,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)


@router.post("")
def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, object]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise authentication_required_http()
    settings = get_settings()
    AuthorizationService.from_settings(
        settings,
        audit_repository=AuditEventRepository(db),
    ).require(
        principal=principal,
        permission=Permission.API_KEYS_CREATE,
        tenant_id=str(tenant_id),
    )

    # The quota service holds the tenant-row reservation lock until this
    # request transaction commits/rolls back. Key creation therefore consumes
    # the capacity snapshot atomically with the new active key.
    try:
        QuotaEnforcementService(db).reserve_api_key_capacity(tenant_id)
    except QuotaExceededError as exc:
        raise quota_exceeded_http(exc) from exc
    except QuotaConfigurationError as exc:
        raise HTTPException(status_code=503, detail="API-key quota configuration is unavailable") from exc

    plaintext, record = ApiKeyService(db).create_key(tenant_id=str(tenant_id), scopes=tuple(body.scopes))
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
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, str]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise authentication_required_http()
    settings = get_settings()
    AuthorizationService.from_settings(
        settings,
        audit_repository=AuditEventRepository(db),
    ).require(
        principal=principal,
        permission=Permission.API_KEYS_REVOKE,
        tenant_id=str(tenant_id),
    )
    try:
        ApiKeyService(db).revoke_key(key_id=key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"key_id": key_id, "status": "revoked"}

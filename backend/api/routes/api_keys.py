from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.auth.permissions import Permission
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.api_key_service import ApiKeyService
from backend.services.authorization_service import AuthorizationService
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError
import uuid as _uuid

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)


@router.post("")
def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing authentication")
    AuthorizationService(AuditEventRepository(db)).require(
        principal=principal,
        permission=Permission.API_KEYS_CREATE,
        tenant_id=tenant_id,
    )
    # --- Quota check: API key count ---
    tenant_uuid = _uuid.UUID(tenant_id)
    service = ApiKeyService(db)
    current_key_count = service.count_active_keys(tenant_id=tenant_id)
    try:
        QuotaEnforcementService(db).check_api_key_limit(
            tenant_uuid,
            current_key_count=current_key_count,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "QUOTA_EXCEEDED",
                "field": exc.field,
                "limit": exc.limit,
                "current": exc.current,
                "plan": exc.plan,
                "message": (
                    f"You have reached the API key limit ({exc.limit}) "
                    f"for the {exc.plan!r} plan. Upgrade to continue."
                ),
            },
        ) from exc

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
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
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

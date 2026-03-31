from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def who_am_i(request: Request) -> dict[str, object]:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing authentication")
    return {
        "subject_id": principal.subject_id,
        "tenant_id": principal.tenant_id,
        "principal_type": principal.principal_type.value,
        "roles": list(principal.roles),
        "permissions": sorted(permission.value for permission in principal.permissions),
        "email": getattr(principal, "email", None),
    }

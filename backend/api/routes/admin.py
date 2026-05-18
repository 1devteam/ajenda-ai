from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantSuspendedError,
)
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.tenant_lifecycle import TenantLifecycleService

router = APIRouter(prefix="/admin", tags=["admin"])


class ProvisionTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")
    plan: str = Field(default="free", pattern=r"^(free|starter|pro|enterprise)$")


class ProvisionTenantResponse(BaseModel):
    tenant_id: str
    slug: str
    plan: str
    status: str


class SuspendTenantRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ChangePlanRequest(BaseModel):
    new_plan: str = Field(pattern=r"^(free|starter|pro|enterprise)$")


def _get_actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return "unknown_admin"
    return str(getattr(principal, "subject_id", "unknown_admin"))


def _require_admin(request: Request) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=403, detail="Admin authentication required")

    roles = getattr(principal, "roles", ())
    if "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Insufficient privileges. This endpoint requires the 'admin' role.",
        )


@router.post("/tenants", response_model=ProvisionTenantResponse, status_code=201)
def provision_tenant(
    body: ProvisionTenantRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> ProvisionTenantResponse:
    _require_admin(request)
    try:
        result = TenantLifecycleService(db).provision(
            name=body.name,
            slug=body.slug,
            plan=body.plan,
            actor=_get_actor(request),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ProvisionTenantResponse(
        tenant_id=str(result.tenant_id),
        slug=result.slug,
        plan=result.plan,
        status=result.status,
    )


@router.post("/tenants/{tenant_id}/suspend", status_code=200)
def suspend_tenant(
    tenant_id: uuid.UUID,
    body: SuspendTenantRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_admin(request)
    try:
        TenantLifecycleService(db).suspend(
            tenant_id,
            reason=body.reason,
            actor=_get_actor(request),
        )
        db.commit()
    except TenantNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TenantDeletedError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"tenant_id": str(tenant_id), "status": "suspended"}


@router.post("/tenants/{tenant_id}/reactivate", status_code=200)
def reactivate_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_admin(request)
    try:
        TenantLifecycleService(db).reactivate(tenant_id, actor=_get_actor(request))
        db.commit()
    except (TenantNotFoundError, TenantDeletedError) as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"tenant_id": str(tenant_id), "status": "active"}


@router.delete("/tenants/{tenant_id}", status_code=200)
def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_admin(request)
    try:
        TenantLifecycleService(db).delete(tenant_id, actor=_get_actor(request))
        db.commit()
    except TenantNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"tenant_id": str(tenant_id), "status": "deleted"}


@router.post("/tenants/{tenant_id}/plan", status_code=200)
def change_plan(
    tenant_id: uuid.UUID,
    body: ChangePlanRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_admin(request)
    try:
        TenantLifecycleService(db).upgrade_plan(
            tenant_id,
            new_plan=body.new_plan,
            actor=_get_actor(request),
        )
        db.commit()
    except TenantNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"tenant_id": str(tenant_id), "plan": body.new_plan}


@router.get("/tenants/{tenant_id}/quota", status_code=200)
def get_quota_status(
    tenant_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        status = QuotaEnforcementService(db).get_quota_status(tenant_id)
    except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "tenant_id": status.tenant_id,
        "plan": status.plan,
        "billing_period": status.billing_period,
        "usage": {
            "missions_created": status.missions_created,
            "missions_limit": status.missions_limit,
            "tasks_created": status.tasks_created,
            "tasks_limit": status.tasks_limit,
            "agents_provisioned": status.agents_provisioned,
            "api_calls_count": status.api_calls_count,
            "api_calls_limit": status.api_calls_limit,
        },
    }

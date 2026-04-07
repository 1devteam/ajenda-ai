"""Admin control-plane routes — tenant lifecycle and plan management.

These routes are restricted to the 'admin' role via RBAC. They are mounted
under /v1/admin/ and are NOT accessible to tenant-scoped principals.

All routes require:
  - A valid JWT with role='admin' in the principal claims.
  - The X-Tenant-Id header is NOT required (admin operates cross-tenant).

Endpoints:
  POST   /v1/admin/tenants                  — Provision a new tenant
  GET    /v1/admin/tenants/{tenant_id}      — Get tenant details
  POST   /v1/admin/tenants/{tenant_id}/suspend    — Suspend a tenant
  POST   /v1/admin/tenants/{tenant_id}/reactivate — Reactivate a tenant
  DELETE /v1/admin/tenants/{tenant_id}      — Soft-delete a tenant
  POST   /v1/admin/tenants/{tenant_id}/plan — Change subscription plan
  GET    /v1/admin/tenants/{tenant_id}/quota — Get quota status
"""

from __future__ import annotations

import uuid

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


# ------------------------------------------------------------------
# Request / Response schemas
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Helper: extract actor from request principal
# ------------------------------------------------------------------


def _get_actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return "unknown_admin"
    return getattr(principal, "subject_id", "unknown_admin")


def _require_admin(request: Request) -> None:
    """Raise HTTP 403 if the caller is not an admin principal."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=403, detail="Admin authentication required")
    roles = getattr(principal, "roles", set())
    if "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Insufficient privileges. This endpoint requires the 'admin' role.",
        )


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@router.post("/tenants", response_model=ProvisionTenantResponse, status_code=201)
def provision_tenant(
    body: ProvisionTenantRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> ProvisionTenantResponse:
    """Provision a new SaaS tenant."""
    _require_admin(request)
    actor = _get_actor(request)
    try:
        result = TenantLifecycleService(db).provision(
            name=body.name,
            slug=body.slug,
            plan=body.plan,
            actor=actor,
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
) -> dict:
    """Suspend a tenant. Blocks all mutation operations for that tenant."""
    _require_admin(request)
    actor = _get_actor(request)
    try:
        TenantLifecycleService(db).suspend(tenant_id, reason=body.reason, actor=actor)
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
) -> dict:
    """Reactivate a suspended tenant."""
    _require_admin(request)
    actor = _get_actor(request)
    try:
        TenantLifecycleService(db).reactivate(tenant_id, actor=actor)
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
) -> dict:
    """Soft-delete a tenant. Irreversible within the compliance retention window."""
    _require_admin(request)
    actor = _get_actor(request)
    try:
        TenantLifecycleService(db).delete(tenant_id, actor=actor)
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
) -> dict:
    """Change the subscription plan for a tenant."""
    _require_admin(request)
    actor = _get_actor(request)
    try:
        TenantLifecycleService(db).upgrade_plan(tenant_id, new_plan=body.new_plan, actor=actor)
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
) -> dict:
    """Return the current quota consumption for a tenant."""
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

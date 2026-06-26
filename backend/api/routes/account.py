"""Tenant self-service account routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.api.routes.provider_credentials import router as provider_credentials_router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantSuspendedError,
)
from backend.services.account_service import AccountService

router = APIRouter(prefix="/account", tags=["account"])
router.include_router(provider_credentials_router)


class AccountTenantResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    status: str
    plan: str
    created_at: str


class AccountPrincipalResponse(BaseModel):
    subject_id: str
    principal_type: str
    roles: list[str]
    email: str | None = None


class AccountMembershipResponse(BaseModel):
    email: str
    role: str
    status: str


class AccountMeResponse(BaseModel):
    tenant: AccountTenantResponse
    principal: AccountPrincipalResponse
    membership: AccountMembershipResponse | None = None


class AccountPlanResponse(BaseModel):
    slug: str
    display_name: str
    limits: dict[str, int]
    features_enabled: list[str]


class AccountUsageResponse(BaseModel):
    tenant_id: str
    plan: str
    billing_period: str
    usage: dict[str, int]
    limits: dict[str, int]


class AccountBillingResponse(BaseModel):
    tenant_id: str
    plan: str
    tenant_status: str
    has_billing_account: bool
    stripe_customer_id: str | None = None


def _map_account_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, TenantNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (TenantSuspendedError, TenantDeletedError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    raise exc


@router.get("/me", response_model=AccountMeResponse, status_code=status.HTTP_200_OK)
def get_account_me(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AccountMeResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.ACCOUNT_READ,
        tenant_id=tenant_id,
    )
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing authentication")
    try:
        summary = AccountService(db).get_me(tenant_id, principal=principal)
    except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise _map_account_errors(exc) from exc
    return AccountMeResponse(
        tenant=AccountTenantResponse(
            tenant_id=summary.tenant.tenant_id,
            name=summary.tenant.name,
            slug=summary.tenant.slug,
            status=summary.tenant.status,
            plan=summary.tenant.plan,
            created_at=summary.tenant.created_at,
        ),
        principal=AccountPrincipalResponse(
            subject_id=summary.principal.subject_id,
            principal_type=summary.principal.principal_type,
            roles=list(summary.principal.roles),
            email=summary.principal.email,
        ),
        membership=(
            AccountMembershipResponse(
                email=summary.membership.email,
                role=summary.membership.role,
                status=summary.membership.status,
            )
            if summary.membership is not None
            else None
        ),
    )


@router.get("/plan", response_model=AccountPlanResponse, status_code=status.HTTP_200_OK)
def get_account_plan(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AccountPlanResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.ACCOUNT_READ,
        tenant_id=tenant_id,
    )
    try:
        summary = AccountService(db).get_plan(tenant_id)
    except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise _map_account_errors(exc) from exc
    return AccountPlanResponse(
        slug=summary.slug,
        display_name=summary.display_name,
        limits=summary.limits,
        features_enabled=summary.features_enabled,
    )


@router.get("/usage", response_model=AccountUsageResponse, status_code=status.HTTP_200_OK)
def get_account_usage(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AccountUsageResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.ACCOUNT_READ,
        tenant_id=tenant_id,
    )
    try:
        summary = AccountService(db).get_usage(tenant_id)
    except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise _map_account_errors(exc) from exc
    return AccountUsageResponse(
        tenant_id=summary.tenant_id,
        plan=summary.plan,
        billing_period=summary.billing_period,
        usage=summary.usage,
        limits=summary.limits,
    )


@router.get("/billing", response_model=AccountBillingResponse, status_code=status.HTTP_200_OK)
def get_account_billing(
    request: Request,
    tenant_id: UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AccountBillingResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.BILLING_READ,
        tenant_id=tenant_id,
    )
    try:
        summary = AccountService(db).get_billing(tenant_id)
    except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError) as exc:
        raise _map_account_errors(exc) from exc
    return AccountBillingResponse(
        tenant_id=summary.tenant_id,
        plan=summary.plan,
        tenant_status=summary.tenant_status,
        has_billing_account=summary.has_billing_account,
        stripe_customer_id=summary.stripe_customer_id,
    )

"""Self-serve tenant onboarding routes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import MachinePrincipal
from backend.services.quota_enforcement import QuotaExceededError
from backend.services.signup_abuse_guard import SignupDisabledError, SignupRateLimitedError
from backend.services.tenant_onboarding_orchestrator import (
    BootstrapPromotionError,
    DuplicateEmailError,
    InvalidVerificationTokenError,
    MemberNotFoundError,
    TenantOnboardingOrchestrator,
    VerificationExpiredError,
    VerificationPendingError,
)
from backend.services.verification_delivery import (
    DeliveryError,
    build_verify_url,
    verification_delivery_from_settings,
)
from backend.utils.client_ip import extract_client_ip, hash_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class SignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9\-]+$", max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=256)


class SignupResponse(BaseModel):
    tenant_id: str
    slug: str
    plan: str
    email: str
    status: str
    verification_expires_at: str
    verification_token: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class VerifyEmailResponse(BaseModel):
    tenant_id: str
    key_id: str
    api_key: str
    bootstrap_expires_at: str


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResendVerificationResponse(BaseModel):
    tenant_id: str
    email: str
    status: str
    verification_expires_at: str
    verification_token: str | None = None


class PromoteBootstrapKeyResponse(BaseModel):
    tenant_id: str
    key_id: str
    api_key: str
    revoked_bootstrap_key_id: str


def _require_idempotency_key(
    request: Request,
    settings: Settings,
    idempotency_key: str | None,
) -> None:
    if not settings.signup_idempotency_required:
        return
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")


def _client_ip_hash(request: Request) -> str:
    return hash_client_ip(extract_client_ip(request))


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SignupResponse:
    _require_idempotency_key(request, settings, idempotency_key)
    orchestrator = TenantOnboardingOrchestrator(db, settings=settings)
    client_ip_hash = _client_ip_hash(request)
    try:
        receipt = orchestrator.begin_signup(
            org_name=body.org_name,
            email=body.email,
            slug=body.slug,
            password=body.password,
            client_ip_hash=client_ip_hash,
        )
        db.commit()
    except SignupDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Signup is temporarily unavailable.") from exc
    except SignupRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail="rate limit exceeded") from exc
    except (DuplicateEmailError, VerificationPendingError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    except Exception:
        db.rollback()
        raise

    if receipt.status == "active":
        return SignupResponse(
            tenant_id=str(receipt.tenant_id),
            slug=receipt.slug,
            plan=receipt.plan,
            email=receipt.email.canonical,
            status=receipt.status,
            verification_expires_at=receipt.verification_expires_at.isoformat(),
            verification_token=None,
        )

    delivery = verification_delivery_from_settings(settings)
    verify_url = build_verify_url(
        base_url=settings.signup_verify_url_base or "http://localhost/verify-email",
        token=receipt.verification_token_plaintext,
    )
    try:
        delivery.send_signup_verification(
            to_email=receipt.email.raw,
            org_name=body.org_name,
            verify_url=verify_url,
            expires_at=receipt.verification_expires_at,
        )
    except DeliveryError as exc:
        try:
            orchestrator.mark_delivery_failed(member_id=receipt.member_id)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "verification_email_failed", "message": "verification email delivery failed"},
        ) from exc

    return SignupResponse(
        tenant_id=str(receipt.tenant_id),
        slug=receipt.slug,
        plan=receipt.plan,
        email=receipt.email.canonical,
        status=receipt.status,
        verification_expires_at=receipt.verification_expires_at.isoformat(),
        verification_token=(
            receipt.verification_token_plaintext if settings.signup_expose_verification_token else None
        ),
    )


@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> VerifyEmailResponse:
    _require_idempotency_key(request, settings, idempotency_key)
    orchestrator = TenantOnboardingOrchestrator(db, settings=settings)
    try:
        result = orchestrator.complete_verification(
            token=body.token,
            client_ip_hash=_client_ip_hash(request),
        )
        db.commit()
    except SignupRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail="rate limit exceeded") from exc
    except (InvalidVerificationTokenError, VerificationExpiredError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        db.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    response = VerifyEmailResponse(
        tenant_id=str(result.tenant_id),
        key_id=result.key_id,
        api_key=result.api_key,
        bootstrap_expires_at=result.bootstrap_expires_at.isoformat(),
    )
    request.state.onboarding_bootstrap_response = response
    return response


@router.post("/resend-verification", response_model=ResendVerificationResponse)
def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ResendVerificationResponse:
    orchestrator = TenantOnboardingOrchestrator(db, settings=settings)
    try:
        result = orchestrator.resend_verification(
            email=body.email,
            client_ip_hash=_client_ip_hash(request),
        )
        db.commit()
    except SignupDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Signup is temporarily unavailable.") from exc
    except SignupRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail="rate limit exceeded") from exc
    except MemberNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    delivery = verification_delivery_from_settings(settings)
    verify_url = build_verify_url(
        base_url=settings.signup_verify_url_base or "http://localhost/verify-email",
        token=result.verification_token_plaintext,
    )
    try:
        delivery.send_signup_verification(
            to_email=result.email.raw,
            org_name="your organization",
            verify_url=verify_url,
            expires_at=result.verification_expires_at,
        )
    except DeliveryError as exc:
        try:
            orchestrator.mark_delivery_failed(member_id=result.member_id)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "verification_email_failed", "message": "verification email delivery failed"},
        ) from exc

    return ResendVerificationResponse(
        tenant_id=str(result.tenant_id),
        email=result.email.canonical,
        status="pending_verification",
        verification_expires_at=result.verification_expires_at.isoformat(),
        verification_token=(result.verification_token_plaintext if settings.signup_expose_verification_token else None),
    )


@router.post("/promote-bootstrap-key", response_model=PromoteBootstrapKeyResponse)
def promote_bootstrap_key(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PromoteBootstrapKeyResponse:
    _require_idempotency_key(request, settings, idempotency_key)
    principal = getattr(request.state, "principal", None)
    if principal is None or not isinstance(principal, MachinePrincipal):
        from backend.api.errors import authentication_required_http

        raise authentication_required_http()

    orchestrator = TenantOnboardingOrchestrator(db, settings=settings)
    try:
        result = orchestrator.promote_bootstrap_key(principal=principal)
        db.commit()
    except BootstrapPromotionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        db.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return PromoteBootstrapKeyResponse(
        tenant_id=str(result.tenant_id),
        key_id=result.key_id,
        api_key=result.api_key,
        revoked_bootstrap_key_id=result.revoked_bootstrap_key_id,
    )

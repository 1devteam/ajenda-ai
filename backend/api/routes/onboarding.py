"""Self-serve tenant onboarding routes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
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
    ResendVerificationResult,
    SignupReceipt,
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
from backend.utils.email_canonical import canonicalize_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class SignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9\-]+$", max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=256)


class SignupResponse(BaseModel):
    email: str
    status: str
    verification_code: str | None = None
    tenant_id: str | None = None
    verification_token: str | None = None


class VerifyEmailRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=320)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    token: str | None = Field(default=None, min_length=8, max_length=512)


class VerifyEmailResponse(BaseModel):
    tenant_id: str
    key_id: str
    api_key: str
    bootstrap_expires_at: str


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResendVerificationResponse(BaseModel):
    email: str
    status: str
    verification_code: str | None = None
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


def _canonical_public_email(email: str) -> str:
    """Canonicalize an already validated public email for a stable generic response."""
    try:
        return canonicalize_email(email).canonical
    except ValueError:
        return email.strip().lower()


def _legacy_verification_envelope(*, email: str, code: str) -> str:
    """Serialize email+code for legacy passwordless staging clients without a hash scan."""
    return f"{code}:{_canonical_public_email(email)}"


def _resolve_verification_input(
    *,
    body: VerifyEmailRequest,
    settings: Settings,
) -> tuple[str, str]:
    if body.email is not None and body.code is not None:
        return body.email, body.code

    if body.token is not None and settings.signup_expose_verification_token:
        code, separator, email = body.token.partition(":")
        if separator and len(code) == 6 and code.isdigit() and email.strip():
            return email, code

    raise HTTPException(
        status_code=422,
        detail="email and six-digit verification code are required",
    )


def _signup_response(
    *,
    email: str,
    settings: Settings,
    verification_code: str | None = None,
    legacy_tenant_id: uuid.UUID | None = None,
    legacy_passwordless: bool = False,
) -> SignupResponse:
    exposed_code = verification_code if settings.signup_expose_verification_token else None
    legacy_enabled = bool(legacy_passwordless and exposed_code and legacy_tenant_id)
    canonical_email = _canonical_public_email(email)
    return SignupResponse(
        email=canonical_email,
        status="verification_required",
        verification_code=exposed_code,
        tenant_id=(str(legacy_tenant_id) if legacy_enabled else None),
        verification_token=(
            _legacy_verification_envelope(email=canonical_email, code=exposed_code)
            if legacy_enabled and exposed_code is not None
            else None
        ),
    )


def _resend_response(
    *,
    email: str,
    settings: Settings,
    verification_code: str | None = None,
) -> ResendVerificationResponse:
    exposed_code = verification_code if settings.signup_expose_verification_token else None
    canonical_email = _canonical_public_email(email)
    return ResendVerificationResponse(
        email=canonical_email,
        status="verification_if_pending",
        verification_code=exposed_code,
        verification_token=(
            _legacy_verification_envelope(email=canonical_email, code=exposed_code)
            if exposed_code is not None
            else None
        ),
    )


def _deliver_verification(
    *,
    settings: Settings,
    orchestrator: TenantOnboardingOrchestrator,
    db: Session,
    to_email: str,
    org_name: str,
    verification_code: str,
    verification_expires_at: datetime,
    member_id: uuid.UUID,
) -> None:
    """Attempt delivery without turning account state into a public enumeration oracle."""
    delivery = verification_delivery_from_settings(settings)
    verify_url = build_verify_url(
        base_url=settings.signup_verify_url_base or "http://localhost/verify-email",
        email=to_email,
    )
    try:
        delivery.send_signup_verification(
            to_email=to_email,
            org_name=org_name,
            verification_code=verification_code,
            verify_url=verify_url,
            expires_at=verification_expires_at,
        )
    except DeliveryError:
        logger.exception("verification_email_delivery_failed")
        try:
            orchestrator.mark_delivery_failed(member_id=member_id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("verification_delivery_failure_state_update_failed")


def _deliver_signup_receipt(
    *,
    settings: Settings,
    orchestrator: TenantOnboardingOrchestrator,
    db: Session,
    receipt: SignupReceipt,
    org_name: str,
) -> None:
    _deliver_verification(
        settings=settings,
        orchestrator=orchestrator,
        db=db,
        to_email=receipt.email.raw,
        org_name=org_name,
        verification_code=receipt.verification_token_plaintext,
        verification_expires_at=receipt.verification_expires_at,
        member_id=receipt.member_id,
    )


def _deliver_resend_result(
    *,
    settings: Settings,
    orchestrator: TenantOnboardingOrchestrator,
    db: Session,
    result: ResendVerificationResult,
) -> None:
    _deliver_verification(
        settings=settings,
        orchestrator=orchestrator,
        db=db,
        to_email=result.email.raw,
        org_name="your organization",
        verification_code=result.verification_token_plaintext,
        verification_expires_at=result.verification_expires_at,
        member_id=result.member_id,
    )


@router.post(
    "/signup",
    response_model=SignupResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SignupResponse:
    """Begin signup without revealing whether the submitted email already owns an account."""
    _require_idempotency_key(request, settings, idempotency_key)
    passwordless_programmatic = body.password is None
    if passwordless_programmatic:
        response.status_code = status.HTTP_201_CREATED

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
    except VerificationPendingError:
        db.rollback()
        try:
            result = orchestrator.resend_verification(
                email=body.email,
                client_ip_hash=client_ip_hash,
            )
            db.commit()
        except SignupRateLimitedError as exc:
            db.rollback()
            raise HTTPException(status_code=429, detail="rate limit exceeded") from exc
        except (MemberNotFoundError, DuplicateEmailError):
            db.rollback()
            return _signup_response(email=body.email, settings=settings)
        _deliver_resend_result(
            settings=settings,
            orchestrator=orchestrator,
            db=db,
            result=result,
        )
        return _signup_response(
            email=result.email.canonical,
            settings=settings,
            verification_code=result.verification_token_plaintext,
        )
    except DuplicateEmailError:
        db.rollback()
        return _signup_response(email=body.email, settings=settings)
    except SignupDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Signup is temporarily unavailable.") from exc
    except SignupRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail="rate limit exceeded") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        return _signup_response(email=body.email, settings=settings)
    except Exception:
        db.rollback()
        raise

    _deliver_signup_receipt(
        settings=settings,
        orchestrator=orchestrator,
        db=db,
        receipt=receipt,
        org_name=body.org_name,
    )
    return _signup_response(
        email=receipt.email.canonical,
        settings=settings,
        verification_code=receipt.verification_token_plaintext,
        legacy_tenant_id=receipt.tenant_id,
        legacy_passwordless=passwordless_programmatic,
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
    email, code = _resolve_verification_input(body=body, settings=settings)
    orchestrator = TenantOnboardingOrchestrator(db, settings=settings)
    try:
        result = orchestrator.complete_verification(
            email=email,
            code=code,
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

    verification_response = VerifyEmailResponse(
        tenant_id=str(result.tenant_id),
        key_id=result.key_id,
        api_key=result.api_key,
        bootstrap_expires_at=result.bootstrap_expires_at.isoformat(),
    )
    request.state.onboarding_bootstrap_response = verification_response
    return verification_response


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
)
def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ResendVerificationResponse:
    """Resend when pending while returning the same public response for unknown/active emails."""
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
    except MemberNotFoundError:
        db.rollback()
        return _resend_response(email=body.email, settings=settings)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    _deliver_resend_result(
        settings=settings,
        orchestrator=orchestrator,
        db=db,
        result=result,
    )
    return _resend_response(
        email=result.email.canonical,
        settings=settings,
        verification_code=result.verification_token_plaintext,
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

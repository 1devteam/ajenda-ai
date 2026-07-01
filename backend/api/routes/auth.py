"""Customer authentication routes — OIDC login and session management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.dependencies.db import get_db_session
from backend.auth.jwt_validator import JwtValidationError
from backend.auth.session_token import SessionTokenService
from backend.services.auth_login_abuse_guard import AuthLoginRateLimitedError
from backend.services.oidc_login_service import (
    OidcAccountNotFoundError,
    OidcAccountPendingVerificationError,
    OidcLoginDisabledError,
    OidcLoginService,
    OidcLoginValidationError,
    OidcMultipleTenantsError,
)
from backend.utils.client_ip import extract_client_ip, hash_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class OidcConfigResponse(BaseModel):
    enabled: bool
    provider: str
    client_id: str | None = None
    authorization_endpoint: str | None = None
    scopes: str


class OidcStartRequest(BaseModel):
    redirect_uri: str = Field(min_length=8, max_length=2048)
    code_challenge: str = Field(min_length=43, max_length=128)


class OidcStartResponse(BaseModel):
    login_intent_id: str
    authorization_url: str
    expires_at: str


class OidcCallbackRequest(BaseModel):
    login_intent_id: str
    code: str = Field(min_length=8, max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str = Field(min_length=8, max_length=2048)
    tenant_id: str | None = None


class CustomerSessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    tenant_id: str
    email: str
    org_name: str
    slug: str
    plan: str


class SessionRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


def _client_ip_hash(request: Request) -> str:
    return hash_client_ip(extract_client_ip(request))


@router.get("/oidc/config", response_model=OidcConfigResponse, status_code=status.HTTP_200_OK)
def oidc_config(
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OidcConfigResponse:
    """Return public OIDC configuration for the customer UI."""
    config = OidcLoginService(db, settings=settings).public_config()
    return OidcConfigResponse(
        enabled=config.enabled,
        provider=config.provider,
        client_id=config.client_id,
        authorization_endpoint=config.authorization_endpoint,
        scopes=config.scopes,
    )


@router.post("/oidc/start", response_model=OidcStartResponse, status_code=status.HTTP_200_OK)
def oidc_start(
    body: OidcStartRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OidcStartResponse:
    service = OidcLoginService(db, settings=settings)
    try:
        result = service.start_login(
            redirect_uri=body.redirect_uri,
            code_challenge=body.code_challenge,
            client_ip_hash=_client_ip_hash(request),
        )
        db.commit()
    except OidcLoginDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AuthLoginRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded") from exc
    except OidcLoginValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return OidcStartResponse(
        login_intent_id=result.login_intent_id,
        authorization_url=result.authorization_url,
        expires_at=result.expires_at,
    )


@router.post("/oidc/callback", response_model=CustomerSessionResponse, status_code=status.HTTP_200_OK)
def oidc_callback(
    body: OidcCallbackRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> CustomerSessionResponse:
    service = OidcLoginService(db, settings=settings)
    try:
        result = service.complete_login(
            login_intent_id=body.login_intent_id,
            code=body.code,
            code_verifier=body.code_verifier,
            redirect_uri=body.redirect_uri,
            client_ip_hash=_client_ip_hash(request),
            tenant_id=body.tenant_id,
        )
        db.commit()
    except OidcLoginDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AuthLoginRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded") from exc
    except OidcAccountPendingVerificationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "EMAIL_VERIFICATION_REQUIRED", "message": str(exc)},
        ) from exc
    except OidcMultipleTenantsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MULTIPLE_TENANTS",
                "message": str(exc),
                "tenants": [
                    {"tenant_id": choice.tenant_id, "org_name": choice.org_name, "slug": choice.slug}
                    for choice in exc.tenants
                ],
            },
        ) from exc
    except OidcAccountNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": str(exc)},
        ) from exc
    except OidcLoginValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except JwtValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="identity provider token validation failed",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return CustomerSessionResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        tenant_id=result.tenant_id,
        email=result.email,
        org_name=result.org_name,
        slug=result.slug,
        plan=result.plan,
    )


@router.post("/session/refresh", response_model=CustomerSessionResponse, status_code=status.HTTP_200_OK)
def refresh_session(
    body: SessionRefreshRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> CustomerSessionResponse:
    service = OidcLoginService(db, settings=settings)
    try:
        result = service.refresh_session(
            refresh_token=body.refresh_token,
            client_ip_hash=_client_ip_hash(request),
        )
        db.commit()
    except OidcLoginDisabledError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AuthLoginRateLimitedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded") from exc
    except (OidcAccountNotFoundError, OidcLoginValidationError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return CustomerSessionResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        tenant_id=result.tenant_id,
        email=result.email,
        org_name=result.org_name,
        slug=result.slug,
        plan=result.plan,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    token_service = SessionTokenService(
        signing_secret=settings.session_signing_secret,
        access_ttl_seconds=settings.session_access_ttl_seconds,
    )
    try:
        claims = token_service.validate_access_token(token)
    except JwtValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session token") from exc

    OidcLoginService(db, settings=settings).revoke_session(access_jti=claims.jti)
    db.commit()
    return {"status": "ok"}


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

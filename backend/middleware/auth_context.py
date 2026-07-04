"""Authentication context middleware.

Resolves and attaches an authenticated principal to every non-public request.
Also enforces cross-tenant rejection: if the authenticated principal's
tenant_id does not match the X-Tenant-Id header (set by TenantContextMiddleware),
the request is rejected with HTTP 403 Forbidden.

Cross-tenant check placement rationale:
  TenantContextMiddleware runs BEFORE AuthContextMiddleware (Tenant is outer,
  Auth is inner in the execution chain). Tenant sets request.state.tenant_id.
  Auth then resolves the principal and can compare principal.tenant_id against
  request.state.tenant_id. This is the only point in the middleware chain where
  both values are available simultaneously.

Auth split-brain fix: ApiKeyService is constructed with a scoped DB session
resolved from app.state on every request. There is no in-memory fallback.
Keys created via the API are immediately visible to authentication.

API Key format: ``X-Api-Key: <key_id>.<plaintext_secret>``
Bearer format:  ``Authorization: Bearer <jwt>``
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Protocol

from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.api.errors import api_json_response, authentication_required_json
from backend.auth.jwt_validator import JwtValidationError
from backend.auth.oidc import OidcAuthenticator
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.auth.rbac import RbacAuthorizer
from backend.auth.session_token import SessionTokenService
from backend.middleware.public_paths import is_public_path
from backend.repositories.customer_auth_session_repository import CustomerAuthSessionRepository
from backend.services.api_key_service import ApiKeyService

logger = logging.getLogger("ajenda.auth_context")


def _customer_session_auth_ready(settings: object) -> bool:
    ready = getattr(settings, "customer_session_auth_ready", None)
    if ready is not None:
        return bool(ready)
    return bool(
        getattr(settings, "oidc_login_enabled", False)
        and len(str(getattr(settings, "session_signing_secret", "")).strip()) >= 32
    )


class _SessionScopeLike(Protocol):
    def __iter__(self) -> Iterator[Session]: ...

    def __next__(self) -> Session: ...

    def throw(
        self,
        typ: type[BaseException],
        val: BaseException | None = None,
        tb: TracebackType | None = None,
    ) -> Session: ...


class _DatabaseRuntimeLike(Protocol):
    def session_context(self) -> AbstractContextManager[Session]: ...

    def session_scope(self) -> _SessionScopeLike | AbstractContextManager[Session]: ...


@contextmanager
def _db_session_context(db_runtime: _DatabaseRuntimeLike) -> Generator[Session, None, None]:
    if hasattr(db_runtime, "session_context"):
        with db_runtime.session_context() as session:
            yield session
        return

    scope = db_runtime.session_scope()

    if hasattr(scope, "__enter__") and hasattr(scope, "__exit__"):
        with scope as session:
            yield session
        return

    session = next(scope)
    try:
        yield session
    except Exception as exc:
        try:
            scope.throw(type(exc), exc, exc.__traceback__)
        except StopIteration:
            pass
        raise
    else:
        try:
            next(scope)
        except StopIteration:
            pass


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Fail-closed authentication middleware with explicit public-route allowlist.

    Every request to a non-public path must present valid credentials.
    Missing, malformed, or invalid credentials always return 401.
    Cross-tenant access (principal.tenant_id != X-Tenant-Id) returns 403.
    Internal errors return 500 — they never silently pass through.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if is_public_path(path):
            return await call_next(request)

        authorization: str | None = request.headers.get("Authorization")
        api_key_header: str | None = request.headers.get("X-Api-Key")
        tenant_id: str | None = getattr(request.state, "tenant_id", None)

        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            try:
                auth_response = await self._authenticate_bearer(request, token)
            except Exception:
                logger.exception("unexpected_error_in_auth_middleware")
                return JSONResponse(
                    status_code=500,
                    content={"detail": "internal authentication error"},
                )
            if auth_response is not None:
                return auth_response
            return await call_next(request)

        if api_key_header:
            if tenant_id is None:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "X-Tenant-Id header required for API key authentication"},
                )
            try:
                auth_response = await self._authenticate_api_key(request, tenant_id, api_key_header)
            except Exception:
                logger.exception("unexpected_error_in_auth_middleware")
                return JSONResponse(
                    status_code=500,
                    content={"detail": "internal authentication error"},
                )
            if auth_response is not None:
                return auth_response
            return await call_next(request)

        return authentication_required_json()

    def _check_cross_tenant(
        self,
        request: Request,
        principal_tenant_id: str | None,
    ) -> JSONResponse | None:
        """Return a 403 JSONResponse if the principal's tenant does not match
        the request's X-Tenant-Id. Returns None if the check passes.

        This check is only meaningful when both values are present. If either
        is absent (e.g., public routes, admin routes), the check is skipped.
        """
        request_tenant_id: str | None = getattr(request.state, "tenant_id", None)
        if request_tenant_id is None or principal_tenant_id is None:
            return None
        if str(principal_tenant_id) != str(request_tenant_id):
            logger.warning(
                "cross_tenant_access_rejected",
                extra={
                    "principal_tenant": str(principal_tenant_id),
                    "requested_tenant": str(request_tenant_id),
                    "path": request.url.path,
                },
            )
            return api_json_response(
                status_code=403,
                code="CROSS_TENANT_REJECTED",
                message="Cross-tenant access is not permitted.",
            )
        return None

    async def _authenticate_api_key(
        self,
        request: Request,
        tenant_id: str,
        api_key_header: str,
    ) -> Response | None:
        if "." not in api_key_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "malformed api key: expected <key_id>.<secret> format"},
            )
        key_id, plaintext = api_key_header.split(".", 1)

        db_runtime = request.app.state.database_runtime
        with _db_session_context(db_runtime) as session:
            service = ApiKeyService(session=session)
            try:
                principal = service.authenticate_machine(
                    tenant_id=tenant_id,
                    key_id=key_id,
                    plaintext=plaintext,
                )
            except ValueError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or revoked api key"},
                )

        if principal is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid or revoked api key"},
            )

        cross_tenant_error = self._check_cross_tenant(
            request,
            principal_tenant_id=getattr(principal, "tenant_id", None),
        )
        if cross_tenant_error is not None:
            return cross_tenant_error

        request.state.principal = principal
        return None

    async def _authenticate_bearer(self, request: Request, token: str) -> Response | None:
        settings = getattr(request.app.state, "settings", None)
        session_error: JwtValidationError | None = None
        if settings is not None and _customer_session_auth_ready(settings):
            try:
                principal = self._authenticate_customer_session(request, token=token, settings=settings)
            except (JwtValidationError, ValueError) as exc:
                session_error = exc if isinstance(exc, JwtValidationError) else JwtValidationError(str(exc))
                principal = None
            if principal is not None:
                cross_tenant_error = self._check_cross_tenant(
                    request,
                    principal_tenant_id=getattr(principal, "tenant_id", None),
                )
                if cross_tenant_error is not None:
                    return cross_tenant_error
                request.state.principal = principal
                return None

        oidc = getattr(request.app.state, "oidc_authenticator", None)
        if oidc is None:
            if settings is None:
                return JSONResponse(
                    status_code=500,
                    content={"detail": "internal authentication error"},
                )
            oidc = OidcAuthenticator(
                jwks_uri=settings.oidc_jwks_uri,
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
            )
        try:
            result = oidc.validate_bearer_token(token)
        except JwtValidationError as exc:
            logger.warning(
                "bearer_auth_failed",
                extra={"error": str(exc), "session_error": str(session_error) if session_error else None},
            )
            return api_json_response(
                status_code=401,
                code="INVALID_BEARER_TOKEN",
                message="invalid bearer token",
            )

        cross_tenant_error = self._check_cross_tenant(
            request,
            principal_tenant_id=getattr(result.principal, "tenant_id", None),
        )
        if cross_tenant_error is not None:
            return cross_tenant_error

        request.state.principal = result.principal
        return None

    def _authenticate_customer_session(self, request: Request, *, token: str, settings: object) -> UserPrincipal:
        from datetime import UTC, datetime

        from backend.app.config import Settings as AppSettings

        app_settings = settings if isinstance(settings, AppSettings) else request.app.state.settings
        token_service = SessionTokenService(
            signing_secret=app_settings.session_signing_secret,
            access_ttl_seconds=app_settings.session_access_ttl_seconds,
        )
        claims = token_service.validate_access_token(token)
        db_runtime = request.app.state.database_runtime
        with _db_session_context(db_runtime) as session:
            record = CustomerAuthSessionRepository(session).get_by_access_jti(claims.jti)
            now = datetime.now(tz=UTC)
            if record is None or record.revoked_at is not None or record.expires_at <= now:
                raise JwtValidationError("session has been revoked or expired")

        rbac = RbacAuthorizer()
        permissions = rbac.resolve_permissions(claims.roles)
        return UserPrincipal(
            subject_id=f"user:{claims.member_id}",
            tenant_id=claims.tenant_id,
            principal_type=PrincipalType.USER,
            roles=claims.roles,
            permissions=permissions,
            email=claims.email,
        )

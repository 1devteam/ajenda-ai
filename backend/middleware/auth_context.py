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
from collections.abc import Awaitable, Callable
from contextlib import contextmanager

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.auth.jwt_validator import JwtValidationError
from backend.auth.oidc import OidcAuthenticator
from backend.services.api_key_service import ApiKeyService

logger = logging.getLogger("ajenda.auth_context")


@contextmanager
def _db_session_context(db_runtime):
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


# Paths that bypass authentication entirely.
# Prometheus scraper and health probes must never be blocked.
_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/readiness",
    "/system/health",
    "/system/readiness",
    "/observability/metrics",
    "/operations/recovery",  # cross-tenant lease recovery — no auth required
    "/v1/operations/recovery",  # same, with v1 prefix (production mount)
    "/docs",
    "/openapi.json",
    "/redoc",
)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Fail-closed authentication middleware with explicit public-route allowlist.

    Every request to a non-public path must present valid credentials.
    Missing, malformed, or invalid credentials always return 401.
    Cross-tenant access (principal.tenant_id != X-Tenant-Id) returns 403.
    Internal errors return 500 — they never silently pass through.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        authorization: str | None = request.headers.get("Authorization")
        api_key_header: str | None = request.headers.get("X-Api-Key")
        tenant_id: str | None = getattr(request.state, "tenant_id", None)

        try:
            if authorization and authorization.startswith("Bearer "):
                token = authorization.removeprefix("Bearer ").strip()
                return await self._handle_bearer(request, call_next, token)

            if api_key_header:
                if tenant_id is None:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "X-Tenant-Id header required for API key authentication"},
                    )
                return await self._handle_api_key(request, call_next, tenant_id, api_key_header)

            return JSONResponse(
                status_code=401,
                content={"detail": "missing authentication credentials"},
            )

        except Exception:
            logger.exception("unexpected_error_in_auth_middleware")
            return JSONResponse(
                status_code=500,
                content={"detail": "internal authentication error"},
            )

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
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Cross-tenant access is not permitted.",
                    "code": "CROSS_TENANT_REJECTED",
                },
            )
        return None

    async def _handle_api_key(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        tenant_id: str,
        api_key_header: str,
    ) -> Response:
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
        return await call_next(request)

    async def _handle_bearer(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        token: str,
    ) -> Response:
        settings = request.app.state.settings
        oidc = OidcAuthenticator(
            jwks_uri=settings.oidc_jwks_uri,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
        )
        try:
            result = oidc.validate_bearer_token(token)
        except JwtValidationError as exc:
            logger.warning("bearer_auth_failed", extra={"error": str(exc)})
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid bearer token"},
            )

        cross_tenant_error = self._check_cross_tenant(
            request,
            principal_tenant_id=getattr(result.principal, "tenant_id", None),
        )
        if cross_tenant_error is not None:
            return cross_tenant_error

        request.state.principal = result.principal
        return await call_next(request)

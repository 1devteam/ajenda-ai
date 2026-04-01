"""Authentication context middleware.

Resolves and attaches an authenticated principal to every non-public request.

Auth split-brain fix: ApiKeyService is constructed with a scoped DB session
resolved from app.state on every request. There is no in-memory fallback.
Keys created via the API are immediately visible to authentication.

API Key format: ``X-Api-Key: <key_id>.<plaintext_secret>``
Bearer format:  ``Authorization: Bearer <jwt>``
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.auth.jwt_validator import JwtValidationError
from backend.auth.oidc import OidcAuthenticator
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.services.api_key_service import ApiKeyService

logger = logging.getLogger("ajenda.auth_context")

# Paths that bypass authentication entirely.
# Prometheus scraper and health probes must never be blocked.
_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/readiness",
    "/system/health",
    "/system/readiness",
    "/observability/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Fail-closed authentication middleware with explicit public-route allowlist.

    Every request to a non-public path must present valid credentials.
    Missing, malformed, or invalid credentials always return 401.
    Internal errors return 500 — they never silently pass through.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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

        # Resolve a DB session from app.state — the single source of truth.
        # No in-memory fallback exists. This is intentional.
        db_runtime = request.app.state.database_runtime
        with db_runtime.session_scope() as session:
            repo = ApiKeyRepository(session)
            service = ApiKeyService(session=session)
            try:
                principal = service.authenticate_machine(
                    tenant_id=tenant_id,
                    key_id=key_id,
                    plaintext=plaintext,
                )
            except ValueError:
                # Intentionally generic — prevents key enumeration
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or revoked api key"},
                )

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

        request.state.principal = result.principal
        return await call_next(request)

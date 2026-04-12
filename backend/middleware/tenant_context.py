"""TenantContextMiddleware — SaaS tenant isolation enforcement.

This middleware is the primary enforcement point for multi-tenant isolation
at the HTTP layer. It runs on every request and enforces:

  1. Presence of X-Tenant-Id header on all non-public paths.
  2. Tenant exists in the database (not a phantom tenant_id).
  3. Tenant is active (not suspended or deleted).
Public paths (exempt from X-Tenant-Id requirement):
  /health, /ready, /readiness — infrastructure probes (root-level)
  /system/health, /system/readiness — infrastructure probes (system-prefixed)
  /metrics — Prometheus scrape endpoint
  /v1/auth/*  — OIDC token exchange (tenant_id is in the token, not the header)
  /v1/admin/* — Admin control plane (cross-tenant by design, admin role required)

Design decisions:
  - The DB lookup is a lightweight SELECT on the tenants table (indexed on id).
    It is cached for the duration of the request on request.state.tenant.
  - Suspension check is done here (HTTP 403) rather than in the service layer
    to give a clear, consistent error before any business logic runs.
  - Cross-tenant rejection is enforced in AuthContextMiddleware (which runs
    after this middleware), where both the principal and tenant_id are available.
  - If the DB is unavailable, the middleware fails closed (HTTP 503).
  - If the app.state.database_runtime is not set (e.g., tests without lifespan),
    the DB check is skipped and only the header presence is enforced.
"""

from __future__ import annotations

import logging
import uuid as _uuid_module
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that do not require X-Tenant-Id. All comparisons use startswith().
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/ready",
    "/readiness",
    "/system/health",  # infrastructure health probe — no tenant context
    "/system/readiness",  # infrastructure readiness probe — no tenant context
    "/operations/recovery",  # cross-tenant lease recovery — no tenant context
    "/v1/operations/recovery",  # same, with v1 prefix (production mount)
    "/metrics",
    "/v1/auth",
    "/v1/admin",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Enforce multi-tenant isolation on every inbound HTTP request.

    Sets request.state.tenant_id and request.state.tenant on success.
    Rejects with 400, 403, 404, or 503 on any isolation violation.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # --- Public paths: skip tenant enforcement ---
        if any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES):
            request.state.tenant_id = None
            request.state.tenant = None
            return await call_next(request)

        # --- Require X-Tenant-Id header ---
        tenant_id_str = request.headers.get("X-Tenant-Id")
        if not tenant_id_str:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "X-Tenant-Id header is required for this endpoint.",
                    "code": "MISSING_TENANT_ID",
                },
            )

        # --- Validate UUID format ---
        try:
            tenant_uuid = _uuid_module.UUID(tenant_id_str)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": f"X-Tenant-Id {tenant_id_str!r} is not a valid UUID.",
                    "code": "INVALID_TENANT_ID_FORMAT",
                },
            )

        # --- DB validation: tenant exists and is active ---
        database_runtime = getattr(request.app.state, "database_runtime", None)
        if database_runtime is not None:
            try:
                session = database_runtime.session_factory()
                try:
                    from backend.repositories.tenant_repository import TenantRepository

                    repo = TenantRepository(session)
                    tenant = repo.get(tenant_uuid)

                    if tenant is None:
                        return JSONResponse(
                            status_code=404,
                            content={
                                "detail": "Tenant not found.",
                                "code": "TENANT_NOT_FOUND",
                            },
                        )
                    if tenant.is_deleted():
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "This tenant account has been deleted.",
                                "code": "TENANT_DELETED",
                            },
                        )
                    if tenant.is_suspended():
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": (
                                    "This tenant account is currently suspended. Contact support to restore access."
                                ),
                                "code": "TENANT_SUSPENDED",
                            },
                        )
                    request.state.tenant = tenant
                finally:
                    session.close()
            except Exception:
                logger.exception("tenant_lookup_failed", extra={"tenant_id": tenant_id_str})
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Service temporarily unavailable. Please retry.",
                        "code": "DB_UNAVAILABLE",
                    },
                )
        else:
            # No DB runtime (e.g., unit tests) — skip DB check
            request.state.tenant = None

        # --- Set tenant context on request state ---
        # Cross-tenant rejection is handled by AuthContextMiddleware, which
        # runs after this middleware and has access to the resolved principal.
        request.state.tenant_id = tenant_id_str

        return await call_next(request)

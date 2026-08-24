"""TenantContextMiddleware — SaaS tenant isolation enforcement.

This middleware is the primary enforcement point for multi-tenant isolation
at the HTTP layer. It runs on every request and enforces:

  1. Presence of X-Tenant-Id header on all tenant-scoped paths.
  2. Tenant exists in the database (not a phantom tenant_id).
  3. Tenant is active (not suspended or deleted).

Tenant-header-exempt paths include infrastructure probes, public auth/onboarding
flows, Stripe webhook ingress, and authenticated platform control-plane routes.
Authentication exemption is evaluated independently by AuthContextMiddleware.

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
from starlette.responses import Response

from backend.api.errors import api_json_response
from backend.middleware.public_paths import is_tenant_exempt_path

logger = logging.getLogger(__name__)


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

        # --- Tenant-header-exempt paths: skip tenant enforcement only. ---
        # AuthContextMiddleware independently decides whether auth is required.
        if is_tenant_exempt_path(path):
            request.state.tenant_id = None
            request.state.tenant = None
            return await call_next(request)

        # --- Require X-Tenant-Id header ---
        tenant_id_str = request.headers.get("X-Tenant-Id")
        if not tenant_id_str:
            return api_json_response(
                status_code=400,
                code="MISSING_TENANT_ID",
                message="X-Tenant-Id header is required for this endpoint.",
            )

        # --- Validate UUID format ---
        try:
            tenant_uuid = _uuid_module.UUID(tenant_id_str)
        except ValueError:
            return api_json_response(
                status_code=400,
                code="INVALID_TENANT_ID_FORMAT",
                message=f"X-Tenant-Id {tenant_id_str!r} is not a valid UUID.",
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
                        return api_json_response(
                            status_code=404,
                            code="TENANT_NOT_FOUND",
                            message="Tenant not found.",
                        )
                    if tenant.is_deleted():
                        return api_json_response(
                            status_code=403,
                            code="TENANT_DELETED",
                            message="This tenant account has been deleted.",
                        )
                    if tenant.is_suspended():
                        return api_json_response(
                            status_code=403,
                            code="TENANT_SUSPENDED",
                            message=("This tenant account is currently suspended. Contact support to restore access."),
                        )
                    request.state.tenant = tenant
                finally:
                    session.close()
            except Exception:
                logger.exception("tenant_lookup_failed", extra={"tenant_id": tenant_id_str})
                return api_json_response(
                    status_code=503,
                    code="DB_UNAVAILABLE",
                    message="Service temporarily unavailable. Please retry.",
                )
        else:
            # No DB runtime (e.g., unit tests) — skip DB check
            request.state.tenant = None

        # --- Set tenant context on request state ---
        # Cross-tenant rejection is handled by AuthContextMiddleware, which
        # runs after this middleware and has access to the resolved principal.
        request.state.tenant_id = tenant_id_str

        return await call_next(request)

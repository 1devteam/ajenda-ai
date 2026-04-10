"""Ajenda AI — FastAPI application entrypoint.

Startup sequence (lifespan):
  1. Load and validate Settings (validate_runtime_contract raises on misconfiguration)
  2. Configure structured logging
  3. Initialize DatabaseRuntime (connection pool)
  4. Build and ping queue adapter (fail-fast on startup if queue is unreachable)
  5. Store shared resources on app.state for dependency injection
  6. Yield (application serves requests)
  7. Dispose database connection pool on shutdown

Middleware stack (outermost to innermost — applied in reverse registration order):
  1. SecurityHeadersMiddleware  — injects HSTS, CSP, X-Frame-Options, etc.
  2. IdempotencyMiddleware      — deduplicates mutating requests by Idempotency-Key header
  3. RateLimitMiddleware        — per-(tenant, principal, route) fixed-window rate limiting
  4. TenantContextMiddleware    — extracts and validates X-Tenant-Id header
  5. AuthContextMiddleware      — resolves principal from JWT or API key, sets request.state
  6. RequestContextMiddleware   — assigns a unique request_id to every request

Note on middleware ordering: FastAPI/Starlette applies middleware in reverse
registration order. The last middleware added is the outermost wrapper. We
register SecurityHeaders last so it wraps everything and injects headers on
all responses including error responses from inner middleware.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from fastapi import FastAPI

from backend.api.router import build_api_router
from backend.app.config import get_settings
from backend.app.logging import configure_logging
from backend.db.session import DatabaseRuntime
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.idempotency import IdempotencyMiddleware
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware
from backend.queue import build_queue_adapter


def _resolve_app_version() -> str:
    """Return installed package version, with a safe local fallback."""
    try:
        return package_version("ajenda-ai")
    except PackageNotFoundError:
        return "0.0.0+local"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Validates configuration, initialises shared resources, and ensures clean
    shutdown. Any exception raised here before the yield will prevent the
    application from starting — this is intentional fail-fast behaviour.
    """
    # Step 1: Load and validate settings. validate_runtime_contract() raises
    # ValueError on misconfiguration (e.g. redis adapter with no URL in prod).
    settings = get_settings()

    # Step 2: Configure structured logging before any other output
    configure_logging(settings)

    # Step 3: Initialise database connection pool
    database_runtime = DatabaseRuntime(settings)

    # Step 4: Build queue adapter and verify connectivity
    queue_adapter = build_queue_adapter(settings)
    if not queue_adapter.ping():
        raise RuntimeError(
            f"Queue adapter '{settings.queue_adapter}' failed startup ping. "
            "Check AJENDA_QUEUE_URL and queue service health before starting."
        )

    # Step 5: Store shared resources on app.state for dependency injection
    app.state.settings = settings
    app.state.database_runtime = database_runtime
    app.state.queue_adapter = queue_adapter

    try:
        yield
    finally:
        # Step 7: Clean shutdown — dispose connection pool
        database_runtime.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Registers all middleware and routes. The middleware stack is registered
    in innermost-first order (FastAPI reverses the order at runtime).
    """
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=_resolve_app_version(),
        lifespan=lifespan,
        # Disable docs in production to reduce attack surface
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url="/redoc" if settings.env != "production" else None,
        openapi_url="/openapi.json" if settings.env != "production" else None,
    )

    # Mount all API routes
    app.include_router(build_api_router())

    # --- Middleware stack (registered innermost-first) ---
    #
    # Starlette applies middleware in REVERSE registration order.
    # The LAST middleware added here becomes the OUTERMOST wrapper.
    #
    # Execution order (outermost → innermost):
    #   SecurityHeaders → Idempotency → RateLimit → Tenant → Auth → RequestContext → route
    #
    # Tenant MUST execute before Auth because:
    #   - AuthContextMiddleware reads request.state.tenant_id (set by TenantContextMiddleware)
    #     to scope API key lookups to the correct tenant.
    #   - Without tenant_id, API key auth falls back to a tenant-agnostic lookup,
    #     which is incorrect and a potential cross-tenant information leak.
    #
    # Auth MUST execute before RateLimit because:
    #   - RateLimitMiddleware uses request.state.principal for per-principal bucketing.

    # Innermost: request context (assigns request_id to every request)
    app.add_middleware(RequestContextMiddleware)

    # Auth context: resolves principal from JWT or API key.
    # Registered before Tenant so that Tenant executes first at runtime.
    app.add_middleware(AuthContextMiddleware)

    # Tenant context: extracts X-Tenant-Id, validates tenant active status,
    # enforces cross-tenant rejection. Executes before Auth at runtime.
    app.add_middleware(TenantContextMiddleware)

    # Rate limiting: per-(tenant, principal, route) fixed-window
    app.add_middleware(RateLimitMiddleware)

    # Idempotency: deduplicates POST/PUT/PATCH by Idempotency-Key header
    app.add_middleware(IdempotencyMiddleware)

    # Outermost: security headers — applied to ALL responses including errors
    app.add_middleware(SecurityHeadersMiddleware)

    return app


app = create_app()

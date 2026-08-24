"""Shared path classification for tenant and authentication middleware."""

from __future__ import annotations

# Paths that intentionally bypass authentication. Keep this list limited to
# infrastructure probes and unauthenticated ingress flows.
AUTH_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/ready",
    "/readiness",
    "/system/health",
    "/system/readiness",
    "/v1/system/health",
    "/v1/system/readiness",
    "/metrics",
    "/observability/metrics",
    "/v1/observability/metrics",
    "/v1/billing/webhook/",
    "/v1/auth/oidc/",
    "/v1/auth/session/refresh",
    "/v1/auth/password",
    "/v1/onboarding/signup",
    "/v1/onboarding/verify-email",
    "/v1/onboarding/resend-verification",
    "/docs",
    "/openapi.json",
    "/redoc",
)

# Paths that do not require an X-Tenant-Id header. Some of these are still
# authenticated control-plane routes. In particular, admin and global recovery
# are tenant-header exempt but MUST NOT bypass AuthContextMiddleware.
TENANT_EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    *AUTH_PUBLIC_PATH_PREFIXES,
    "/v1/admin",
    "/v1/operations/recovery",
)

# Backwards-compatible name used by AuthContextMiddleware and existing tests.
# "Public" now means authentication-public, not merely tenant-header-exempt.
PUBLIC_PATH_PREFIXES = AUTH_PUBLIC_PATH_PREFIXES


def is_public_path(path: str) -> bool:
    """Return True only when authentication may be bypassed."""
    return any(path.startswith(prefix) for prefix in AUTH_PUBLIC_PATH_PREFIXES)


def is_tenant_exempt_path(path: str) -> bool:
    """Return True when the request does not require X-Tenant-Id."""
    return any(path.startswith(prefix) for prefix in TENANT_EXEMPT_PATH_PREFIXES)

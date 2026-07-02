"""Shared public-path allowlists for tenant and auth middleware."""

from __future__ import annotations

# Paths that bypass tenant header enforcement and authentication.
PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
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
    "/v1/admin",
    "/v1/billing/webhook/",
    "/v1/auth/oidc/",
    "/v1/auth/session/refresh",
    "/v1/onboarding/signup",
    "/v1/onboarding/verify-email",
    "/v1/onboarding/resend-verification",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def is_public_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)

"""
Security Headers Middleware for Omnipath v2
Adds OWASP-recommended HTTP security headers to every response.

Headers applied:
- Strict-Transport-Security (HSTS)
- Content-Security-Policy (CSP)
- X-Content-Type-Options
- X-Frame-Options
- X-XSS-Protection
- Referrer-Policy
- Permissions-Policy
- Cache-Control (for API responses)

Built with Pride for Obex Blackvault
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from backend.config.settings import settings
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that injects OWASP-recommended security headers into every HTTP response.

    In production mode all headers are enforced at their strictest values.
    In development mode CSP is relaxed to allow the Swagger UI and ReDoc to function.

    Args:
        app: The ASGI application.
        environment: Override the deployment environment (defaults to settings.ENVIRONMENT).
                     Useful for testing without patching the module-level settings.
    """

    def __init__(self, app, environment: str | None = None) -> None:
        super().__init__(app)
        self._environment = environment

    # Content-Security-Policy directives
    _CSP_PRODUCTION = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    # Relaxed CSP for development — allows Swagger UI CDN resources
    _CSP_DEVELOPMENT = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and add security headers to response."""
        response: Response = await call_next(request)

        is_production = (self._environment or settings.ENVIRONMENT) == "production"

        # ── Strict-Transport-Security ──────────────────────────────────────
        # Only meaningful over HTTPS; include in production only
        if is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        # ── Content-Security-Policy ────────────────────────────────────────
        csp = self._CSP_PRODUCTION if is_production else self._CSP_DEVELOPMENT
        response.headers["Content-Security-Policy"] = csp

        # ── X-Content-Type-Options ─────────────────────────────────────────
        # Prevents MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # ── X-Frame-Options ────────────────────────────────────────────────
        # Prevents clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # ── X-XSS-Protection ──────────────────────────────────────────────
        # Legacy header; still useful for older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # ── Referrer-Policy ────────────────────────────────────────────────
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # ── Permissions-Policy ─────────────────────────────────────────────
        # Disable browser features not used by the API
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=()"
        )

        # ── Cache-Control ──────────────────────────────────────────────────
        # API responses must not be cached by intermediaries
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"

        # ── Remove server identification headers ───────────────────────────
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        return response

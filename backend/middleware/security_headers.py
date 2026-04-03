"""Security headers middleware for Ajenda AI.

Adds the following headers to every response:

- Strict-Transport-Security (HSTS): enforces HTTPS for 1 year, includes subdomains
- X-Content-Type-Options: prevents MIME-type sniffing
- X-Frame-Options: blocks clickjacking via iframe embedding
- X-XSS-Protection: legacy XSS filter for older browsers
- Referrer-Policy: limits referrer leakage to same-origin
- Content-Security-Policy: restricts resource loading to same origin by default;
  the API-only policy is intentionally strict — no scripts, no styles, no images
  from external origins. Adjust if a web UI is added.
- Permissions-Policy: disables browser features not used by this API

This middleware is applied unconditionally to all responses including error
responses, health probes, and metrics endpoints. The only exception is the
/metrics endpoint which must remain accessible to Prometheus scrapers — HSTS
still applies there.

Design notes:
- Does NOT use BaseHTTPMiddleware to avoid double-body-read issues with streaming
  responses. Uses raw ASGI middleware instead.
- Header values are computed once at class instantiation (not per-request) since
  they are static strings.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# HSTS max-age: 1 year in seconds
_HSTS_MAX_AGE = 31_536_000

# CSP for a pure API backend: deny all resource loading except self.
# Adjust if a Swagger UI or ReDoc is served.
_CSP = (
    "default-src 'self'; "
    "script-src 'none'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none';"
)

_PERMISSIONS_POLICY = (
    "camera=(), "
    "microphone=(), "
    "geolocation=(), "
    "interest-cohort=()"
)

_STATIC_HEADERS: list[tuple[bytes, bytes]] = [
    (b"strict-transport-security", f"max-age={_HSTS_MAX_AGE}; includeSubDomains; preload".encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"content-security-policy", _CSP.encode()),
    (b"permissions-policy", _PERMISSIONS_POLICY.encode()),
]


class SecurityHeadersMiddleware:
    """Raw ASGI middleware that injects security headers into every response.

    Usage (in main.py)::

        app.add_middleware(SecurityHeadersMiddleware)

    Because this is a raw ASGI middleware (not BaseHTTPMiddleware), it does not
    buffer response bodies and is safe to use with streaming endpoints.
    """

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self._app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            # Pass through WebSocket and lifespan events unchanged
            await self._app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Inject security headers before the response headers are sent.
                # We append to the existing headers list rather than replacing it
                # so that route-level headers (e.g. Content-Type) are preserved.
                existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing.extend(_STATIC_HEADERS)
                message = {**message, "headers": existing}
            await send(message)

        await self._app(scope, receive, send_with_security_headers)

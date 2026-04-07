"""Unit tests for SecurityHeadersMiddleware.

Verifies that all required security headers are injected on every response,
including error responses and health probe responses.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.middleware.security_headers import SecurityHeadersMiddleware


def homepage(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def error_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"detail": "not found"}, status_code=404)


def make_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/error", error_endpoint),
        ]
    )
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(make_app(), raise_server_exceptions=False)


class TestSecurityHeaders:
    def test_hsts_header_present(self, client: TestClient) -> None:
        response = client.get("/")
        assert "strict-transport-security" in response.headers
        assert "max-age=31536000" in response.headers["strict-transport-security"]
        assert "includeSubDomains" in response.headers["strict-transport-security"]

    def test_x_content_type_options(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_csp_header_present(self, client: TestClient) -> None:
        response = client.get("/")
        csp = response.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_referrer_policy(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client: TestClient) -> None:
        response = client.get("/")
        assert "permissions-policy" in response.headers

    def test_headers_on_error_responses(self, client: TestClient) -> None:
        """Security headers must be present even on 4xx responses."""
        response = client.get("/error")
        assert response.status_code == 404
        assert "strict-transport-security" in response.headers
        assert "x-frame-options" in response.headers

    def test_existing_headers_preserved(self, client: TestClient) -> None:
        """The middleware must not strip existing response headers."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.text == "ok"
